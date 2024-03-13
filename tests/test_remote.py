"""Test remote sni handler."""

import asyncio
from datetime import timedelta
from ssl import SSLError
from unittest.mock import patch

from acme import client, messages
import pytest

from hass_nabucasa import utils
from hass_nabucasa.acme import AcmeHandler
from hass_nabucasa.const import (
    DISPATCH_REMOTE_BACKEND_DOWN,
    DISPATCH_REMOTE_BACKEND_UP,
    DISPATCH_REMOTE_CONNECT,
    DISPATCH_REMOTE_DISCONNECT,
)
from hass_nabucasa.remote import (
    RENEW_IF_EXPIRES_DAYS,
    WARN_RENEW_FAILED_DAYS,
    CertificateStatus,
    RemoteUI,
    SubscriptionExpired,
)
from hass_nabucasa.utils import utcnow

from .common import MockAcme, MockSnitun

# pylint: disable=protected-access


@pytest.fixture(autouse=True)
def ignore_context():
    """Ignore ssl context."""
    with patch(
        "hass_nabucasa.remote.RemoteUI._create_context",
        return_value=None,
    ) as context:
        yield context


@pytest.fixture
def acme_mock():
    """Mock ACME client."""
    with patch("hass_nabucasa.remote.AcmeHandler", new_callable=MockAcme) as acme:
        yield acme


@pytest.fixture
def valid_acme_mock(acme_mock):
    """Mock ACME client with valid cert."""
    acme_mock.common_name = "test.dui.nabu.casa"
    acme_mock.alternative_names = ["test.dui.nabu.casa"]
    acme_mock.expire_date = utcnow() + timedelta(days=60)
    return acme_mock


@pytest.fixture
async def snitun_mock():
    """Mock ACME client."""
    with patch("hass_nabucasa.remote.SniTunClientAioHttp", MockSnitun()) as snitun:
        yield snitun


def test_init_remote(auth_cloud_mock):
    """Init remote object."""
    RemoteUI(auth_cloud_mock)

    assert len(auth_cloud_mock.register_on_start.mock_calls) == 1
    assert len(auth_cloud_mock.register_on_stop.mock_calls) == 1


async def test_load_backend_exists_cert(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    assert remote.certificate_status is None

    assert not remote.is_connected
    await remote.start()
    await remote._info_loaded.wait()
    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert remote.instance_domain == "test.dui.nabu.casa"

    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.init_args == (
        auth_cloud_mock,
        ["test.dui.nabu.casa"],
        "test@nabucasa.inc",
    )
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (auth_cloud_mock.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert snitun_mock.start_whitelist is not None
    assert snitun_mock.start_endpoint_connection_error_callback is not None

    await asyncio.sleep(0.1)
    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400
    assert remote.is_connected

    assert remote._acme_task
    assert remote._reconnect_task

    assert auth_cloud_mock.client.mock_dispatcher[0][0] == DISPATCH_REMOTE_BACKEND_UP
    assert auth_cloud_mock.client.mock_dispatcher[1][0] == DISPATCH_REMOTE_CONNECT

    await remote.stop()
    await asyncio.sleep(0.1)

    assert not remote._acme_task
    assert remote.certificate_status == CertificateStatus.READY


async def test_load_backend_not_exists_cert(
    auth_cloud_mock,
    acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    acme_mock.set_false()
    await remote.start()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert acme_mock.call_issue
    assert acme_mock.init_args == (
        auth_cloud_mock,
        ["test.dui.nabu.casa"],
        "test@nabucasa.inc",
    )
    assert acme_mock.call_hardening
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (auth_cloud_mock.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    assert remote._acme_task
    assert remote._reconnect_task

    await remote.stop()
    await asyncio.sleep(0.1)

    assert not remote._acme_task


async def test_load_and_unload_backend(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    await remote.start()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.init_args == (
        auth_cloud_mock,
        ["test.dui.nabu.casa"],
        "test@nabucasa.inc",
    )
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert not snitun_mock.call_stop
    assert snitun_mock.init_args == (auth_cloud_mock.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert remote._acme_task
    assert remote._reconnect_task

    await remote.stop()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_stop

    assert not remote._acme_task
    assert not remote._reconnect_task

    assert auth_cloud_mock.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_BACKEND_DOWN


async def test_load_backend_exists_wrong_cert(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["example.com"],
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    aioclient_mock.post(
        "https://example.com/instance/resolve_dns_cname",
        json=["test.dui.nabu.casa", "_acme-challenge.test.dui.nabu.casa"],
    )

    auth_cloud_mock.accounts_server = "example.com"

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa"]
    await remote.load_backend()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert valid_acme_mock.call_reset
    assert valid_acme_mock.init_args == (
        auth_cloud_mock,
        ["test.dui.nabu.casa", "example.com"],
        "test@nabucasa.inc",
    )
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (auth_cloud_mock.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    await remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


async def test_call_disconnect(
    auth_cloud_mock,
    acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    assert not remote.is_connected
    await remote.load_backend()
    await asyncio.sleep(0.1)
    assert remote.is_connected

    await remote.disconnect()
    assert snitun_mock.call_disconnect
    assert not remote.is_connected
    assert remote._token
    assert auth_cloud_mock.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_DISCONNECT


async def test_load_backend_no_autostart(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    auth_cloud_mock.client.prop_remote_autostart = False
    await remote.load_backend()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start

    assert not snitun_mock.call_connect

    await remote.connect()

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400
    assert auth_cloud_mock.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_CONNECT

    await remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


async def test_get_certificate_details(
    auth_cloud_mock,
    acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    assert remote.certificate is None

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    auth_cloud_mock.client.prop_remote_autostart = False
    await remote.load_backend()
    await asyncio.sleep(0.1)
    assert remote.certificate is None

    acme_mock.common_name = "test"
    acme_mock.alternative_names = ["test"]
    acme_mock.expire_date = valid
    acme_mock.fingerprint = "ffff"

    certificate = remote.certificate
    assert certificate.common_name == "test"
    assert certificate.alternative_names == ["test"]
    assert certificate.expire_date == valid
    assert certificate.fingerprint == "ffff"


async def test_certificate_task_no_backend(
    auth_cloud_mock,
    acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    acme_mock.expire_date = valid

    with (
        patch("hass_nabucasa.utils.next_midnight", return_value=0),
        patch("random.randint", return_value=0),
    ):
        acme_task = remote._acme_task = asyncio.create_task(
            remote._certificate_handler(),
        )
        await asyncio.sleep(0.1)
        assert acme_mock.call_issue
        assert snitun_mock.call_start

        await remote.stop()
        await asyncio.sleep(0.1)

        assert acme_task.done()


async def test_certificate_task_renew_cert(
    auth_cloud_mock,
    acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    acme_mock.expire_date = utcnow() + timedelta(days=-40)

    with (
        patch("hass_nabucasa.utils.next_midnight", return_value=0),
        patch("random.randint", return_value=0),
    ):
        acme_task = remote._acme_task = asyncio.create_task(
            remote._certificate_handler(),
        )

        await remote.load_backend()
        await asyncio.sleep(0.1)
        assert acme_mock.call_issue

        await remote.stop()
        await asyncio.sleep(0.1)

        assert acme_task.done()


async def test_refresh_token_no_sub(auth_cloud_mock):
    """Test that we rais SubscriptionExpired if expired sub."""
    auth_cloud_mock.subscription_expired = True

    with pytest.raises(SubscriptionExpired):
        await RemoteUI(auth_cloud_mock)._refresh_snitun_token()


async def test_load_connect_insecure(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
        status=409,
    )

    auth_cloud_mock.client.prop_remote_autostart = True
    await remote.load_backend()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start

    assert not snitun_mock.call_connect

    assert not snitun_mock.call_connect
    assert auth_cloud_mock.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_BACKEND_UP


async def test_load_connect_forbidden(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
    caplog,
):
    """Initialize backend."""
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "message": "lorem_ipsum",
        },
        status=403,
        headers={"content-type": "application/json; charset=utf-8"},
    )

    auth_cloud_mock.client.prop_remote_autostart = True
    await remote.load_backend()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert not snitun_mock.call_connect

    assert "Remote connection is not allowed lorem_ipsum" in caplog.text


async def test_call_disconnect_clean_token(
    auth_cloud_mock,
    acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    assert not remote.is_connected
    await remote.load_backend()
    await asyncio.sleep(0.1)
    assert remote.is_connected
    assert remote._token

    await remote.disconnect(clear_snitun_token=True)
    assert snitun_mock.call_disconnect
    assert not remote.is_connected
    assert remote._token is None
    assert auth_cloud_mock.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_DISCONNECT


async def test_recreating_old_certificate_with_bad_dns_config(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Test recreating old certificate with bad DNS config for alias."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["example.com"],
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )
    aioclient_mock.post(
        "https://example.com/instance/resolve_dns_cname",
        json=["test.dui.nabu.casa"],
    )

    auth_cloud_mock.accounts_server = "example.com"

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa", "example.com"]
    valid_acme_mock.expire_date = utils.utcnow() + timedelta(
        days=WARN_RENEW_FAILED_DAYS,
    )
    await remote.load_backend()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert valid_acme_mock.call_reset
    assert valid_acme_mock.init_args == (
        auth_cloud_mock,
        ["test.dui.nabu.casa"],
        "test@nabucasa.inc",
    )
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (auth_cloud_mock.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert len(auth_cloud_mock.client.mock_repairs) == 1
    repair = auth_cloud_mock.client.mock_repairs[0]
    assert set(repair.keys()) == {
        "identifier",
        "translation_key",
        "severity",
        "placeholders",
    }

    assert repair["identifier"].startswith("reset_bad_custom_domain_configuration_")
    assert repair["translation_key"] == "reset_bad_custom_domain_configuration"
    assert repair["severity"] == "error"
    assert repair["placeholders"] == {"custom_domains": "example.com"}

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    await remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


async def test_warn_about_bad_dns_config_for_old_certificate(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Test warn about old certificate with bad DNS config for alias."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["example.com"],
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )
    aioclient_mock.post(
        "https://example.com/instance/resolve_dns_cname",
        status=400,
    )

    auth_cloud_mock.accounts_server = "example.com"

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa", "example.com"]
    valid_acme_mock.expire_date = utils.utcnow() + timedelta(days=RENEW_IF_EXPIRES_DAYS)
    await remote.load_backend()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_reset
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (auth_cloud_mock.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert len(auth_cloud_mock.client.mock_repairs) == 1
    repair = auth_cloud_mock.client.mock_repairs[0]
    assert set(repair.keys()) == {
        "identifier",
        "translation_key",
        "severity",
        "placeholders",
    }
    assert repair["identifier"].startswith("warn_bad_custom_domain_configuration_")
    assert repair["translation_key"] == "warn_bad_custom_domain_configuration"
    assert repair["severity"] == "warning"
    assert repair["placeholders"] == {"custom_domains": "example.com"}

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    await remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


async def test_regeneration_without_warning_for_good_dns_config(
    auth_cloud_mock,
    valid_acme_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
):
    """Test no warning for good dns config."""
    valid = utcnow() + timedelta(days=1)
    auth_cloud_mock.servicehandlers_server = "test.local"
    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["example.com"],
        },
    )
    aioclient_mock.post(
        "https://test.local/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )
    aioclient_mock.post(
        "https://example.com/instance/resolve_dns_cname",
        json=["test.dui.nabu.casa", "_acme-challenge.test.dui.nabu.casa"],
    )

    auth_cloud_mock.accounts_server = "example.com"

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa", "example.com"]
    valid_acme_mock.expire_date = utils.utcnow() + timedelta(days=RENEW_IF_EXPIRES_DAYS)
    await remote.load_backend()
    await asyncio.sleep(0.1)

    assert remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_reset
    assert valid_acme_mock.call_issue
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (auth_cloud_mock.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert len(auth_cloud_mock.client.mock_repairs) == 0

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    await remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


@pytest.mark.parametrize(
    ("json_error", "should_reset"),
    (
        (
            {
                "type": "urn:ietf:params:acme:error:malformed",
                "detail": "JWS verification error",
            },
            True,
        ),
        (
            {
                "type": "urn:ietf:params:acme:error:malformed",
                "detail": "Some other malformed reason",
            },
            False,
        ),
        (
            {
                "type": "about:blank",
                "detail": "Boom",
            },
            False,
        ),
    ),
)
async def test_acme_client_new_order_errors(
    auth_cloud_mock,
    mock_cognito,
    aioclient_mock,
    snitun_mock,
    json_error,
    should_reset,
):
    """Initialize backend."""
    auth_cloud_mock.servicehandlers_server = "test.local"

    class _MockAcmeClient(client.ClientV2):
        def __init__(self) -> None:
            pass

        def new_order(self, _):
            raise messages.Error.from_json(json_error)

    class _MockAcme(AcmeHandler):
        call_reset = False
        cloud = auth_cloud_mock

        @property
        def certificate_available(self):
            return True

        @property
        def alternative_names(self):
            return ["test.dui.nabu.casa"]

        def _generate_csr(self):
            return b""

        def _create_client(self):
            self._acme_client = _MockAcmeClient()

        async def reset_acme(self):
            self.call_reset = True

    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )

    with patch(
        "hass_nabucasa.remote.AcmeHandler",
        return_value=_MockAcme(auth_cloud_mock, [], "test@nabucasa.inc"),
    ):
        assert remote._certificate_status is None
        await remote.load_backend()

    await asyncio.sleep(0.1)
    assert remote._acme.call_reset == should_reset
    assert remote._certificate_status is CertificateStatus.ERROR

    await remote.stop()


@pytest.mark.parametrize(
    ("reason", "should_reset"),
    (
        (
            "KEY_VALUES_MISMATCH",
            True,
        ),
        (
            "Boom",
            False,
        ),
    ),
)
async def test_context_error_handling(
    auth_cloud_mock,
    mock_cognito,
    valid_acme_mock,
    aioclient_mock,
    snitun_mock,
    reason,
    should_reset,
):
    """Test that we reset if we hit an error reason that require resetting."""
    auth_cloud_mock.servicehandlers_server = "test.local"

    remote = RemoteUI(auth_cloud_mock)

    aioclient_mock.post(
        "https://test.local/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )

    ssl_error = SSLError()
    ssl_error.reason = reason

    with patch(
        "hass_nabucasa.remote.RemoteUI._create_context",
        side_effect=ssl_error,
    ):
        assert remote._certificate_status is None
        await remote.load_backend()

    await asyncio.sleep(0.1)
    assert remote._acme.call_reset == should_reset
    assert remote._certificate_status is CertificateStatus.ERROR

    await remote.stop()
