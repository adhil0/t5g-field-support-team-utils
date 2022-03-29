#! /usr/bin/python -W ignore

'''
This script takes a configuration file name as its only argument.
Not passing a configuration file as an option will cause the script
to use its default settings and any environmental settings.

Setting set in the environment override the ones in the configuration file.
'''

from __future__ import print_function
import os
import getpass
import datetime
from jira import JIRA
from jira.client import ResultList
from jira.resources import Issue
import re
import pprint
import requests
from urllib.parse import urlparse
import smtplib
from email.message import EmailMessage
import random
from slack_sdk import WebClient
import redis
import json
import logging
import time
import bugzilla
import smartsheet

# for portal to jira mapping
portal2jira_sevs = {
    "1 (Urgent)"    : "Critical",
    "2 (High)"      : "Major",
    "3 (Normal)"    : "Normal",
    "4 (Low)"       : "Minor"
}

def jira_connection(cfg):

    jira = JIRA(
        server = cfg['server'],
        token_auth = cfg['password']
    )

    return jira

def get_project_id(conn, name):
    ''' Take a project name and return its id
    conn    - Jira connection object
    name    - project name

    Returns Jira object.
    Notable fields:
        .components  - list of Jira objects
            [<JIRA Component: name='CNV CI and Release', id='12333847'>,...]
        .description - string
        .id          - numerical string
        .key         - string
            KNIECO
        .name        - string
            KNI Ecosystem
    '''

    project = conn.project(name)
    return project

def get_component_id(conn, projid, name):
    ''' Take a component name and return its id
    conn    - Jira connection object
    projid  - component id
    name    - component name

    Returns Jira object.
    Notable fields:
        .description - string
        .id          - numerical string
        .name        - string
            KNI Labs & Field
        .project     - string
            KNIECO
        .projectId   - numerical string
    '''

    components=conn.project_components(projid)
    component = next(item for item in components if item.name == name)
    return component

def get_board_id(conn, name):
    ''' Take a board name as input and return its id
    conn    - Jira connection object
    name    - board name

    Returns Jira object.
    Notable fields:
        .id          - numerical string
        .name        - string
            KNI ECO Labs & Field
    '''

    boards = conn.boards(name=name)
    return boards[0]

def get_latest_sprint(conn, bid, sprintname):
    ''' Take a board id and return the current sprint
    conn    - Jira connection object
    name    - board id

    Returns Jira object.
    Notable fields:
        .id          - numerical string
        .name        - string
            ECO Labs & Field Sprint 188
    '''

    sprints = conn.sprints(bid, state="active")
    return sprints[0]

def get_last_sprint(conn, bid, sprintname):
    this_sprint = get_latest_sprint(conn, bid, sprintname)
    sprint_number = re.search('\d*$', this_sprint.name)[0]
    last_sprint_number = int(sprint_number) - 1
    board = conn.sprints(bid) # still seems to return everything?
    last_sprint_name = sprintname + ".*" + str(last_sprint_number)
    
    for b in board:
        if re.search(last_sprint_name, b.name):
            return b

def get_sprint_summary(conn, bid, sprintname, team):
    totals = {}
    last_sprint = get_last_sprint(conn, bid, sprintname)
    sid = last_sprint.id
    
    for member in team:
        user = member['jira_user']
        user = user.replace('@', '\\u0040')
        completed_cards = conn.search_issues('sprint=' + str(sid) + ' and assignee = ' + str(user) + ' and status = "DONE"', 0, 1000).iterable
        print("%s completed %d cards" % (member['name'], len(completed_cards)))
    # kobi
    user = 'kgershon@redhat.com'
    user = user.replace('@', '\\u0040')
    name = 'Kobi Gershon'
    completed_cards = conn.search_issues('sprint=' + str(sid) + ' and assignee = ' + str(user) + ' and status = "DONE"', 0, 1000).iterable
    print("%s completed %d cards" % (name, len(completed_cards)))

def get_card_summary():

    cards = redis_get('cards')
    backlog = [card for card in cards if cards[card]['card_status'] == 'Backlog']
    in_progress = [card for card in cards if cards[card]['card_status'] == 'In Progress']
    code_review = [card for card in cards if cards[card]['card_status'] == 'Code Review']
    qe_review = [card for card in cards if cards[card]['card_status'] == 'QE Review']
    done = [card for card in cards if cards[card]['card_status'] == 'Done']
    summary = {}
    summary['backlog'] = len(backlog)
    summary['in_progress'] = len(in_progress)
    summary['code_review'] = len(code_review)
    summary['qe_review'] = len(qe_review)
    summary['done'] = len(done)
    return summary

def get_case_number(link, pfilter='cases'):
    ''' Accepts RH Support Case URL and returns the case number
        - https://access.redhat.com/support/cases/0123456
        - https://access.redhat.com/support/cases/#/case/0123456
    '''
    parsed_url = urlparse(link)

    if pfilter == 'cases':
        if 'cases' in parsed_url.path and parsed_url.netloc == 'access.redhat.com':
            if len(parsed_url.fragment) > 0 and 'case' in parsed_url.fragment:
                return parsed_url.fragment.split('/')[2]
            if len(parsed_url.path) > 0 and 'cases' in parsed_url.path:
                return parsed_url.path.split('/')[3]
    return ''

def get_random_member(team):
    return random.choice(team)

def create_cards(cfg, new_cases, action='none'):
    '''
    cfg    - configuration
    cases  - dictionary of all cases
    needed - list of cases that need a card created
    '''

    email_content = []
    new_cards = {}

    logging.warning("attempting to connect to jira...")
    jira_conn = jira_connection(cfg)
    project = get_project_id(jira_conn, cfg['project'])
    component = get_component_id(jira_conn, project.id, cfg['component'])
    board = get_board_id(jira_conn, cfg['board'])
    sprint = get_latest_sprint(jira_conn, board.id, cfg['sprintname'])
    
    cases = redis_get('cases')

    for case in new_cases:
        assignee = None
        for member in cfg['team']:
            for account in member["accounts"]:
                if account.lower() in cases[case]['account'].lower():
                    assignee = member
        if assignee == None:
            assignee = get_random_member(cfg['team'])
        assignee['displayName'] = assignee['name']
        priority = portal2jira_sevs[cases[case]['severity']]
        card_info = {
            'project': {'key': cfg['project']},
            'issuetype': {'name': cfg['type']},
            'components': [{'name': cfg['component']}],
            'priority': {'name': priority},
            'labels': cfg['labels'],
            'assignee': {'name': assignee['jira_user']},
            'customfield_12310243': float(cfg['points']),
            'summary': case + ': ' + cases[case]['problem'],
            'description': 'This card was automatically created from the Field Engineering Sync Job.\r\n\r\n'
            + 'This card was created because it had a severity of '
            + cases[case]['severity']
            + '\r\n'
            + 'The account for the case is '
            + cases[case]['account']
            + '\r\n'
            + 'The case had an internal status of: '
            + cases[case]['status']
            + '\r\n\r\n'
            + '*Description:* \r\n\r\n'
            + cases[case]['description']
            + '\r\n'
            }

        logging.warning('A card needs created for case {}'.format(case))
        logging.warning(card_info)
        
        if action == 'create':
            logging.warning('creating card for case {}'.format(case))
            new_card = jira_conn.create_issue(fields=card_info)
            logging.warning('created {}'.format(new_card.key))
            email_content.append( f"A JIRA issue (https://issues.redhat.com/browse/{new_card}) has been created for a new Telco5G case:\nCase #: {case} (https://access.redhat.com/support/cases/{case})\nAccount: {cases[case]['account']}\nSummary: {cases[case]['problem']}\nSeverity: {cases[case]['severity']}\nDescription: {cases[case]['description']}\n\nIt is initially being tracked by {assignee['name']}.\n")

            # Add newly create card to the sprint
            logging.warning('moving card to sprint {}'.format(sprint.id))
            jira_conn.add_issues_to_sprint(sprint.id, [new_card.key])

            # Move the card from backlog to the To Do column
            logging.warning('moving card from backlog to "To Do" column')
            jira_conn.transition_issue(new_card.key, 'To Do')

            # Add links to case, etc
            logging.warning('adding link to support case {}'.format(case))
            jira_conn.add_simple_link(new_card.key, { 
                'url': 'https://access.redhat.com/support/cases/' + case, 
                'title': 'Support Case'
                })

            bz = []
            if 'bug' in cases[case]:
                bz = cases[case]['bug']
                logging.warning('adding link to BZ {}'.format(cases[case]['bug']))
                jira_conn.add_simple_link(new_card.key, { 
                    'url': 'https://bugzilla.redhat.com/show_bug.cgi?id=' + cases[case]['bug'],
                    'title': 'BZ ' + cases[case]['bug'] })

            if 'tags' in cases[case].keys():
                tags = cases[case]['tags']
            else:
                tags = ['shift_telco5g'] # trigged by case summary, not tag

            new_cards[new_card.key] = {
                "card_status": new_card.fields.status.name,
                "account": cases[case]['account'],
                "summary": case + ': ' + cases[case]['problem'],
                "description": cases[case]['description'],
                "comments": None,
                "assignee": assignee,
                "case_number": case,
                "tags": tags,
                "labels": cfg['labels'],
                "bugzilla": bz,
                "severity": re.search(r'[a-zA-Z]+', cases[case]['severity']).group(),
                "case_status": cases[case]['status']
            }
    
    return email_content, new_cards

def notify(ini,blist):
    
    body = ''
    for line in blist:
        body += f"{line}\n"

    msg = EmailMessage()
    msg.set_content(body)

    msg['Subject'] = ini['subject']
    msg['From'] = ini['from']
    msg['to'] = ini['to']

    s = smtplib.SMTP(ini['smtp'])
    s.send_message(msg)
    s.quit()

def slack_notify(ini, blist):
    body = ''
    for line in blist:
        body += f"{line}\n"

    client = WebClient(token = ini['slack_token'])
    msgs = re.split(r'A JIRA issue \(https:\/\/issues\.redhat\.com\/browse\/|Description: ', body)

    #Adding the text removed by re.split() and adding ping to assignee 
    for i in range(1, len(msgs)):
        if i % 2 == 1:
            msgs[i] = "A JIRA issue (https://issues.redhat.com/browse/" + msgs[i]
        if i % 2 == 0:
            msgs[i] = "Description: " + msgs[i]
            assign = re.findall(r'(?<=\nIt is initially being tracked by )[\w ]*', msgs[i])
            for j in ini['team']:
                if j['name'] == assign[0]:
                    userid = j['slack_user']
            msgs[i] = re.sub(r'\nIt is initially being tracked by.*', '', msgs[i])
            msgs[i-1] = msgs[i-1] + f"\nIt is initially being tracked by <@{userid}>"

    #Posting Summaries + reply with Description
    for k in range(1, len(msgs)-1, 2):
        message = client.chat_postMessage(channel = ini['slack_channel'], text = msgs[k])
        reply = client.chat_postMessage(channel = ini['slack_channel'], text = msgs[k+1], thread_ts = message['ts'])

def set_defaults():
    defaults = {}
    defaults['smtp']        = 'smtp.corp.redhat.com'
    defaults['from']        = 't5g_jira@redhat.com'
    defaults['to']          = ''
    defaults['alert_to']    = 'dcritch@redhat.com'
    defaults['subject']     = 'New Card(s) Have Been Created to Track Telco5G Issues'
    defaults['sprintname']  = 'T5GFE' #Previous Sprintname: 'Labs and Field Sprint' 
    defaults['server']      = 'https://issues.redhat.com'
    defaults['project']     = 'KNIECO'
    defaults['component']   = 'KNI Labs & Field'
    defaults['board']       = 'KNI-ECO Labs & Field'
    defaults['email']       = ''
    defaults['type']        = 'Story'
    defaults['labels']      = 'field, no-qe, no-doc'
    defaults['priority']    = 'High'
    defaults['points']      = 3
    defaults['password']    = ''
    defaults['card_action'] = 'none'
    defaults['debug']       = 'False'
    defaults['fields']      =  ["case_account_name","case_summary","case_number","case_status","case_owner","case_severity","case_createdDate","case_lastModifiedDate","case_bugzillaNumber","case_description","case_tags", "case_product", "case_version", "case_closedDate"]
    defaults['query']       = "case_summary:*webscale* OR case_tags:*shift_telco5g* OR case_tags:*cnv*"
    defaults['slack_token']   = ''
    defaults['slack_channel'] = ''
    defaults['max_jira_results'] = 500
    defaults['max_portal_results'] = 5000
    return defaults

def read_config(file):
    '''
    Takes a filename as input and reads the values into a dictionary.
    file should be in the format of "key: value" pairs. no value will
    simply set the key in the dictionary.
    e.g.
        debug
        email : me@redhat.com, you@redhat.com
        email: me@redhat.com, you@redhat.com
        email:me@redhat.com, you@redhat.com
    '''

    cfg_dict = {}
    with open(file) as filep:
        for line in filep:
            if not line.startswith("#") and not line.startswith(";"):
                a = line.split(':', 1)
                key = a[0].replace('\n', '').strip()

                if len(a) > 1:
                    value = a[1].replace('\n', '').strip()
                    cfg_dict[key] = value
                elif len(key) > 0:
                    cfg_dict[key] = True
    return cfg_dict

def read_env_config(keys):
    ecfg = {}

    for key in keys:
        if 't5g_' + key in os.environ:
            ecfg[key] = os.environ.get('t5g_' + key)

    return ecfg

def get_token(offline_token):
  # https://access.redhat.com/articles/3626371
  data = { 'grant_type' : 'refresh_token', 'client_id' : 'rhsm-api', 'refresh_token': offline_token }
  url = 'https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token'
  r = requests.post(url, data=data)
  # It returns 'application/x-www-form-urlencoded'
  token = r.json()['access_token']
  return(token)

def redis_set(key, value):

    logging.warning("syncing {}..".format(key))
    r_cache = redis.Redis(host='redis')
    r_cache.mset({key: value})
    logging.warning("{}....synced".format(key))

def redis_get(key):

    logging.warning("fetching {}..".format(key))
    r_cache = redis.Redis(host='redis')
    data = r_cache.get(key)
    if data is not None:
        data = json.loads(data.decode("utf-8"))
    else:
        data = {}
    logging.warning("{} ....fetched".format(key))

    return data

def cache_cases(cfg):
  # https://source.redhat.com/groups/public/hydra/hydra_integration_platform_cee_integration_wiki/hydras_api_layer

  token = get_token(cfg['offline_token'])
  query = cfg['query']
  fields = ",".join(cfg['fields'])
  query = "({})".format(query)
  num_cases = cfg['max_portal_results']
  payload = {"q": query, "partnerSearch": "false", "rows": num_cases, "fl": fields}
  headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
  url = "https://access.redhat.com/hydra/rest/search/cases"

  logging.warning("searching the portal for cases")
  start = time.time()
  r = requests.get(url, headers=headers, params=payload)
  cases_json = r.json()['response']['docs']
  end = time.time()
  logging.warning("found {} cases in {} seconds".format(len(cases_json), (end-start)))
  cases = {}
  for case in cases_json:
    cases[case["case_number"]] = {
        "owner": case["case_owner"],
        "severity": case["case_severity"],
        "account": case["case_account_name"],
        "problem": case["case_summary"],
        "status": case["case_status"],
        "createdate": case["case_createdDate"],
        "last_update": case["case_lastModifiedDate"],
        "description": case["case_description"],
        "product": case["case_product"][0] + " " + case["case_version"]
    }
    # Sometimes there is no BZ attached to the case
    if "case_bugzillaNumber" in case:
        cases[case["case_number"]]["bug"] = case["case_bugzillaNumber"]
    # Sometimes there is no tag attached to the case
    if "case_tags" in case:
        cases[case["case_number"]]["tags"] = case["case_tags"]
    else: # assume. came from query, so probably telco
        cases[case["case_number"]]["tags"] = ['shift_telco5g']
    # Sometimes there is no closed date attached to the case
    if "case_closedDate" in case:
        cases[case["case_number"]]["closeddate"] = case["case_closedDate"]

  redis_set('cases', json.dumps(cases))

def cache_bz(cfg):
    
    cases = redis_get('cases')
    if cases is None:
        redis_set('bugs', json.dumps(None))
        return
    
    bz_url = "bugzilla.redhat.com"
    bz_api = bugzilla.Bugzilla(bz_url, api_key=cfg['bz_key'])
    bz_dict = {}
    token = get_token(cfg['offline_token'])
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}

    logging.warning("getting all bugzillas")
    for case in cases:
        if "bug" in cases[case] and cases[case]['status'] != "Closed":
            bz_endpoint = "https://access.redhat.com/hydra/rest/v1/cases/" + case
            r_bz = requests.get(bz_endpoint, headers=headers)
            bz_dict[case] = r_bz.json()['bugzillas']

    logging.warning("getting additional info via bugzilla API")
    for case in bz_dict:
        for bug in bz_dict[case]:
            bugs = bz_api.getbug(bug['bugzillaNumber'])
            bug['target_release'] = bugs.target_release
            bug['assignee'] = bugs.assigned_to
            bug['last_change_time'] = datetime.datetime.strftime(datetime.datetime.strptime(str(bugs.last_change_time), '%Y%m%dT%H:%M:%S'), '%Y-%m-%d') # convert from xmlrpc.client.DateTime to str and reformat
            bug['internal_whiteboard'] = bugs.internal_whiteboard
    redis_set('bugs', json.dumps(bz_dict))

def cache_escalations(cfg):
    '''Get cases that have been escalated from Smartsheet'''
    cases = redis_get('cases')
    if cases is None:
        redis_set('escalations', json.dumps(None))
        return

    logging.warning("getting escalated cases from smartsheet")
    smart = smartsheet.Smartsheet(cfg['smartsheet_access_token'])
    sheet_dict = smart.Sheets.get_sheet(cfg['sheet_id']).to_dict()

    # Get Column ID's
    column_map = {}
    for column in sheet_dict['columns']:
        column_map[column['title']] = column['id']
    no_tracking_col = column_map['No longer tracking']
    no_escalation_col = column_map['No longer an escalation']
    case_col = column_map['Case']

    # Get Escalated Cases
    escalations = []
    for row in sheet_dict['rows']:
        for cell in row['cells']:
            if cell['columnId'] == no_tracking_col and 'value' in cell:
                break
            if cell['columnId'] == no_escalation_col and 'value' in cell:
                break
            if cell['columnId'] == case_col and 'value' in cell and cell['value'][:8] not in cases.keys():
                break
            elif cell['columnId'] == case_col and 'value' in cell and cell['value'][:8] in cases.keys():
                escalations.append(cell['value'][:8])

    redis_set('escalations', json.dumps(escalations))

def cache_cards(cfg):

    cases = redis_get('cases')
    bugs = redis_get('bugs')
    escalations = redis_get('escalations')
    logging.warning("attempting to connect to jira...")
    jira_conn = jira_connection(cfg)
    max_cards = cfg['max_jira_results']
    start = time.time()
    project = get_project_id(jira_conn, cfg['project'])
    logging.warning("project: {}".format(project))
    component = get_component_id(jira_conn, project.id, cfg['component'])
    logging.warning("component: {}".format(component))
    board = get_board_id(jira_conn, cfg['board'])
    logging.warning("board: {}".format(board))
    sprint = get_latest_sprint(jira_conn, board.id, cfg['sprintname'])
    logging.warning("sprint: {}".format(sprint))

    logging.warning("pulling cards from jira")

    jira_query = 'sprint=' + str(sprint.id) + ' AND (labels = "field" OR labels = "cnv")'
    card_list = jira_conn.search_issues(jira_query, 0, max_cards).iterable

    jira_cards = {}
    for card in card_list:
        issue = jira_conn.issue(card)
        comments = jira_conn.comments(issue)
        card_comments = []
        for comment in comments:
            body = comment.body
            body = re.sub(r'(?<!\||\s)\s*?((http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])?)',"<a href=\""+r'\g<0>'+"\" target='_blank'>"+r'\g<0>'"</a>", body)
            body = re.sub(r'\[([\s\w!"#$%&\'()*+,-.\/:;<=>?@[^_`{|}~]*?\s*?)\|\s*?((http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])?[\s]*)\]',"<a href=\""+r'\2'+"\" target='_blank'>"+r'\1'+"</a>", body)
            tstamp = comment.updated
            card_comments.append((body, tstamp))
        case_number = get_case_from_link(jira_conn, card)
        if not case_number or case_number not in cases.keys():
            logging.warning("card isn't associated with a case. discarding ({})".format(card))
            continue
        assignee = {
            "displayName": issue.fields.assignee.displayName,
            "key": issue.fields.assignee.key,
            "name": issue.fields.assignee.name
        }
        tags = []
        if 'tags' in cases[case_number].keys():
            tags = cases[case_number]['tags']
        else: # assume telco
            tags = ['shift_telco5g']
        if 'bug' in cases[case_number].keys() and case_number in bugs.keys():
            bugzilla = bugs[case_number]
        else:
            bugzilla = "None"

        if case_number in escalations:
            escalated = True
        else:
            escalated = False
        jira_cards[card.key] = {
            "card_status": issue.fields.status.name,
            "account": cases[case_number]['account'],
            "summary": cases[case_number]['problem'],
            "description": cases[case_number]['description'],
            "comments": card_comments,
            "assignee": assignee,
            "case_number": case_number,
            "tags": tags,
            "labels": issue.fields.labels,
            "bugzilla": bugzilla,
            "severity": re.search(r'[a-zA-Z]+', cases[case_number]['severity']).group(),
            "escalated": escalated,
            "product": cases[case_number]['product'],
            "case_status": cases[case_number]['status']
        }

    end = time.time()
    logging.warning("got {} cards in {} seconds".format(len(jira_cards), (end - start)))
    redis_set('cards', json.dumps(jira_cards))
    redis_set('timestamp', json.dumps(str(datetime.datetime.utcnow())))

def get_case_from_link(jira_conn, card):

    links = jira_conn.remote_links(card)
    for link in links:
        t = jira_conn.remote_link(card, link)
        if t.raw['object']['title'] == "Support Case":
            case_number = get_case_number(t.raw['object']['url'])
            if len(case_number) > 0:
                return case_number
    return None

def generate_stats(case_type):
    ''' generate some stats '''
    
    logging.warning("generating stats for {}".format(case_type))
    start = time.time()
    
    all_cards = redis_get('cards')
    if case_type == 'telco5g':
        cards = {c:d for (c,d) in all_cards.items() if 'field' in d['labels']}
    elif case_type == 'cnv':
        cards = {c:d for (c,d) in all_cards.items() if 'cnv' in d['labels']}
    else:
        logging.warning("unknown case type: {}".format(case_type))
        return {}
    
    all_cases = redis_get('cases')
    if case_type == 'telco5g':
        cases = {c:d for (c,d) in all_cases.items() if 'shift_telco5g' in d['tags']}
    elif case_type == 'cnv':
        cases = {c:d for (c,d) in all_cases.items() if 'cnv' in d['tags']}
    else:
        logging.warning("unknown case type: {}".format(case_type))
        return {}
    
    bugs = redis_get('bugs')

    today = datetime.date.today()
    
    customers = [cards[card]['account'] for card in cards]
    engineers = [cards[card]['assignee']['displayName'] for card in cards]
    severities = [cards[card]['severity'] for card in cards]
    statuses = [cards[card]['case_status'] for card in cards]
        
    stats = {
        'by_customer': {c:0 for c in customers},
        'by_engineer': {e:0 for e in engineers},
        'by_severity': {s:0 for s in severities},
        'by_status': {s:0 for s in statuses},
        'escalated': 0,
        'open_cases': 0,
        'weekly_closed_cases': 0,
        'weekly_opened_cases': 0,
        'daily_closed_cases': 0,
        'daily_opened_cases': 0,
        'no_updates': 0,
        'no_bzs': 0,
        'bugs': {
            'unique': 0,
            'no_target': 0
        }
    }

    for card in cards:
        account = cards[card]['account']
        engineer = cards[card]['assignee']['displayName']
        severity = cards[card]['severity']
        status = cards[card]['case_status']
    
        stats['by_customer'][account] += 1
        stats['by_engineer'][engineer] += 1
        stats['by_severity'][severity] += 1
        stats['by_status'][status] += 1
            
        if cards[card]['escalated']:
            stats['escalated'] += 1
        if cards[card]['bugzilla'] == "None":
            stats['no_bzs'] += 1
        
        if cards[card]['comments'] is not None:
            comments = [comment for comment in cards[card]['comments'] if (today - datetime.datetime.strptime(comment[1], '%Y-%m-%dT%H:%M:%S.%f%z').date()).days > 7]
            if len(comments) == 0:
                stats['no_updates'] += 1
        else:
            stats['no_updates'] += 1

    open_cases = {c: d for (c, d) in cases.items() if d['status'] != 'Closed'}
    weekly_closed_cases = {c: d for (c, d) in cases.items() if d['status'] == 'Closed' and
    (today - datetime.datetime.strptime(d['closeddate'], '%Y-%m-%dT%H:%M:%SZ').date()).days < 7}
    weekly_opened_cases = {c: d for (c, d) in cases.items() if d['status'] != 'Closed' and
    (today - datetime.datetime.strptime(d['createdate'], '%Y-%m-%dT%H:%M:%SZ').date()).days < 7}
    daily_closed_cases = {c: d for (c, d) in cases.items() if d['status'] == 'Closed' and
    (today - datetime.datetime.strptime(d['closeddate'], '%Y-%m-%dT%H:%M:%SZ').date()).days < 1}
    daily_opened_cases = {c: d for (c, d) in cases.items() if d['status'] != 'Closed' and
    (today - datetime.datetime.strptime(d['createdate'], '%Y-%m-%dT%H:%M:%SZ').date()).days < 1}
    
    stats['open_cases'] = len(open_cases)
    stats['weekly_closed_cases'] = len(weekly_closed_cases)
    stats['weekly_opened_cases'] = len(weekly_opened_cases)
    stats['daily_closed_cases'] = len(daily_closed_cases)
    stats['daily_opened_cases'] = len(daily_opened_cases)

    all_bugs = {}
    for case in bugs:
        for case_bug in bugs[case]:
            all_bugs[case_bug['bugzillaNumber']] = case_bug
    
    no_target = {b: d for (b, d) in all_bugs.items() if d['target_release'][0] == '---'}

    stats['bugs']['unique'] = len(all_bugs)
    stats['bugs']['no_target'] = len(no_target)
    

    end = time.time()
    logging.warning("generated stats in {} seconds".format((end-start)))

    return stats

def main():
    print("libtelco5g")

if __name__ == '__main__':
    main()
