"""Test remote sni handler."""
from unittest.mock import patch, MagicMock, Mock

import pytest

from hass_nabucasa.remote import RemoteUI

from .common import mock_coro, MockAcme, MockSnitun


@pytest.fixture(autouse=True)
def ignore_context():
    """Ignore ssl context."""
    with patch(
        "hass_nabucasa.remote.RemoteUI._create_context", return_value=mock_coro()
    ) as context:
        yield context


@pytest.fixture
async def acme_mock():
    """Mock ACME client."""
    with patch("hass_nabucasa.remote.AcmeHandler", new_callable=MockAcme) as acme:
        yield acme


@pytest.fixture
async def snitun_mock():
    """Mock ACME client."""
    with patch("hass_nabucasa.remote.SniTunClientAioHttp", MockSnitun()) as snitun:
        yield snitun


def test_init_remote(cloud_mock):
    """Init remote object."""
    remote = RemoteUI(cloud_mock)

    assert len(cloud_mock.iot.mock_calls) == 2


async def test_load_backend_exists_cert(
    cloud_mock, acme_mock, mock_cognito, aioclient_mock, snitun_mock
):
    """Initialize backend."""
    cloud_mock.remote_api_url = "https://test.local/api"
    remote = RemoteUI(cloud_mock)

    aioclient_mock.post(
        "https://test.local/api/register_instance",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )

    await remote.load_backend()

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert not acme_mock.call_issue
    assert acme_mock.init_args == (
        cloud_mock,
        "test.dui.nabu.casa",
        "test@nabucasa.inc",
    )
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (None, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }


async def test_load_backend_not_exists_cert(
    cloud_mock, acme_mock, mock_cognito, aioclient_mock, snitun_mock
):
    """Initialize backend."""
    cloud_mock.remote_api_url = "https://test.local/api"
    remote = RemoteUI(cloud_mock)

    aioclient_mock.post(
        "https://test.local/api/register_instance",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )

    acme_mock.set_false()
    await remote.load_backend()

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert acme_mock.call_issue
    assert acme_mock.init_args == (
        cloud_mock,
        "test.dui.nabu.casa",
        "test@nabucasa.inc",
    )
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (None, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }


async def test_load_backend_exists_cert(
    cloud_mock, acme_mock, mock_cognito, aioclient_mock, snitun_mock
):
    """Initialize backend."""
    cloud_mock.remote_api_url = "https://test.local/api"
    remote = RemoteUI(cloud_mock)

    aioclient_mock.post(
        "https://test.local/api/register_instance",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )

    await remote.load_backend()

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert not acme_mock.call_issue
    assert acme_mock.init_args == (
        cloud_mock,
        "test.dui.nabu.casa",
        "test@nabucasa.inc",
    )
    assert snitun_mock.call_start
    assert not snitun_mock.call_stop
    assert snitun_mock.init_args == (None, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    await remote.close_backend()

    assert snitun_mock.call_stop
