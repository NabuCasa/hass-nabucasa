"""Set up some common test helper things."""
import logging
from unittest.mock import patch, MagicMock

import pytest

from .utils.aiohttp import mock_aiohttp_client

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def aioclient_mock():
    """Fixture to mock aioclient calls."""
    with mock_aiohttp_client() as mock_session:
        yield mock_session


@pytest.fixture
def cloud_mock(loop):
    """Simple cloud mock."""
    cloud = MagicMock()
    cloud.run_task = loop.create_task

    def _executor(call, *args):
        """Run executor."""
        return loop.run_in_executor(None, call, *args)

    cloud.run_executor = _executor

    yield cloud
