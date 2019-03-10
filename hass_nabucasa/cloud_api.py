"""Cloud APIs."""
from functools import wraps
import logging

from aiohttp.hdrs import AUTHORIZATION

_LOGGER = logging.getLogger(__name__)


def _check_token(func):
    """Decorate a function to verify valid token."""

    @wraps(func)
    async def check_token(cloud, *args):
        """Validate token, then call func."""
        await cloud.run_executor(cloud.auth.check_token)
        return await func(cloud, *args)

    return check_token


def _log_response(func):
    """Decorate a function to log bad responses."""

    @wraps(func)
    async def log_response(*args):
        """Log response if it's bad."""
        resp = await func(*args)
        meth = _LOGGER.debug if resp.status < 400 else _LOGGER.warning
        meth("Fetched %s (%s)", resp.url, resp.status)
        return resp

    return log_response


@_check_token
@_log_response
async def async_create_cloudhook(cloud):
    """Create a cloudhook."""
    return await cloud.websession.post(
        cloud.cloudhook_create_url, headers={AUTHORIZATION: cloud.id_token}
    )


@_check_token
@_log_response
async def async_remote_register(cloud):
    """Create/Get a remote URL."""
    url = "{}/register_instance".format(cloud.remote_api_url)
    return await cloud.websession.post(url, headers={AUTHORIZATION: cloud.id_token})


@_check_token
@_log_response
async def async_remote_token(cloud, aes_key: bytes, aes_iv: bytes):
    """Create a remote snitun token."""
    url = "{}/snitun_token".format(cloud.remote_api_url)
    return await cloud.websession.post(
        url,
        headers={AUTHORIZATION: cloud.id_token},
        json={"aes_key": aes_key.hex(), "aes_iv": aes_iv.hex()},
    )


@_check_token
@_log_response
async def async_remote_challenge_txt(cloud, txt: str):
    """Set DNS challenge."""
    url = "{}/challenge_txt".format(cloud.remote_api_url)
    return await cloud.websession.post(
        url, headers={AUTHORIZATION: cloud.id_token}, json={"txt": txt}
    )


@_check_token
@_log_response
async def async_remote_challenge_cleanup(cloud, txt: str):
    """Remove DNS challenge."""
    url = "{}/challenge_cleanup".format(cloud.remote_api_url)
    return await cloud.websession.post(
        url, headers={AUTHORIZATION: cloud.id_token}, json={"txt": txt}
    )
