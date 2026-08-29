"""Tests for hass_nabucasa utils."""

import asyncio
from unittest.mock import MagicMock, patch

from icmplib import Host, ICMPLibError, SocketPermissionError
import jwt
import pytest
from syrupy import SnapshotAssertion

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


async def test_async_check_latency_no_addresses():
    """Test async_check_latency with empty address list raises CheckLatencyError."""
    with pytest.raises(utils.CheckLatencyError, match="No addresses provided"):
        await utils.async_check_latency([])


async def test_async_check_latency_with_ip(snapshot: SnapshotAssertion):
    """Test async_check_latency with an IP address."""
    mock_host = MagicMock(
        address="999.999.999.999",
        is_alive=True,
        avg_rtt=10.5,
        max_rtt=15.0,
        min_rtt=5.0,
        spec=Host,
    )

    with patch(
        "hass_nabucasa.utils.async_multiping",
        return_value=[mock_host],
    ):
        result = await utils.async_check_latency(["999.999.999.999"])

    assert result == snapshot


async def test_async_check_latency_multiple_addresses(snapshot: SnapshotAssertion):
    """Test async_check_latency with multiple addresses sorted by latency."""
    mock_host1 = MagicMock(
        address="1.1.1.1",
        is_alive=True,
        avg_rtt=20.0,
        max_rtt=25.0,
        min_rtt=15.0,
        spec=Host,
    )
    mock_host2 = MagicMock(
        address="999.999.999.999",
        is_alive=True,
        avg_rtt=10.0,
        max_rtt=15.0,
        min_rtt=5.0,
        spec=Host,
    )
    mock_host3 = MagicMock(
        address="9.9.9.9",
        is_alive=True,
        avg_rtt=15.0,
        max_rtt=20.0,
        min_rtt=10.0,
        spec=Host,
    )

    with patch(
        "hass_nabucasa.utils.async_multiping",
        return_value=[mock_host1, mock_host2, mock_host3],
    ):
        result = await utils.async_check_latency(
            ["1.1.1.1", "999.999.999.999", "9.9.9.9"]
        )

    # Should be sorted by avg_rtt (fastest first)
    assert sorted(result, key=lambda x: x["avg_rtt"]) == snapshot


async def test_async_check_latency_partial_unreachable(snapshot: SnapshotAssertion):
    """Test async_check_latency when some hosts are unreachable."""
    mock_host1 = MagicMock(
        address="1.1.1.1",
        is_alive=True,
        avg_rtt=20.0,
        max_rtt=25.0,
        min_rtt=15.0,
        spec=Host,
    )
    mock_host2 = MagicMock(
        address="999.999.999.999",
        is_alive=False,
        avg_rtt=0.0,
        max_rtt=0.0,
        min_rtt=0.0,
        spec=Host,
    )
    mock_host3 = MagicMock(
        address="9.9.9.9",
        is_alive=True,
        avg_rtt=15.0,
        max_rtt=20.0,
        min_rtt=10.0,
        spec=Host,
    )

    with patch(
        "hass_nabucasa.utils.async_multiping",
        return_value=[mock_host1, mock_host2, mock_host3],
    ):
        result = await utils.async_check_latency(
            ["1.1.1.1", "999.999.999.999", "9.9.9.9"]
        )

    # Result should match the snapshot when some hosts are unreachable
    assert result == snapshot


async def test_async_check_latency_socket_permission_error_retries():
    """Test async_check_latency.

    retries with privileged=False on SocketPermissionError.
    """
    mock_host = MagicMock(
        address="999.999.999.999",
        is_alive=True,
        avg_rtt=10.5,
        max_rtt=15.0,
        min_rtt=5.0,
        spec=Host,
    )

    with patch(
        "hass_nabucasa.utils.async_multiping",
        side_effect=[SocketPermissionError(privileged=True), [mock_host]],
    ) as mock_multiping:
        result = await utils.async_check_latency(["999.999.999.999"])

    assert mock_multiping.call_count == 2
    assert mock_multiping.call_args_list[0][1]["privileged"] is True
    assert mock_multiping.call_args_list[1][1]["privileged"] is False
    assert len(result) == 1
    assert result[0]["address"] == "999.999.999.999"


async def test_async_check_latency_socket_permission_error_unprivileged():
    """Test async_check_latency.

    raises CheckLatencyInsufficientPrivileges when privileged=False.
    """
    with (
        patch(
            "hass_nabucasa.utils.async_multiping",
            side_effect=SocketPermissionError(privileged=True),
        ),
        pytest.raises(utils.CheckLatencyInsufficientPrivileges),
    ):
        await utils.async_check_latency(["999.999.999.999"], privileged=False)


async def test_async_check_latency_socket_permission_error_retry_also_fails():
    """Test async_check_latency.

    raises CheckLatencyInsufficientPrivileges when retry also fails.
    """
    with (
        patch(
            "hass_nabucasa.utils.async_multiping",
            side_effect=SocketPermissionError(privileged=True),
        ),
        pytest.raises(utils.CheckLatencyInsufficientPrivileges),
    ):
        await utils.async_check_latency(["999.999.999.999"])


async def test_async_check_latency_icmp_error():
    """Test async_check_latency when ICMP ping fails raises CheckLatencyError."""
    with (
        patch(
            "hass_nabucasa.utils.async_multiping",
            side_effect=ICMPLibError("ICMP error"),
        ),
        pytest.raises(utils.CheckLatencyError, match="ICMP ping failed"),
    ):
        await utils.async_check_latency(["999.999.999.999"])


async def test_async_check_latency_all_unreachable():
    """Test async_check_latency when all hosts are unreachable."""
    mocked_results = [
        MagicMock(
            address="999.999.999.999",
            is_alive=False,
            avg_rtt=0.0,
            max_rtt=0.0,
            min_rtt=0.0,
            spec=Host,
        ),
        MagicMock(
            address="1.1.1.1",
            is_alive=False,
            avg_rtt=0.0,
            max_rtt=0.0,
            min_rtt=0.0,
            spec=Host,
        ),
    ]

    with (
        patch(
            "hass_nabucasa.utils.async_multiping",
            return_value=mocked_results,
        ),
    ):
        result = await utils.async_check_latency(["1.1.1.1", "999.999.999.999"])

    assert len(result) == 2
    assert not any(host["is_alive"] for host in result)


async def test_wait_for_event():
    """Test wait_for_event returns True and clears a set event, else times out."""
    event = asyncio.Event()
    event.set()

    assert await utils.wait_for_event(event, 3600) is True
    assert not event.is_set()

    assert await utils.wait_for_event(event, 0) is False


def test_backoff_interval_grows_until_maximum() -> None:
    """Test that the interval grows until it hits the maximum."""
    backoff = utils.Backoff(initial=1, maximum=8, multiplier=2, jitter_fraction=0)

    assert [backoff.next_interval() for _ in range(6)] == [1, 2, 4, 8, 8, 8]
    assert backoff.attempts == 6
    assert backoff.elapsed == 31


def test_backoff_multiplier() -> None:
    """Test that the multiplier controls the growth."""
    fixed = utils.Backoff(initial=10, maximum=100, multiplier=1, jitter_fraction=0)
    assert [fixed.next_interval() for _ in range(2)] == [10, 10]

    tripled = utils.Backoff(initial=10, maximum=1000, multiplier=3, jitter_fraction=0)
    assert [tripled.next_interval() for _ in range(3)] == [10, 30, 90]


def test_backoff_default_multiplier() -> None:
    """Test the growth of a backoff that does not pick a multiplier."""
    backoff = utils.Backoff(initial=100, maximum=1000, jitter_fraction=0)

    assert [backoff.next_interval() for _ in range(3)] == [
        100,
        100 * utils.DEFAULT_BACKOFF_MULTIPLIER,
        100 * utils.DEFAULT_BACKOFF_MULTIPLIER**2,
    ]


def test_backoff_jitter_is_shaved_off_the_interval() -> None:
    """Test that jitter spreads the interval out without passing the maximum."""
    backoff = utils.Backoff(initial=10, maximum=10, jitter_fraction=0.5)

    intervals = [backoff.next_interval() for _ in range(20)]

    assert all(5 <= interval <= 10 for interval in intervals)
    assert len(set(intervals)) > 1


def test_backoff_never_passes_the_maximum() -> None:
    """Test that the maximum holds once the growth has settled there."""
    backoff = utils.Backoff(initial=1, maximum=10, jitter_fraction=1)

    assert all(backoff.next_interval() <= 10 for _ in range(50))


def test_backoff_default_jitter_is_applied() -> None:
    """Test that jitter is enabled by default."""
    with patch("hass_nabucasa.utils.jitter", return_value=1.0) as jitter_mock:
        assert utils.Backoff(initial=10, maximum=10).next_interval() == 9.0

    assert jitter_mock.call_args[0] == (0, 10 * utils.DEFAULT_BACKOFF_JITTER)


def test_backoff_retries_forever() -> None:
    """Test that a backoff keeps handing out intervals."""
    backoff = utils.Backoff(initial=1, maximum=2, multiplier=2, jitter_fraction=0)

    assert all(backoff.next_interval() for _ in range(100_000))
    assert backoff.elapsed == 199_999


def test_backoff_reset() -> None:
    """Test that a reset starts over from the initial interval."""
    backoff = utils.Backoff(initial=10, maximum=100, multiplier=2, jitter_fraction=0)

    assert [backoff.next_interval() for _ in range(3)] == [10, 20, 40]

    backoff.reset()

    assert backoff.attempts == 0
    assert backoff.elapsed == 0
    assert backoff.next_interval() == 10


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"initial": 0, "maximum": 10}, "initial must be greater than 0"),
        ({"initial": -1, "maximum": 10}, "initial must be greater than 0"),
        ({"initial": 10, "maximum": 9}, "maximum must not be smaller than initial"),
        (
            {"initial": 1, "maximum": 10, "multiplier": 0.5},
            "multiplier must not be smaller than 1",
        ),
        (
            {"initial": 1, "maximum": 10, "jitter_fraction": 1.5},
            "jitter_fraction must be between 0 and 1",
        ),
        (
            {"initial": 1, "maximum": 10, "jitter_fraction": -0.1},
            "jitter_fraction must be between 0 and 1",
        ),
    ],
)
def test_backoff_invalid_options(options: dict[str, float], message: str) -> None:
    """Test that invalid options are rejected."""
    with pytest.raises(ValueError, match=message):
        utils.Backoff(**options)
