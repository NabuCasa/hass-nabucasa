"""Tests for hass_nabucaa utils."""

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
