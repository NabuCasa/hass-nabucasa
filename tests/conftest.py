"""Set up some common test helper things."""
import logging
from unittest.mock import patch, MagicMock

import pytest

from .utils.aiohttp import mock_aiohttp_client, AiohttpClientMocker
from .common import TestClient, mock_coro

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
async def aioclient_mock(loop):
    """Fixture to mock aioclient calls."""
    with mock_aiohttp_client(loop) as mock_session:
        yield mock_session


@pytest.fixture
async def cloud_mock(loop, aioclient_mock):
    """Simple cloud mock."""
    cloud = MagicMock()
    cloud.run_task = loop.create_task

    def _executor(call, *args):
        """Run executor."""
        return loop.run_in_executor(None, call, *args)

    cloud.run_executor = _executor

    cloud.websession = aioclient_mock.create_session(loop)
    cloud.client = TestClient(loop, cloud.websession)

    yield cloud

    await cloud.websession.close()


@pytest.fixture
def auth_cloud_mock(cloud_mock):
    """Return an authenticated cloud instance."""
    cloud_mock.auth.async_check_token = mock_coro
    return cloud_mock


@pytest.fixture
def cloud_client(cloud_mock):
    """Return cloud client impl."""
    yield cloud_mock.client


@pytest.fixture
def mock_cognito():
    """Mock warrant."""
    with patch("hass_nabucasa.auth.CognitoAuth._cognito") as mock_cog:
        yield mock_cog()
