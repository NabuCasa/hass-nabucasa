"""Cloud APIs."""
from __future__ import annotations

from functools import wraps
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    TypeVar,
)
from aiohttp import ClientResponse

from aiohttp.hdrs import AUTHORIZATION

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

if TYPE_CHECKING:
    from . import Cloud


def _do_log_response(resp: ClientResponse) -> None:
    """Log the response."""
    meth = _LOGGER.debug if resp.status < 400 else _LOGGER.warning
    meth("Fetched %s (%s)", resp.url, resp.status)


def _check_token(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorate a function to verify valid token."""

    @wraps(func)
    async def check_token(cloud: Cloud, *args: Any) -> T:
        """Validate token, then call func."""
        await cloud.auth.async_check_token()
        return await func(cloud, *args)

    return check_token


def _log_response(
    func: Callable[..., Awaitable[ClientResponse]]
) -> Callable[..., Awaitable[ClientResponse]]:
    """Decorate a function to log bad responses."""

    @wraps(func)
    async def log_response(*args: Any) -> ClientResponse:
        """Log response if it's bad."""
        resp = await func(*args)
        _do_log_response(resp)
        return resp

    return log_response


@_check_token
@_log_response
async def async_create_cloudhook(cloud: Cloud) -> ClientResponse:
    """Create a cloudhook."""
    return await cloud.websession.post(
        f"https://{cloud.cloudhook_server}/generate",
        headers={AUTHORIZATION: cloud.id_token},
    )


@_check_token
@_log_response
async def async_remote_register(cloud: Cloud) -> ClientResponse:
    """Create/Get a remote URL."""
    url = f"https://{cloud.remote_sni_server}/register_instance"
    return await cloud.websession.post(url, headers={AUTHORIZATION: cloud.id_token})


@_check_token
@_log_response
async def async_remote_token(
    cloud: Cloud, aes_key: bytes, aes_iv: bytes
) -> ClientResponse:
    """Create a remote snitun token."""
    url = f"https://{cloud.remote_sni_server}/snitun_token"
    return await cloud.websession.post(
        url,
        headers={AUTHORIZATION: cloud.id_token},
        json={"aes_key": aes_key.hex(), "aes_iv": aes_iv.hex()},
    )


@_check_token
@_log_response
async def async_remote_challenge_txt(cloud: Cloud, txt: str) -> ClientResponse:
    """Set DNS challenge."""
    url = f"https://{cloud.remote_sni_server}/challenge_txt"
    return await cloud.websession.post(
        url, headers={AUTHORIZATION: cloud.id_token}, json={"txt": txt}
    )


@_check_token
@_log_response
async def async_remote_challenge_cleanup(cloud: Cloud, txt: str) -> ClientResponse:
    """Remove DNS challenge."""
    url = f"https://{cloud.remote_sni_server}/challenge_cleanup"
    return await cloud.websession.post(
        url, headers={AUTHORIZATION: cloud.id_token}, json={"txt": txt}
    )


@_check_token
@_log_response
async def async_alexa_access_token(cloud: Cloud) -> ClientResponse:
    """Request Alexa access token."""
    return await cloud.websession.post(
        f"https://{cloud.alexa_server}/access_token",
        headers={AUTHORIZATION: cloud.id_token},
    )


@_check_token
@_log_response
async def async_voice_connection_details(cloud: Cloud) -> ClientResponse:
    """Return connection details for voice service."""
    url = f"https://{cloud.servicehandlers_server}/voice/connection_details"
    return await cloud.websession.get(url, headers={AUTHORIZATION: cloud.id_token})


@_check_token
@_log_response
async def async_google_actions_request_sync(cloud: Cloud) -> ClientResponse:
    """Request a Google Actions sync request."""
    return await cloud.websession.post(
        f"https://{cloud.remotestate_server}/request_sync",
        headers={AUTHORIZATION: f"Bearer {cloud.id_token}"},
    )


@_check_token
async def async_subscription_info(cloud: Cloud) -> dict[str, Any]:
    """Fetch subscription info."""
    resp = await cloud.websession.get(
        f"https://{cloud.accounts_server}/payments/subscription_info",
        headers={"authorization": cloud.id_token},
    )
    _do_log_response(resp)
    resp.raise_for_status()
    data: dict[str, Any] = await resp.json()

    # If subscription info indicates we are subscribed, force a refresh of the token
    if data.get("provider") and not cloud.started:
        _LOGGER.debug("Found disconnected account with valid subscription, connecting")
        await cloud.auth.async_renew_access_token()

    return data


@_check_token
async def async_migrate_paypal_agreement(cloud: Cloud) -> dict[str, Any]:
    """Migrate a paypal agreement from legacy."""
    resp = await cloud.websession.post(
        f"https://{cloud.accounts_server}/payments/migrate_paypal_agreement",
        headers={"authorization": cloud.id_token},
    )
    _do_log_response(resp)
    resp.raise_for_status()
    data: dict[str, Any] = await resp.json()
    return data
