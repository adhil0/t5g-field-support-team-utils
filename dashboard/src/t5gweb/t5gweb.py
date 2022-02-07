"""core CRUD functions for t5gweb"""
import logging
import os
import jira
from datetime import datetime, timezone, date
import pkg_resources
import re
from werkzeug.exceptions import abort
from . import libtelco5g
import json
import sys
from copy import deepcopy

def set_cfg():
        # Set the default configuration values
    cfg = libtelco5g.set_defaults()

    # Override the defaults and configuration file settings 
    # with any environmental settings
    trcfg = libtelco5g.read_env_config(cfg.keys())
    for key in trcfg:
        cfg[key] = trcfg[key]

    # Fix some of the settings so they are easier to use
    cfg['labels'] = cfg['labels'].split(',')

    cfg['offline_token'] = os.environ.get('offline_token')
    cfg['password'] = os.environ.get('jira_pass')

    return cfg

def get_new_cases():
    """get new cases created since X days ago"""

    # get cases from cache
    cases = libtelco5g.redis_get("cases")

    interval = 7
    new_cases = []
    for case in sorted(cases.items(), key = lambda i: i[1]['severity']):
        create_date = datetime.strptime(case[1]['createdate'], '%Y-%m-%dT%H:%M:%SZ')
        time_diff = datetime.now() - create_date
        if time_diff.days < 7:
            case[1]['severity'] = re.sub('\(|\)| |[0-9]', '', case[1]['severity'])
            case[1]['number'] = case[0]
            new_cases.append(case[1])
    return new_cases

def get_new_comments(new_comments_only=True):

    # fetch cards from redis cache
    cards = libtelco5g.redis_get('cards')
    logging.warning("found %d JIRA cards" % (len(cards)))
    time_now = datetime.now(timezone.utc)

    # filter cards for comments created in the last week
    # and sort between telco and cnv
    detailed_cards= {}
    telco_account_list = []
    cnv_account_list = []
    for card in cards:
        if new_comments_only:
            comments = [comment[0] for comment in cards[card]['comments'] if (time_now - datetime.strptime(comment[1], '%Y-%m-%dT%H:%M:%S.%f%z')).days < 7]
        else:
            comments = [comment[0] for comment in cards[card]['comments']]
        if len(comments) == 0:
            #logging.warning("no recent updates for {}".format(card))
            continue # no updates
        else:
            detailed_cards[card] = cards[card] #TODO right now will display all comments, even old ones... might be better?
        if "shift_telco5g" in cards[card]['tags'] and cards[card]['account'] not in telco_account_list:
            telco_account_list.append(cards[card]['account'])
        if "cnv" in cards[card]['tags'] and cards[card]['account'] not in cnv_account_list:
            cnv_account_list.append(cards[card]['account'])
    telco_account_list.sort()
    cnv_account_list.sort()
    logging.warning("found %d detailed cards" % (len(detailed_cards)))

    # organize cards by status
    telco_accounts, cnv_accounts = organize_cards(detailed_cards, telco_account_list, cnv_account_list)
    return telco_accounts, cnv_accounts

def get_trending_cards():

    # fetch cards from redis cache
    cards = libtelco5g.redis_get('cards')
    time_now = datetime.now(timezone.utc)

    # get a list of trending cards
    trending_cards = [card for card in cards if 'Trends' in cards[card]['labels']]

    #TODO: timeframe?
    detailed_cards = {}
    telco_account_list = []
    for card in trending_cards:
        detailed_cards[card] = cards[card]
        account = cards[card]['account']
        if account not in telco_account_list:
            telco_account_list.append(cards[card]['account'])

    telco_accounts, cnv_accounts = organize_cards(detailed_cards, telco_account_list)
    return telco_accounts
    

def plots():

    summary = libtelco5g.get_card_summary()
    return summary

def replace_links(detailed_cards):
    """Replace JIRA style links in card's comments with equivalent HTML links"""
    for card in detailed_cards:
        for comment in range(len(detailed_cards[card]["comments"])):
            detailed_cards[card]["comments"][comment] = re.sub(r'(?<!\||\s)\s*?((http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])?)',"<a href=\""+r'\g<0>'+"\" target='_blank'>"+r'\g<0>'"</a>", detailed_cards[card]["comments"][comment])
            detailed_cards[card]["comments"][comment] = re.sub(r'\[([\s\w!"#$%&\'()*+,-.\/:;<=>?@[^_`{|}~]*?\s*?)\|\s*?((http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])?[\s]*)\]',"<a href=\""+r'\2'+"\" target='_blank'>"+r'\1'+"</a>", detailed_cards[card]["comments"][comment])
    return detailed_cards


def add_case_number(conn, cards):
    """Associates each card with its case number and drops cards without a Support Case Link"""
    cards_dict = {}
    for card in cards:
        cards_dict[card.key] = None

    #Associate each card with its corresponding case number
    for card_id in cards_dict:
        links = conn.remote_links(card_id)
        for link in links:
            t = conn.remote_link(card_id, link)
            if t.raw['object']['title'] == "Support Case":
                t_case_number = libtelco5g.get_case_number(t.raw['object']['url'])
                if len(t_case_number) > 0:
                    cards_dict[card_id] = t_case_number
    # Get rid of cards with no Support Case Link
    linked_cards = {card: case for card, case in cards_dict.items() if case is not None}
    return linked_cards

def organize_cards(detailed_cards, telco_account_list, cnv_account_list=None):
    """Group cards by account"""
    
    telco_accounts = {}
    cnv_accounts = {}

    states = {"To Do":{}, "In Progress": {}, "Code Review": {},"QE Review": {}, "Done": {}}
    
    for account in telco_account_list:
        telco_accounts[account] = deepcopy(states)
    if cnv_account_list:
        for account in cnv_account_list:
            cnv_accounts[account] = deepcopy(states)
    
    for i in detailed_cards.keys():
        status = detailed_cards[i]['card_status']
        tags =  detailed_cards[i]['tags']
        account = detailed_cards[i]['account']
        #logging.warning("card: %s\tstatus: %s\ttags: %s\taccount: %s" % (i, status, tags, account))
        if "shift_telco5g" in tags:
            telco_accounts[account][status][i] = detailed_cards[i]
        if cnv_account_list and "cnv" in tags:
            cnv_accounts[account][status][i] = detailed_cards[i]
  
    return telco_accounts, cnv_accounts

def get_previous_quarter():
    """Creates JIRA query to get cards from previous quarter"""
    day = date.today()
    if 1 <= day.month <= 3:
        query_range = '((updated >= "{}-10-01" AND updated <= "{}-12-31") OR (created >= "{}-10-01" AND created <= "{}-12-31"))'.format(day.year-1, day.year-1, day.year-1, day.year-1)
    elif 4 <= day.month <= 6:
        query_range = '((updated >= "{}-1-01" AND updated <= "{}-3-30") OR (created >= "{}-1-01" AND created <= "{}-3-30"))'.format(day.year, day.year, day.year, day.year)
    elif 7 <= day.month <= 9:
        query_range = '((updated >= "{}-4-01" AND updated <= "{}-6-30") OR (created >= "{}-4-01" AND created <= "{}-6-30"))'.format(day.year, day.year, day.year, day.year)
    elif 10 <= day.month <= 12:
        query_range = '((updated >= "{}-7-01" AND updated <= "{}-9-30") OR (created >= "{}-7-01" AND created <= "{}-9-30"))'.format(day.year, day.year, day.year, day.year)
    return query_range