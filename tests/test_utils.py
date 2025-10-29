"""Tests for hass_nabucaa utils."""

import jwt
import pytest

from hass_nabucasa import utils


@pytest.mark.parametrize(
    "input_str",
    [
        "2020-02-30",
        "2019-02-29",
        "2021-04-31",
        "2023-06-31",
        "2018-09-31",
        "2015-11-31",
        "2022-02-30",
        "2020-04-31",
        "2021-06-31",
        "2017-09-31",
        "2019-04-31",
        "2023-11-31",
        "2020-06-31",
        "2016-02-30",
        "2021-11-31",
        "invalid",
        "2023/12/12",
    ],
)
def test_parse_date_with_invalid_dates(input_str):
    """Test the parse_date util."""
    assert utils.parse_date(input_str) is None


@pytest.mark.parametrize(
    "input_str",
    [
        "2020-02-29",
        "2019-03-15",
        "2021-04-30",
        "2023-06-15",
        "2018-09-30",
        "2015-12-25",
        "2022-02-28",
        "2020-07-04",
        "2021-08-21",
        "2017-10-31",
        "2019-01-01",
        "2023-11-30",
        "2020-05-05",
        "2016-12-12",
        "2021-03-14",
    ],
)
def test_parse_date_with_valid_dates(input_str):
    """Test the parse_date util."""
    assert utils.parse_date(input_str) is not None


def test_expiration_from_token():
    """Test the expiration_from_token util."""
    encoded = jwt.encode(
        {
            "exp": 1234567890,
            "iat": 1234567890,
            "sub": "user_id",
        },
        "secret",
        algorithm="HS256",
    )
    assert utils.expiration_from_token(encoded) == 1234567890


def test_expiration_from_token_no_exp():
    """Test the expiration_from_token util with no exp claim."""
    encoded = jwt.encode(
        {
            "iat": 1234567890,
            "sub": "user_id",
        },
        "secret",
        algorithm="HS256",
    )
    assert utils.expiration_from_token(encoded) is None


def test_expiration_from_token_no_token():
    """Test the expiration_from_token util with no token."""
    assert utils.expiration_from_token(None) is None


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0s"),
        (30, "30s"),
        (59, "59s"),
        (60, "1m"),
        (90, "1m:30s"),
        (125, "2m:5s"),
        (3600, "1h"),
        (3661, "1h:1m:1s"),
        (3725, "1h:2m:5s"),
        (7384, "2h:3m:4s"),
        (43289, "12h:1m:29s"),
        (86400, "1d"),
        (86400.44, "1d"),
        (86401, "1d:0h:0m:1s"),
        (86460, "1d:0h:1m"),
        (86461, "1d:0h:1m:1s"),
        (90061, "1d:1h:1m:1s"),
        (93784, "1d:2h:3m:4s"),
        (172925, "2d:0h:2m:5s"),
        (266543, "3d:2h:2m:23s"),
    ],
)
def test_seconds_as_dhms(seconds, expected):
    """Test the seconds_as_dhms util."""
    assert utils.seconds_as_dhms(seconds) == expected
