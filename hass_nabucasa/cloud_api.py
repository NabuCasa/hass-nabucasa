"""Cloud APIs."""
from functools import wraps
import logging

from aiohttp.hdrs import AUTHORIZATION
from aiohttp import ClientResponse

_LOGGER = logging.getLogger(__name__)


def _check_token(func):
    """Decorate a function to verify valid token."""

    @wraps(func)
    async def check_token(cloud, *args):
        """Validate token, then call func."""
        await cloud.auth.async_check_token()
        return await func(cloud, *args)

    return check_token


def _log_response(func):
    """Decorate a function to log bad responses."""

    @wraps(func)
    async def log_response(*args):
        """Log response if it's bad."""
        resp: ClientResponse = await func(*args)
        if resp.ok:
            _LOGGER.debug("Fetched %s (%d)", resp.url, resp.status)
        else:
            _LOGGER.warning("Fetched %s (%d): %s", resp.url, resp.status, resp.reason)
        return resp

    return log_response


@_check_token
@_log_response
async def async_create_cloudhook(cloud) -> ClientResponse:
    """Create a cloudhook."""
    return await cloud.websession.post(
        cloud.cloudhook_create_url, headers={AUTHORIZATION: cloud.id_token}
    )


@_check_token
@_log_response
async def async_remote_register(cloud) -> ClientResponse:
    """Create/Get a remote URL."""
    url = f"{cloud.remote_api_url}/register_instance"
    return await cloud.websession.post(url, headers={AUTHORIZATION: cloud.id_token})


@_check_token
@_log_response
async def async_remote_token(cloud, aes_key: bytes, aes_iv: bytes) -> ClientResponse:
    """Create a remote snitun token."""
    url = f"{cloud.remote_api_url}/snitun_token"
    return await cloud.websession.post(
        url,
        headers={AUTHORIZATION: cloud.id_token},
        json={"aes_key": aes_key.hex(), "aes_iv": aes_iv.hex()},
    )


@_check_token
@_log_response
async def async_remote_challenge_txt(cloud, txt: str) -> ClientResponse:
    """Set DNS challenge."""
    url = f"{cloud.remote_api_url}/challenge_txt"
    return await cloud.websession.post(
        url, headers={AUTHORIZATION: cloud.id_token}, json={"txt": txt}
    )


@_check_token
@_log_response
async def async_remote_challenge_cleanup(cloud, txt: str) -> ClientResponse:
    """Remove DNS challenge."""
    url = f"{cloud.remote_api_url}/challenge_cleanup"
    return await cloud.websession.post(
        url, headers={AUTHORIZATION: cloud.id_token}, json={"txt": txt}
    )


@_check_token
@_log_response
async def async_alexa_access_token(cloud) -> ClientResponse:
    """Request Alexa access token."""
    return await cloud.websession.post(
        cloud.alexa_access_token_url, headers={AUTHORIZATION: cloud.id_token}
    )


@_check_token
@_log_response
async def async_voice_connection_details(cloud) -> ClientResponse:
    """Return connection details for voice service."""
    url = f"{cloud.voice_api_url}/connection_details"
    return await cloud.websession.get(url, headers={AUTHORIZATION: cloud.id_token})


@_check_token
@_log_response
async def async_google_actions_request_sync(cloud) -> ClientResponse:
    """Request a Google Actions sync request."""
    return await cloud.websession.post(
        f"{cloud.google_actions_report_state_url}/request_sync",
        headers={AUTHORIZATION: f"Bearer {cloud.id_token}"},
    )
