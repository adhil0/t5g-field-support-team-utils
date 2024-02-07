import pytest
import t5gweb.libtelco5g as libtelco5g


def test_get_jira_connection(mocker):
    cfg = {"server": "http://example.com", "password": "your_token"}
    mock_jira = mocker.patch("t5gweb.libtelco5g.JIRA")

    result = libtelco5g.jira_connection(cfg)

    mock_jira.assert_called_once_with(server=cfg["server"], token_auth=cfg["password"])
    assert result == mock_jira.return_value


@pytest.fixture
def mock_redis(mocker):
    return mocker.patch("t5gweb.libtelco5g.redis.Redis")


@pytest.fixture
def mock_redis_get(mocker):
    return mocker.patch("t5gweb.libtelco5g.redis_get")


def test_redis_set(mock_redis):
    key = "test_key"
    value = "test_value"
    libtelco5g.redis_set(key, value)

    mock_redis.assert_called_once_with(host="redis")
    mock_redis.return_value.mset.assert_called_once_with({key: value})


@pytest.mark.parametrize(
    "key,value,expected_result",
    [("test_key", b'{"foo": "bar"}', {"foo": "bar"}), ("test_none", None, {})],
)
def test_redis_get(mock_redis, key, value, expected_result):
    mock_redis.return_value.get.return_value = value

    result = libtelco5g.redis_get(key)

    mock_redis.assert_called_once_with(host="redis")
    mock_redis.return_value.get.assert_called_once_with(key)
    assert result == expected_result


@pytest.mark.parametrize(
    "input_data, expected_summary",
    [
        (
            {},
            {
                "backlog": 0,
                "debugging": 0,
                "eng_working": 0,
                "backport": 0,
                "ready_to_close": 0,
                "done": 0,
            },
        ),
        (
            {
                "card1": {"card_status": "Backlog"},
                "card2": {"card_status": "Debugging"},
                "card3": {"card_status": "Eng Working"},
                "card4": {"card_status": "Backport"},
                "card5": {"card_status": "Ready To Close"},
                "card6": {"card_status": "Done"},
            },
            {
                "backlog": 1,
                "debugging": 1,
                "eng_working": 1,
                "backport": 1,
                "ready_to_close": 1,
                "done": 1,
            },
        ),
        (
            {
                "card1": {"card_status": "Backlog"},
                "card2": {"card_status": "Backlog"},
                "card4": {"card_status": "Eng Working"},
                "card5": {"card_status": "Eng Working"},
                "card6": {"card_status": "Eng Working"},
                "card7": {"card_status": "Backport"},
                "card8": {"card_status": "Backport"},
                "card9": {"card_status": "Backport"},
                "card10": {"card_status": "Ready To Close"},
            },
            {
                "backlog": 2,
                "debugging": 0,
                "eng_working": 3,
                "backport": 3,
                "ready_to_close": 1,
                "done": 0,
            },
        ),
    ],
)
def test_get_card_summary(mock_redis_get, input_data, expected_summary):
    mock_redis_get.return_value = input_data

    result = libtelco5g.get_card_summary()

    assert result == expected_summary


@pytest.mark.parametrize(
    "link, pfilter, expected_case_number",
    [
        ("https://access.redhat.com/support/cases/0123456", "cases", "0123456"),
        ("https://access.redhat.com/support/cases/#/case/0123456", "cases", "0123456"),
        ("https://example.com/support/cases/0123456", "cases", ""),
        ("https://access.redhat.com/support/cases/0123456", "invalid_filter", ""),
        ("", "cases", ""),
    ],
)
def test_get_case_number(link, pfilter, expected_case_number):
    result = libtelco5g.get_case_number(link, pfilter)
    assert result == expected_case_number


@pytest.mark.parametrize(
    "item,expected_result",
    [
        ({"target_release": ["---"]}, True),
        ({"target_release": ["4.14"]}, False),
        ({"fix_versions": ["4.14"]}, False),
        ({"fix_versions": ["---"]}, True),
        ({"fix_versions": None}, True),
        ({"nothing": ["4.14"]}, True),
    ],
)
def test_is_bug_missing_target(item, expected_result):
    result = libtelco5g.is_bug_missing_target(item)
    assert result == expected_result


@pytest.mark.parametrize(
    "input_data, expected_result",
    [
        (
            {},
            (
                [],
                {
                    "escalated": [],
                    "watched": [],
                    "open_cases": [],
                    "new_cases": [],
                    "closed_cases": [],
                    "no_updates": [],
                    "no_bzs": [],
                    "bugs_unique": [],
                    "bugs_no_tgt": [],
                    "high_prio": [],
                    "crit_sit": [],
                    "total_escalations": [],
                },
            ),
        ),
        (
            {
                "2022-01-01": {
                    "escalated": 10,
                    "watched": 5,
                    "open_cases": 20,
                    "daily_opened_cases": 5,
                    "daily_closed_cases": 3,
                    "no_updates": 2,
                    "no_bzs": 1,
                    "bugs": {"unique": 7, "no_target": 2},
                    "high_prio": 8,
                    "crit_sit": 3,
                    "total_escalations": 15,
                },
                "2022-01-02": {
                    "escalated": 15,
                    "watched": 7,
                    "open_cases": 18,
                    "daily_opened_cases": 6,
                    "daily_closed_cases": 4,
                    "no_updates": 1,
                    "no_bzs": 0,
                    "bugs": {"unique": 8, "no_target": 1},
                    "high_prio": 6,
                    "crit_sit": 2,
                    "total_escalations": 18,
                },
            },
            (
                ["2022-01-01", "2022-01-02"],
                {
                    "escalated": [10, 15],
                    "watched": [5, 7],
                    "open_cases": [20, 18],
                    "new_cases": [5, 6],
                    "closed_cases": [3, 4],
                    "no_updates": [2, 1],
                    "no_bzs": [1, 0],
                    "bugs_unique": [7, 8],
                    "bugs_no_tgt": [2, 1],
                    "high_prio": [8, 6],
                    "crit_sit": [3, 2],
                    "total_escalations": [15, 18],
                },
            ),
        ),
        (
            {
                "2022-01-01": {
                    "bugs": {"unique": 8},
                },
            },
            (
                ["2022-01-01"],
                {
                    "escalated": [0],
                    "watched": [0],
                    "open_cases": [0],
                    "new_cases": [0],
                    "closed_cases": [0],
                    "no_updates": [0],
                    "no_bzs": [0],
                    "bugs_unique": [8],
                    "bugs_no_tgt": [0],
                    "high_prio": [0],
                    "crit_sit": [0],
                    "total_escalations": [0],
                },
            ),
        ),
    ],
)
def test_plot_stats(mock_redis_get, input_data, expected_result):
    mock_redis_get.return_value = input_data

    stats = libtelco5g.plot_stats()

    assert stats == expected_result