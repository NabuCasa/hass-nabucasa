"""Set up some common test helper things."""
import logging
from unittest.mock import patch, MagicMock

import pytest

from .utils.aiohttp import mock_aiohttp_client, AiohttpClientMocker
from .common import TestPreferences, TestClient

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

    cloud.prefs = TestPreferences()
    await cloud.prefs.async_initialize()

    cloud.websession = aioclient_mock.create_session(loop)
    cloud.client = TestClient(loop, cloud.websession)

    yield cloud

    await cloud.websession.close()
