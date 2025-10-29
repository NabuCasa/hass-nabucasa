"""Tests for Service Discovery API."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
import re
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa.const import FIVE_MINUTES_IN_SECONDS
from hass_nabucasa.service_discovery import (
    MIN_REFRESH_INTERVAL,
    ServiceDiscovery,
    ServiceDiscoveryError,
    ServiceDiscoveryMissingActionError,
    ServiceDiscoveryMissingParameterError,
    _calculate_sleep_time,
)
from hass_nabucasa.utils import utcnow

from .common import (
    FreezeTimeFixture,
    extract_log_messages,
)

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker

BASE_EXPECTED_RESULT = {
    "actions": {"test_api_action": "https://example.com/test/{param}/action"},
    "valid_for": 3600,
    "version": "1.0",
}


def assert_snapshot_with_logs(
    result: Any, caplog: pytest.LogCaptureFixture, snapshot: SnapshotAssertion
) -> None:
    """Assert result and logs match snapshot."""
    assert {"result": result, "log": extract_log_messages(caplog)} == snapshot


@pytest.fixture(autouse=True)
def jitter_patch() -> Generator[Any, Any, Any]:
    """Mock jitter to always return 0."""
    with patch("hass_nabucasa.service_discovery.jitter", return_value=111):
        yield


@pytest.fixture(autouse=True)
def add_test_api_action_to_service_discovery():
    """Add test_api_action for this module's tests."""
    with (
        patch(
            "hass_nabucasa.service_discovery.VALID_ACTION_NAMES",
            frozenset(BASE_EXPECTED_RESULT["actions"].keys()),
        ),
    ):
        yield


@pytest.mark.parametrize(
    "exception,mockargs,exception_msg",
    [
        [
            ServiceDiscoveryError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to parse API response",
        ],
        [
            ServiceDiscoveryError,
            {"status": 429, "text": "Too fast"},
            "Failed to parse API response",
        ],
        [
            ServiceDiscoveryError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            ServiceDiscoveryError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            ServiceDiscoveryError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_fetch_well_known_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with well-known service discovery endpoint."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await cloud.service_discovery._fetch_well_known_service_discovery()


async def test_fetch_well_known_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful fetch of well-known service discovery endpoint."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    result = await cloud.service_discovery._fetch_well_known_service_discovery()

    assert result == BASE_EXPECTED_RESULT
    assert_snapshot_with_logs(result, caplog, snapshot)


async def test_fetch_well_known_invalid_response(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test invalid response from well-known service discovery endpoint."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json={"invalid": "data"},
    )

    with pytest.raises(
        ServiceDiscoveryError, match=re.escape("required key not provided")
    ):
        await cloud.service_discovery._fetch_well_known_service_discovery()


async def test_load_service_discovery_data_caches_result(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that service discovery data is cached."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    cache1 = await cloud.service_discovery._load_service_discovery_data()
    assert "Service discovery data cached" in caplog.text
    assert cache1 is not None
    assert cloud.service_discovery._memory_cache is not None

    cache2 = await cloud.service_discovery._load_service_discovery_data()
    assert cache1 is cache2

    assert_snapshot_with_logs(
        {"cache1": cache1["data"], "cache2": cache2["data"]},
        caplog,
        snapshot,
    )


async def test_load_service_discovery_data_uses_expired_cache_on_failure(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that expired cache is used when API fails."""
    expected_result = {
        **BASE_EXPECTED_RESULT,
        "version": "1.0",
    }

    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=expected_result,
    )

    cache1 = await cloud.service_discovery._load_service_discovery_data()
    assert cache1 is not None

    await asyncio.sleep(0.01)

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        status=500,
        text="Internal Server Error",
    )
    aioclient_mock.get(
        "https://example.com/.well-known/service-discovery",
        status=500,
        text="Internal Server Error",
    )

    cache2 = await cloud.service_discovery._load_service_discovery_data()
    assert cache2 is cache1
    assert_snapshot_with_logs(
        {"cache1": cache1["data"], "cache2": cache2["data"]},
        caplog,
        snapshot,
    )


async def test_load_service_discovery_data_raises_when_no_cache_and_failure(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test that error is raised when no cache exists and API fails."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        status=500,
        text="Internal Server Error",
    )

    with pytest.raises(
        ServiceDiscoveryError, match=re.escape("Failed to parse API response")
    ):
        await cloud.service_discovery._load_service_discovery_data()


async def test_async_start_service_discovery_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test starting service discovery successfully."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    await cloud.service_discovery.async_start_service_discovery()

    assert cloud.service_discovery._service_discovery_refresh_task is not None
    assert not cloud.service_discovery._service_discovery_refresh_task.done()

    await cloud.service_discovery.async_stop_service_discovery()


async def test_async_start_service_discovery_handles_initial_failure(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test that service discovery handles initial load failure gracefully."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        status=500,
        text="Internal Server Error",
    )

    await cloud.service_discovery.async_start_service_discovery()

    assert "Failed to load initial service discovery data" in caplog.text
    assert cloud.service_discovery._service_discovery_refresh_task is not None

    await cloud.service_discovery.async_stop_service_discovery()


async def test_async_stop_service_discovery(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test stopping service discovery."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    await cloud.service_discovery.async_start_service_discovery()

    assert cloud.service_discovery._service_discovery_refresh_task is not None

    await cloud.service_discovery.async_stop_service_discovery()

    assert cloud.service_discovery._service_discovery_refresh_task is None


async def test_action_url_returns_cached_url(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that action_url returns cached URL."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    await cloud.service_discovery._load_service_discovery_data()

    url = cloud.service_discovery.action_url("test_api_action", param="test")
    assert isinstance(url, str)
    assert url == "https://example.com/test/test/action"
    assert_snapshot_with_logs(url, caplog, snapshot)


async def test_action_url_returns_fallback_url(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that action_url returns fallback URL when not cached."""
    cloud.service_discovery._fallback_actions = {
        "test_api_action": "https://example.com/test/fallback/action"
    }
    url = cloud.service_discovery.action_url("test_api_action", param="test")
    assert url == "https://example.com/test/fallback/action"
    assert "Using fallback action URL" in caplog.text
    assert_snapshot_with_logs(url, caplog, snapshot)


async def test_action_url_with_format_parameters(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that action_url correctly applies format parameters."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    await cloud.service_discovery._load_service_discovery_data()

    url = cloud.service_discovery.action_url("test_api_action", param="test")
    assert isinstance(url, str)
    assert "test" in url
    assert_snapshot_with_logs(url, caplog, snapshot)


async def test_action_url_missing_format_parameter(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test that action_url raises error when format parameter is missing."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    await cloud.service_discovery._load_service_discovery_data()

    with pytest.raises(ServiceDiscoveryMissingParameterError):
        cloud.service_discovery.action_url("test_api_action")


async def test_action_url_with_override(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that action_url uses override when provided."""
    override_url = "https://override.example.com/custom"
    cloud.service_discovery._action_overrides = {"test_api_action": override_url}

    url = cloud.service_discovery.action_url("test_api_action")
    assert url == override_url
    assert "Using overridden action URL" in caplog.text
    assert_snapshot_with_logs(url, caplog, snapshot)


async def test_get_fallback_action_url_for_missing_action(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test that fallback raises error for unknown action."""
    with pytest.raises(ServiceDiscoveryMissingActionError):
        cloud.service_discovery._get_fallback_action_url("invalid_action")  # type: ignore[arg-type]


async def test_service_discovery_with_action_overrides(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that ServiceDiscovery can be initialized with action overrides."""
    override_url = "https://override.example.com/custom"
    discovery = ServiceDiscovery(
        cloud, action_overrides={"test_api_action": override_url}
    )

    url = discovery.action_url("test_api_action")
    assert url == override_url
    assert_snapshot_with_logs(url, caplog, snapshot)


async def test_invalid_action_name_in_response(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that invalid action names in response are filtered out."""
    expected_result = {
        **BASE_EXPECTED_RESULT,
        "actions": {
            **BASE_EXPECTED_RESULT["actions"],
            "invalid_action": "https://example.com/invalid",
        },
        "valid_for": 3600,
        "version": "1.0",
    }

    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=expected_result,
    )

    result = await cloud.service_discovery._fetch_well_known_service_discovery()
    assert "test_api_action" in result["actions"]
    assert "invalid_action" not in result["actions"]
    assert_snapshot_with_logs(result, caplog, snapshot)


async def test_concurrent_cache_load_uses_lock(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test that concurrent cache loads are serialized by lock."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    results = await asyncio.gather(
        cloud.service_discovery._load_service_discovery_data(),
        cloud.service_discovery._load_service_discovery_data(),
        cloud.service_discovery._load_service_discovery_data(),
    )

    assert aioclient_mock.call_count == 1
    assert all(r == results[0] for r in results)
    assert all(r["data"]["version"] == "1.0" for r in results)


async def test_background_task_lifecycle_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test complete lifecycle of background refresh task."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    await cloud.service_discovery.async_start_service_discovery()
    assert cloud.service_discovery._service_discovery_refresh_task is not None
    assert not cloud.service_discovery._service_discovery_refresh_task.done()
    assert cloud.service_discovery._memory_cache is not None
    assert cloud.service_discovery._memory_cache["data"]["version"] == "1.0"

    await cloud.service_discovery.async_stop_service_discovery()
    assert cloud.service_discovery._service_discovery_refresh_task is None


async def test_background_task_handles_api_failures(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test that background task survives initial API failures."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        status=500,
        text="Internal Server Error",
    )

    await cloud.service_discovery.async_start_service_discovery()

    assert "Failed to load initial service discovery data" in caplog.text
    assert cloud.service_discovery._service_discovery_refresh_task is not None
    assert not cloud.service_discovery._service_discovery_refresh_task.done()

    await cloud.service_discovery.async_stop_service_discovery()


async def test_stop_during_active_refresh(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test stopping service discovery during an active refresh."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json={
            **BASE_EXPECTED_RESULT,
            "valid_for": 1,
        },
    )

    await cloud.service_discovery.async_start_service_discovery()
    await asyncio.sleep(0.1)

    await cloud.service_discovery.async_stop_service_discovery()

    assert cloud.service_discovery._service_discovery_refresh_task is None
    assert "Service discovery refresh task cancelled" in caplog.text


async def test_multiple_start_stop_cycles(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test multiple start/stop cycles work correctly."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    for _ in range(3):
        await cloud.service_discovery.async_start_service_discovery()
        assert cloud.service_discovery._service_discovery_refresh_task is not None

        await cloud.service_discovery.async_stop_service_discovery()
        assert cloud.service_discovery._service_discovery_refresh_task is None


async def test_cloud_initialization_lifecycle(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test service discovery integrates properly with Cloud lifecycle."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    assert cloud.service_discovery is not None
    assert cloud.service_discovery._service_discovery_refresh_task is None

    await cloud.service_discovery.async_start_service_discovery()
    assert cloud.service_discovery._memory_cache is not None

    await cloud.stop()
    assert cloud.service_discovery._service_discovery_refresh_task is None


async def test_early_action_validation(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test that action_url validates action name early."""
    with pytest.raises(
        ServiceDiscoveryMissingActionError, match="Unknown action: invalid_action"
    ):
        cloud.service_discovery.action_url("invalid_action")  # type: ignore[arg-type]


async def test_forward_compatibility_extra_top_level_fields(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that extra top-level fields in API response are ignored."""
    api_response = {
        **BASE_EXPECTED_RESULT,
        "newFeature": "some_value",
        "anotherField": {"nested": "data"},
        "experimental": True,
    }

    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=api_response,
    )

    result = await cloud.service_discovery._fetch_well_known_service_discovery()

    assert "newFeature" not in result
    assert "anotherField" not in result
    assert "experimental" not in result
    assert result["actions"] == BASE_EXPECTED_RESULT["actions"]
    assert result["valid_for"] == 3600
    assert result["version"] == "1.0"
    assert_snapshot_with_logs(result, caplog, snapshot)


async def test_forward_compatibility_extra_actions(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that extra actions in API response are ignored."""
    api_response = {
        **BASE_EXPECTED_RESULT,
        "actions": {
            **BASE_EXPECTED_RESULT["actions"],
            "future_action_1": "https://example.com/future/action1",
            "future_action_2": "https://example.com/future/action2",
            "experimental_feature": "https://example.com/experimental",
        },
        "valid_for": 3600,
        "version": "1.0",
    }

    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=api_response,
    )

    result = await cloud.service_discovery._fetch_well_known_service_discovery()

    assert "future_action_1" not in result["actions"]
    assert "future_action_2" not in result["actions"]
    assert "experimental_feature" not in result["actions"]
    assert "test_api_action" in result["actions"]
    assert_snapshot_with_logs(result, caplog, snapshot)


async def test_forward_compatibility_combined(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test forward compatibility with both extra top-level fields and extra actions."""
    api_response = {
        **BASE_EXPECTED_RESULT,
        "actions": {
            **BASE_EXPECTED_RESULT["actions"],
            "future_action": "https://example.com/future",
        },
        "valid_for": 3600,
        "version": "2.0",
        "newTopLevelField": "future_data",
        "metadata": {"extra": "info"},
    }

    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=api_response,
    )

    result = await cloud.service_discovery._fetch_well_known_service_discovery()

    assert "newTopLevelField" not in result
    assert "metadata" not in result
    assert "future_action" not in result["actions"]
    assert "test_api_action" in result["actions"]
    assert result["valid_for"] == 3600
    assert result["version"] == "2.0"

    assert_snapshot_with_logs(result, caplog, snapshot)


async def test_network_failure_during_background_refresh(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that network failures during background refresh are handled gracefully."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json={
            **BASE_EXPECTED_RESULT,
            "valid_for": 0,
        },
    )

    await cloud.service_discovery.async_start_service_discovery()
    assert cloud.service_discovery._memory_cache is not None
    original_cache = cloud.service_discovery._memory_cache

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        exc=ClientError("Network error during refresh"),
    )

    await asyncio.sleep(0.2)

    assert cloud.service_discovery._service_discovery_refresh_task is not None
    assert not cloud.service_discovery._service_discovery_refresh_task.done()
    assert cloud.service_discovery._memory_cache is original_cache

    await cloud.service_discovery.async_stop_service_discovery()

    assert_snapshot_with_logs(
        {"cache_preserved": (original_cache is cloud.service_discovery._memory_cache)},
        caplog,
        snapshot,
    )


async def test_extremely_long_running_refresh_cycle(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that extremely long valid_for times are handled correctly."""
    one_year_seconds = 365 * 24 * 60 * 60
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json={
            **BASE_EXPECTED_RESULT,
            "valid_for": one_year_seconds,
        },
    )

    await cloud.service_discovery.async_start_service_discovery()
    assert cloud.service_discovery._memory_cache is not None

    valid_for_value = cloud.service_discovery._memory_cache["data"]["valid_for"]
    assert valid_for_value == one_year_seconds

    assert cloud.service_discovery._service_discovery_refresh_task is not None
    assert not cloud.service_discovery._service_discovery_refresh_task.done()

    url = cloud.service_discovery.action_url("test_api_action", param="test")

    await cloud.service_discovery.async_stop_service_discovery()

    assert_snapshot_with_logs(
        {
            "url": url,
            "valid_for": valid_for_value,
            "task_running": cloud.service_discovery._service_discovery_refresh_task
            is None,
        },
        caplog,
        snapshot,
    )


async def test_race_condition_stop_during_fetch(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test race condition when stop is called during an ongoing fetch."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json={
            **BASE_EXPECTED_RESULT,
            "valid_for": 0,
        },
    )

    await cloud.service_discovery.async_start_service_discovery()
    assert cloud.service_discovery._service_discovery_refresh_task is not None

    await asyncio.sleep(0.05)

    await cloud.service_discovery.async_stop_service_discovery()

    assert cloud.service_discovery._service_discovery_refresh_task is None

    assert_snapshot_with_logs(
        {
            "task_stopped": (
                cloud.service_discovery._service_discovery_refresh_task is None
            )
        },
        caplog,
        snapshot,
    )


async def test_race_condition_multiple_concurrent_stops(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test race condition when multiple stop calls happen concurrently."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json={
            **BASE_EXPECTED_RESULT,
            "valid_for": 1,
        },
    )

    await cloud.service_discovery.async_start_service_discovery()
    assert cloud.service_discovery._service_discovery_refresh_task is not None

    await asyncio.gather(
        cloud.service_discovery.async_stop_service_discovery(),
        cloud.service_discovery.async_stop_service_discovery(),
        cloud.service_discovery.async_stop_service_discovery(),
    )

    assert cloud.service_discovery._service_discovery_refresh_task is None

    assert_snapshot_with_logs(
        {
            "task_stopped": cloud.service_discovery._service_discovery_refresh_task
            is None
        },
        caplog,
        snapshot,
    )


async def test_race_condition_stop_and_start_rapid_cycling(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test rapid start/stop cycling for race conditions."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    for _ in range(5):
        await cloud.service_discovery.async_start_service_discovery()
        await asyncio.sleep(0.01)
        await cloud.service_discovery.async_stop_service_discovery()

    assert cloud.service_discovery._service_discovery_refresh_task is None

    assert_snapshot_with_logs(
        {
            "final_state_clean": cloud.service_discovery._service_discovery_refresh_task
            is None
        },
        caplog,
        snapshot,
    )


async def test_background_refresh_with_changing_network_conditions(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test background refresh handles alternating success and failure."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    await cloud.service_discovery.async_start_service_discovery()
    first_cache = cloud.service_discovery._memory_cache
    assert first_cache is not None
    assert first_cache["data"]["version"] == "1.0"

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        exc=ClientError("Temporary network failure"),
    )

    cloud.service_discovery._memory_cache = None
    with pytest.raises(ServiceDiscoveryError):
        await cloud.service_discovery._load_service_discovery_data()

    expired_cache = first_cache.copy()
    expired_cache["valid_until"] = 0
    cloud.service_discovery._memory_cache = expired_cache

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json={
            **BASE_EXPECTED_RESULT,
            "version": "2.0",
        },
    )

    second_cache = await cloud.service_discovery._load_service_discovery_data()
    assert second_cache["data"]["version"] == "2.0"
    assert first_cache is not second_cache

    await cloud.service_discovery.async_stop_service_discovery()

    assert_snapshot_with_logs(
        {
            "first_version": first_cache["data"]["version"],
            "second_version": second_cache["data"]["version"],
            "cache_updated": first_cache is not second_cache,
        },
        caplog,
        snapshot,
    )


@pytest.mark.parametrize(
    "valid_for_seconds,expected_min,expected_max",
    [
        # Expired/small: jitter(60, 300)
        (10, MIN_REFRESH_INTERVAL, FIVE_MINUTES_IN_SECONDS),
        (3600, 3605, 7200),  # 1 hour: remaining + jitter(5, 3600)
        (7200, 7205, 10800),  # 2 hours: remaining + jitter(5, 3600)
        (259200, 259205, 262800),  # 3 days: remaining + jitter(5, 3600)
    ],
)
def test_sleep_time_calculation_with_jitter(
    valid_for_seconds: int,
    expected_min: int,
    expected_max: int,
):
    """Test sleep time calculation with jitter applied."""
    now = utcnow().timestamp()
    valid_until = now + valid_for_seconds
    result = _calculate_sleep_time(valid_until)
    assert expected_min <= result <= expected_max


async def test_background_refresh_with_no_cache_uses_12_hour_retry(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    frozen_time: FreezeTimeFixture,
):
    """Test that background refresh with no cache schedules 12-hour retry."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        status=500,
        text="Internal Server Error",
    )

    await cloud.service_discovery.async_start_service_discovery()

    await asyncio.sleep(0.1)

    assert cloud.service_discovery._service_discovery_refresh_task is not None
    assert not cloud.service_discovery._service_discovery_refresh_task.done()
    assert cloud.service_discovery._memory_cache is None

    # With jitter, expect between ~11h58m and ~13h (12h + up to 1h jitter)
    pattern = r"Scheduling service discovery refresh in (11h:5[0-9]m|12h|13h:0m)"
    assert re.search(pattern, caplog.text)

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    # Tick past the maximum possible sleep time (12h + 1h jitter = 13h)
    frozen_time.tick(13 * 3600 + 1)
    await asyncio.sleep(0.1)

    assert cloud.service_discovery._memory_cache is not None
    assert cloud.service_discovery._memory_cache["data"]["version"] == "1.0"

    await cloud.service_discovery.async_stop_service_discovery()

    assert_snapshot_with_logs(
        {
            "cache_populated_after_retry": True,
            "version": "1.0",
        },
        caplog,
        snapshot,
    )


async def test_service_discovery_fetch_without_token_check(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
):
    """Test that service discovery fetch skips token validation."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json=BASE_EXPECTED_RESULT,
    )

    cloud.auth.async_check_token = AsyncMock(
        side_effect=Exception("Token check should not be called!")
    )

    result = await cloud.service_discovery._fetch_well_known_service_discovery()

    assert result["version"] == "1.0"
    assert not cloud.auth.async_check_token.called
