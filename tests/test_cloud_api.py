"""Test cloud API."""
from unittest.mock import Mock, patch

import pytest

from hass_nabucasa import cloud_api


@pytest.fixture(autouse=True)
def mock_check_token():
    """Mock check token."""
    with patch("hass_nabucasa.auth_api." "check_token"):
        yield


async def test_create_cloudhook(cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/bla",
        json={"cloudhook_id": "mock-webhook", "url": "https://blabla"},
    )
    cloud_mock.id_token = "mock-id-token"
    cloud_mock.cloudhook_create_url = "https://example.com/bla"

    resp = await cloud_api.async_create_cloudhook(cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {
        "cloudhook_id": "mock-webhook",
        "url": "https://blabla",
    }
