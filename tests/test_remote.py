"""Test remote sni handler."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from datetime import timedelta
from ssl import SSLError
from typing import Any
from unittest.mock import Mock, patch

from acme import client, messages
import aiohttp
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa import Cloud, utils
from hass_nabucasa.accounts_api import AccountsApiError
from hass_nabucasa.acme import AcmeHandler
from hass_nabucasa.const import (
    DISPATCH_CERTIFICATE_STATUS,
    DISPATCH_REMOTE_BACKEND_DOWN,
    DISPATCH_REMOTE_BACKEND_UP,
    DISPATCH_REMOTE_CONNECT,
    DISPATCH_REMOTE_DISCONNECT,
    CertificateStatus,
)
from hass_nabucasa.remote import (
    RENEW_IF_EXPIRES_DAYS,
    WARN_RENEW_FAILED_DAYS,
    SubscriptionExpired,
)
from hass_nabucasa.utils import utcnow
from tests.common import extract_log_messages
from tests.utils.aiohttp import AiohttpClientMocker

from .common import MockAcme, MockSnitun

# pylint: disable=protected-access


@pytest.fixture
def mock_timing() -> Generator[None]:
    """Mock timing functions for remote tests."""
    original_sleep = asyncio.sleep

    async def mock_sleep(seconds: float) -> None:
        """Mock sleep that only sleeps for very short time."""
        await original_sleep(0.001)

    with (
        patch("hass_nabucasa.utils.next_midnight", return_value=0),
        patch("random.randint", return_value=0),
        patch("hass_nabucasa.remote.random.randint", return_value=0),
        patch("hass_nabucasa.remote.asyncio.sleep", side_effect=mock_sleep),
    ):
        yield


@pytest.fixture(autouse=True)
def ignore_context() -> Generator[Mock]:
    """Ignore ssl context."""
    with patch(
        "hass_nabucasa.remote.RemoteUI._create_context",
        return_value=None,
    ) as context:
        yield context


@pytest.fixture
def acme_mock() -> Generator[MockAcme]:
    """Mock ACME client."""
    with patch("hass_nabucasa.remote.AcmeHandler", new_callable=MockAcme) as acme:
        yield acme


@pytest.fixture
def valid_acme_mock(acme_mock: MockAcme) -> MockAcme:
    """Mock ACME client with valid cert."""
    acme_mock.common_name = "test.dui.nabu.casa"
    acme_mock.alternative_names = ["test.dui.nabu.casa"]
    acme_mock.expire_date = utcnow() + timedelta(days=60)
    return acme_mock


@pytest.fixture
async def snitun_mock() -> AsyncGenerator[MockSnitun]:
    """Mock ACME client."""
    with patch("hass_nabucasa.remote.SniTunClientAioHttp", MockSnitun()) as snitun:
        yield snitun


async def test_load_backend_exists_cert(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    assert cloud.remote.certificate_status is None

    assert not cloud.remote.is_connected
    await cloud.remote.start()
    await cloud.remote._info_loaded.wait()
    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert cloud.remote.instance_domain == "test.dui.nabu.casa"

    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.init_args == (
        cloud,
        ["test.dui.nabu.casa"],
        "test@nabucasa.inc",
    )
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (cloud.client.aiohttp_runner, None)
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
    assert cloud.remote.is_connected

    assert cloud.remote._acme_task
    assert cloud.remote._reconnect_task

    # Check that certificate status updates were dispatched
    certificate_dispatches = [
        call
        for call in cloud.client.mock_dispatcher
        if call[0] == DISPATCH_CERTIFICATE_STATUS
    ]
    # Should have certificate status updates
    assert len(certificate_dispatches) >= 1

    # Check that backend and connection dispatches happened
    backend_dispatches = [
        call
        for call in cloud.client.mock_dispatcher
        if call[0] in (DISPATCH_REMOTE_BACKEND_UP, DISPATCH_REMOTE_CONNECT)
    ]
    assert any(call[0] == DISPATCH_REMOTE_BACKEND_UP for call in backend_dispatches)
    assert any(call[0] == DISPATCH_REMOTE_CONNECT for call in backend_dispatches)

    await cloud.remote.stop()
    await asyncio.sleep(0.1)

    assert not cloud.remote._acme_task
    assert cloud.remote.certificate_status == CertificateStatus.READY


async def test_load_backend_not_exists_cert(
    cloud: Cloud,
    acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    acme_mock.set_false()
    await cloud.remote.start()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert acme_mock.call_issue
    assert acme_mock.init_args == (
        cloud,
        ["test.dui.nabu.casa"],
        "test@nabucasa.inc",
    )
    assert acme_mock.call_hardening
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (cloud.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    assert cloud.remote._acme_task
    assert cloud.remote._reconnect_task

    await cloud.remote.stop()
    await asyncio.sleep(0.1)

    assert not cloud.remote._acme_task


async def test_load_and_unload_backend(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    await cloud.remote.start()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.init_args == (
        cloud,
        ["test.dui.nabu.casa"],
        "test@nabucasa.inc",
    )
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert not snitun_mock.call_stop
    assert snitun_mock.init_args == (cloud.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert cloud.remote._acme_task
    assert cloud.remote._reconnect_task

    await cloud.remote.stop()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_stop

    assert not cloud.remote._acme_task
    assert not cloud.remote._reconnect_task

    assert cloud.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_BACKEND_DOWN


async def test_load_backend_exists_wrong_cert(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["example.com"],
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    aioclient_mock.post(
        f"https://{cloud.accounts_server}/instance/resolve_dns_cname",
        json=[
            "test.dui.nabu.casa",
            "_acme-challenge.test.dui.nabu.casa",
        ],
    )

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa"]
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert valid_acme_mock.call_reset
    assert valid_acme_mock.init_args == (
        cloud,
        ["test.dui.nabu.casa", "example.com"],
        "test@nabucasa.inc",
    )
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (cloud.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    await cloud.remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


async def test_call_disconnect(
    cloud: Cloud,
    acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    assert not cloud.remote.is_connected
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)
    assert cloud.remote.is_connected

    await cloud.remote.disconnect()
    assert snitun_mock.call_disconnect
    assert not cloud.remote.is_connected
    assert cloud.remote._token
    assert cloud.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_DISCONNECT


async def test_load_backend_no_autostart(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    cloud.client.prop_remote_autostart = False
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start

    assert not snitun_mock.call_connect

    await cloud.remote.connect()

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400
    assert cloud.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_CONNECT

    await cloud.remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


async def test_get_certificate_details(
    cloud: Cloud,
    acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    assert cloud.remote.certificate is None

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    cloud.client.prop_remote_autostart = False
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)
    assert cloud.remote.certificate is None

    acme_mock.common_name = "test"
    acme_mock.alternative_names = ["test"]
    acme_mock.expire_date = valid
    acme_mock.fingerprint = "ffff"

    certificate = cloud.remote.certificate
    assert certificate.common_name == "test"
    assert certificate.alternative_names == ["test"]
    assert certificate.expire_date == valid
    assert certificate.fingerprint == "ffff"


async def test_certificate_task_no_backend(
    cloud: Cloud,
    acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
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
        acme_task = cloud.remote._acme_task = asyncio.create_task(
            cloud.remote._certificate_handler(),
        )
        await asyncio.sleep(0.1)
        assert acme_mock.call_issue
        assert snitun_mock.call_start

        await cloud.remote.stop()
        await asyncio.sleep(0.1)

        assert acme_task.done()


async def test_certificate_task_renew_cert(
    cloud: Cloud,
    acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
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
        acme_task = cloud.remote._acme_task = asyncio.create_task(
            cloud.remote._certificate_handler(),
        )

        await cloud.remote.load_backend()
        await asyncio.sleep(0.1)
        assert acme_mock.call_issue

        await cloud.remote.stop()
        await asyncio.sleep(0.1)

        assert acme_task.done()


async def test_refresh_token_no_sub(cloud: Cloud, mock_timing: None) -> None:
    """Test that we rais SubscriptionExpired if expired sub."""
    with (
        patch.object(
            type(cloud),
            "subscription_expired",
            new_callable=lambda: property(lambda _: True),
        ),
        pytest.raises(SubscriptionExpired),
    ):
        await cloud.remote._refresh_snitun_token()


async def test_load_connect_insecure(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    # Mock the error response via aioclient_mock instead

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
        status=409,
    )

    cloud.client.prop_remote_autostart = True
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start

    assert not snitun_mock.call_connect

    assert not snitun_mock.call_connect
    assert cloud.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_BACKEND_UP

    assert snapshot == extract_log_messages(caplog)


async def test_load_connect_forbidden(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    # Mock the error response via aioclient_mock instead

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "message": "lorem_ipsum",
        },
        status=403,
        headers={"content-type": "application/json; charset=utf-8"},
    )

    cloud.client.prop_remote_autostart = True
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_issue
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert not snitun_mock.call_connect

    assert snapshot == extract_log_messages(caplog)


async def test_call_disconnect_clean_token(
    cloud: Cloud,
    acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    mock_timing: None,
) -> None:
    """Initialize backend."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )

    assert not cloud.remote.is_connected
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)
    assert cloud.remote.is_connected
    assert cloud.remote._token

    await cloud.remote.disconnect(clear_snitun_token=True)
    assert snitun_mock.call_disconnect
    assert not cloud.remote.is_connected
    assert cloud.remote._token is None
    assert cloud.client.mock_dispatcher[-1][0] == DISPATCH_REMOTE_DISCONNECT


async def test_recreating_old_certificate_with_bad_dns_config(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    mock_timing: None,
) -> None:
    """Test recreating old certificate with bad DNS config for alias."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["example.com"],
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )
    aioclient_mock.post(
        f"https://{cloud.accounts_server}/instance/resolve_dns_cname",
        json=["test.dui.nabu.casa"],
    )

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa", "example.com"]
    valid_acme_mock.expire_date = utils.utcnow() + timedelta(
        days=WARN_RENEW_FAILED_DAYS,
    )
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert valid_acme_mock.call_reset
    assert valid_acme_mock.init_args == (
        cloud,
        ["test.dui.nabu.casa"],
        "test@nabucasa.inc",
    )
    assert valid_acme_mock.call_hardening
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (cloud.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert snapshot == cloud.client.mock_repairs

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    await cloud.remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


@pytest.mark.parametrize(
    "exception",
    (
        AccountsApiError("DNS resolution failed"),
        aiohttp.ClientError("DNS resolution failed"),
        TimeoutError(),
    ),
)
async def test_warn_about_bad_dns_config_for_old_certificate(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    mock_timing: None,
    exception: Exception,
) -> None:
    """Test warn about old certificate with bad DNS config for alias."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["example.com"],
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )
    aioclient_mock.post(
        f"https://{cloud.accounts_server}/instance/resolve_dns_cname",
        exc=exception,
    )

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa", "example.com"]
    valid_acme_mock.expire_date = utils.utcnow() + timedelta(days=RENEW_IF_EXPIRES_DAYS)
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_reset
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (cloud.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert snapshot == cloud.client.mock_repairs

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    await cloud.remote.disconnect()
    await asyncio.sleep(0.1)

    assert snitun_mock.call_disconnect


async def test_regeneration_without_warning_for_good_dns_config(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    snapshot: SnapshotAssertion,
    mock_timing: None,
) -> None:
    """Test no warning for good dns config."""
    valid = utcnow() + timedelta(days=1)

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["example.com"],
        },
    )
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/snitun_token",
        json={
            "token": "test-token",
            "server": "rest-remote.nabu.casa",
            "valid": valid.timestamp(),
            "throttling": 400,
        },
    )
    aioclient_mock.post(
        f"https://{cloud.accounts_server}/instance/resolve_dns_cname",
        json=[
            "test.dui.nabu.casa",
            "_acme-challenge.test.dui.nabu.casa",
        ],
    )

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa", "example.com"]
    valid_acme_mock.expire_date = utils.utcnow() + timedelta(days=RENEW_IF_EXPIRES_DAYS)
    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)

    assert cloud.remote.snitun_server == "rest-remote.nabu.casa"
    assert not valid_acme_mock.call_reset
    assert valid_acme_mock.call_issue
    assert snitun_mock.call_start
    assert snitun_mock.init_args == (cloud.client.aiohttp_runner, None)
    assert snitun_mock.init_kwarg == {
        "snitun_server": "rest-remote.nabu.casa",
        "snitun_port": 443,
    }

    assert snapshot == cloud.client.mock_repairs

    assert snitun_mock.call_connect
    assert snitun_mock.connect_args[0] == b"test-token"
    assert snitun_mock.connect_args[3] == 400

    await cloud.remote.disconnect()
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
                "detail": "Unable to validate JWS",
            },
            True,
        ),
        (
            {
                "type": "urn:ietf:params:acme:error:malformed",
                "detail": "Unable to validate JWS :: Invalid Content-Type header on",
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
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    json_error: dict[str, str],
    should_reset: bool,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    mock_timing: None,
) -> None:
    """Initialize backend."""

    class _MockAcmeClient(client.ClientV2):
        def __init__(self) -> None:
            pass

        def new_order(self, _: Any) -> None:
            raise messages.Error.from_json(json_error)

    class _MockAcme(AcmeHandler):
        call_reset: bool = False
        # cloud instance passed via constructor

        @property
        def certificate_available(self) -> bool:
            return True

        @property
        def alternative_names(self) -> list[str]:
            return ["test.dui.nabu.casa"]

        def _generate_csr(self) -> bytes:
            return b""

        def _create_client(self) -> None:
            self._acme_client = _MockAcmeClient()

        async def reset_acme(self) -> None:
            self.call_reset = True

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )

    with patch(
        "hass_nabucasa.remote.AcmeHandler",
        return_value=_MockAcme(cloud, [], "test@nabucasa.inc", Mock()),
    ):
        assert cloud.remote._certificate_status is None
        await cloud.remote.load_backend()

    await asyncio.sleep(0.1)
    assert cloud.remote._acme.call_reset == should_reset
    assert cloud.remote._certificate_status is CertificateStatus.INITIAL_CERT_ERROR

    assert snapshot == extract_log_messages(caplog)

    await cloud.remote.stop()


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
                "detail": "Unable to validate JWS",
            },
            True,
        ),
        (
            {
                "type": "urn:ietf:params:acme:error:malformed",
                "detail": "Unable to validate JWS :: Invalid Content-Type header on",
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
async def test_acme_client_create_client_jws_errors(
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    json_error: dict[str, str],
    should_reset: bool,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    mock_timing: None,
) -> None:
    """Test ACME client creation JWS error handling."""

    class _MockAcmeClient(client.ClientV2):
        def __init__(self) -> None:
            pass

        @classmethod
        def get_directory(cls, *_: Any, **_kwargs: Any) -> None:
            raise messages.Error.from_json(json_error)

    class _MockAcme(AcmeHandler):
        call_reset: bool = False
        # cloud instance passed via constructor

        @property
        def certificate_available(self) -> bool:
            return True

        @property
        def alternative_names(self) -> list[str]:
            return ["test.dui.nabu.casa"]

        def _load_account_key(self) -> None:
            self._account_jwk = Mock()

        def _create_client(self) -> None:
            with patch("hass_nabucasa.acme.client.ClientV2", _MockAcmeClient):
                super()._create_client()

        async def reset_acme(self) -> None:
            self.call_reset = True

    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )

    with patch(
        "hass_nabucasa.remote.AcmeHandler",
        return_value=_MockAcme(cloud, [], "test@nabucasa.inc", Mock()),
    ):
        assert cloud.remote._certificate_status is None
        await cloud.remote.load_backend()

    await asyncio.sleep(0.1)
    assert cloud.remote._acme.call_reset == should_reset
    assert cloud.remote._certificate_status is CertificateStatus.INITIAL_CERT_ERROR

    assert snapshot == extract_log_messages(caplog)

    await cloud.remote.stop()


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
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
    snitun_mock: MockSnitun,
    reason: str,
    should_reset: bool,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    mock_timing: None,
) -> None:
    """Test that we reset if we hit an error reason that require resetting."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )

    ssl_error = SSLError()
    ssl_error.reason = reason

    # Patch _create_context to raise SSL error directly
    with patch.object(cloud.remote, "_create_context", side_effect=ssl_error):
        assert cloud.remote._certificate_status is None
        await cloud.remote.load_backend()

        await asyncio.sleep(0.1)
        assert cloud.remote._acme.call_reset == should_reset
        assert cloud.remote._certificate_status is CertificateStatus.SSL_CONTEXT_ERROR

        assert snapshot == extract_log_messages(caplog)

    await cloud.remote.stop()


async def test_certificate_status_dispatcher(cloud: Cloud) -> None:
    """Test certificate status dispatcher functionality."""
    # Test status update dispatching
    cloud.remote._update_certificate_status(CertificateStatus.LOADING)

    # Check that dispatcher was called
    assert len(cloud.client.mock_dispatcher) == 1
    assert cloud.client.mock_dispatcher[0] == (
        DISPATCH_CERTIFICATE_STATUS,
        CertificateStatus.LOADING,
    )

    # Test second status update
    cloud.remote._update_certificate_status(CertificateStatus.ERROR)

    assert len(cloud.client.mock_dispatcher) == 2
    assert cloud.client.mock_dispatcher[1] == (
        DISPATCH_CERTIFICATE_STATUS,
        CertificateStatus.ERROR,
    )

    # Test duplicate status update (should be ignored)
    cloud.remote._update_certificate_status(CertificateStatus.ERROR)

    # Should still be 2 calls since status didn't change
    assert len(cloud.client.mock_dispatcher) == 2


async def test_recreate_acme_calls_reset_when_acme_exists(cloud: Cloud) -> None:
    """Test that _recreate_acme calls reset_acme when _acme exists."""
    mock_acme = MockAcme()
    cloud.remote._acme = mock_acme

    await cloud.remote._recreate_acme(["new.example.com"], "new@example.com")

    assert mock_acme.call_reset is True
    assert cloud.remote._acme is not mock_acme


async def test_recreate_acme_with_certificate_available(cloud: Cloud) -> None:
    """Test _recreate_acme behavior when certificate is available."""
    mock_acme = MockAcme()
    cloud.remote._acme = mock_acme

    await cloud.remote._recreate_acme(["new.example.com"], "new@example.com")

    assert mock_acme.call_reset is True
    assert cloud.remote._acme is not mock_acme


async def test_recreate_acme_without_certificate_available(cloud: Cloud) -> None:
    """Test _recreate_acme behavior when certificate is not available."""
    mock_acme = MockAcme()
    mock_acme.common_name = None
    cloud.remote._acme = mock_acme

    await cloud.remote._recreate_acme(["new.example.com"], "new@example.com")

    assert mock_acme.call_reset is True
    assert cloud.remote._acme is not mock_acme


async def test_recreate_acme_with_error_status(cloud: Cloud) -> None:
    """Test _recreate_acme behavior when certificate status is ERROR."""
    mock_acme = MockAcme()
    cloud.remote._acme = mock_acme
    cloud.remote._certificate_status = CertificateStatus.ERROR

    await cloud.remote._recreate_acme(["new.example.com"], "new@example.com")

    assert mock_acme.call_reset is True
    assert cloud.remote._acme is not mock_acme


async def test_recreate_acme_when_no_acme_exists(cloud: Cloud) -> None:
    """Test _recreate_acme behavior when no ACME handler exists."""
    cloud.remote._acme = None

    await cloud.remote._recreate_acme(["test.example.com"], "test@example.com")

    assert cloud.remote._acme is not None


async def test_recreate_acme_integration_during_load_backend(
    cloud: Cloud,
    valid_acme_mock: MockAcme,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test _recreate_acme integration during load_backend with domain changes."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
            "alias": ["new-alias.com"],
        },
    )
    aioclient_mock.post(
        f"https://{cloud.accounts_server}/instance/resolve_dns_cname",
        json=[
            "test.dui.nabu.casa",
            "_acme-challenge.test.dui.nabu.casa",
        ],
    )

    valid_acme_mock.common_name = "test.dui.nabu.casa"
    valid_acme_mock.alternative_names = ["test.dui.nabu.casa", "old-alias.com"]

    await cloud.remote.load_backend()
    await asyncio.sleep(0.1)

    assert valid_acme_mock.call_reset is True

    expected_domains = ["test.dui.nabu.casa", "new-alias.com"]
    assert valid_acme_mock.init_args == (
        cloud,
        expected_domains,
        "test@nabucasa.inc",
    )
