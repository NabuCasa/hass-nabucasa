"""Test the helper method for writing tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
import threading
from typing import Any, Literal
from unittest.mock import Mock

import pytest

from hass_nabucasa.client import CloudClient

FROZEN_NOW_AS_TIMESTAMP = 1537185600  # 2018-09-17 12:00:00 UTC


class MockClient(CloudClient):
    """Interface class for Home Assistant."""

    def __init__(self, base_path, loop, websession) -> None:
        """Initialize MockClient."""
        self._loop = loop
        self._websession = websession
        self._cloudhooks = {}
        self._aiohttp_runner = Mock()
        self.prop_remote_autostart = True

        self.mock_user = []
        self.mock_dispatcher = []
        self.mock_alexa = []
        self.mock_google = []
        self.mock_webhooks = []
        self.mock_system = []
        self.mock_repairs = []
        self.mock_connection_info = []

        self.mock_return = []
        self._base_path = base_path

        self.pref_should_connect = False

    @property
    def base_path(self) -> Path:
        """Return path to base dir."""
        return self._base_path

    @property
    def loop(self):
        """Return client loop."""
        return self._loop

    @property
    def websession(self):
        """Return client session for aiohttp."""
        return self._websession

    @property
    def client_name(self):
        """Return name of the client, this will be used as the user-agent."""
        return "hass-nabucasa/tests"

    @property
    def aiohttp_runner(self):
        """Return client webinterface aiohttp application."""
        return self._aiohttp_runner

    @property
    def cloudhooks(self):
        """Return list of cloudhooks."""
        return self._cloudhooks

    @property
    def remote_autostart(self) -> bool:
        """Return true if we want start a remote connection."""
        return self.prop_remote_autostart

    async def cloud_connected(self):
        """Handle cloud connected."""

    async def cloud_disconnected(self):
        """Handle cloud disconnected."""

    async def cloud_started(self):
        """Handle cloud started."""

    async def cloud_stopped(self):
        """Handle stopping."""

    async def logout_cleanups(self):
        """Need nothing to do."""

    def user_message(self, identifier: str, title: str, message: str) -> None:
        """Create a message for user to UI."""
        if self.loop._thread_id != threading.get_ident():
            raise RuntimeError(
                "`CloudClient.user_message` should be called from the event loop"
            )
        self.mock_user.append((identifier, title, message))

    def dispatcher_message(self, identifier: str, data: Any = None) -> None:
        """Send data to dispatcher."""
        self.mock_dispatcher.append((identifier, data))

    async def async_cloud_connect_update(self, connect: bool) -> None:
        """Process cloud remote message to client."""
        self.pref_should_connect = connect

    async def async_alexa_message(self, payload):
        """Process cloud alexa message to client."""
        self.mock_alexa.append(payload)
        return self.mock_return.pop()

    async def async_google_message(self, payload):
        """Process cloud google message to client."""
        self.mock_google.append(payload)
        return self.mock_return.pop()

    async def async_webhook_message(self, payload):
        """Process cloud webhook message to client."""
        self.mock_webhooks.append(payload)
        return self.mock_return.pop()

    async def async_system_message(self, payload):
        """Process cloud system message to client."""
        self.mock_system.append(payload)
        return self.mock_return.pop()

    async def async_cloud_connection_info(self, payload) -> dict[Any, Any]:
        """Process cloud connection info message to client."""
        self.mock_connection_info.append(payload)
        return self.mock_return.pop()

    async def async_cloudhooks_update(self, data):
        """Update internal cloudhooks data."""
        self._cloudhooks = data

    async def async_create_repair_issue(
        self,
        identifier: str,
        translation_key: str,
        *,
        placeholders: dict[str, str] | None = None,
        severity: Literal["error", "warning"] = "warning",
    ) -> None:
        """Create a repair issue."""
        self.mock_repairs.append(
            {
                "identifier": identifier,
                "translation_key": translation_key,
                "placeholders": placeholders,
                "severity": severity,
            },
        )

    async def async_delete_repair_issue(self, identifier: str) -> None:
        """Delete a repair issue."""
        issue = next(
            (issue for issue in self.mock_repairs if issue["identifier"] == identifier),
            None,
        )
        if issue is not None:
            self.mock_repairs.remove(issue)


class MockAcme:
    """Mock AcmeHandler."""

    def __init__(self) -> None:
        """Initialize MockAcme."""
        self.is_valid = True
        self.call_issue = False
        self.call_reset = False
        self.call_load = False
        self.call_hardening = False
        self.init_args = None

        self.common_name = None
        self.alternative_names = None
        self.expire_date = None
        self.fingerprint = None

        self.email = "test@nabucasa.inc"

    @property
    def domains(self):
        """Return all domains."""
        return self.alternative_names

    def set_false(self):
        """Set certificate as not valid."""
        self.is_valid = False

    @property
    def certificate_available(self) -> bool:
        """Return true if certificate is available."""
        return self.common_name is not None

    @property
    def is_valid_certificate(self) -> bool:
        """Return valid certificate."""
        return self.is_valid

    async def issue_certificate(self):
        """Issue a certificate."""
        self.call_issue = True

    async def reset_acme(self):
        """Issue a certificate."""
        self.call_reset = True

    async def load_certificate(self):
        """Load certificate."""
        self.call_load = True

    async def hardening_files(self):
        """Hardening files."""
        self.call_hardening = True

    def __call__(self, *args, **kwargs) -> MockAcme:
        """Init."""
        self.init_args = args
        self.init_kwargs = kwargs
        return self


class MockSnitun:
    """Mock Snitun client."""

    def __init__(self) -> None:
        """Initialize MockAcme."""
        self.call_start = False
        self.call_stop = False
        self.call_connect = False
        self.call_disconnect = False
        self.init_args = None
        self.connect_args = None
        self.init_kwarg = None
        self.wait_task = asyncio.Event()

        self.start_whitelist = None
        self.start_endpoint_connection_error_callback = None

    @property
    def is_connected(self):
        """Return if it is connected."""
        return self.call_connect and not self.call_disconnect

    def wait(self):
        """Return waitable object."""
        return self.wait_task.wait()

    async def start(
        self,
        whitelist: bool = False,
        endpoint_connection_error_callback: Coroutine[Any, Any, None] | None = None,
    ):
        """Start snitun."""
        self.start_whitelist = whitelist
        self.start_endpoint_connection_error_callback = (
            endpoint_connection_error_callback
        )
        self.call_start = True

    async def stop(self):
        """Stop snitun."""
        self.call_stop = True

    async def connect(
        self,
        token: bytes,
        aes_key: bytes,
        aes_iv: bytes,
        throttling=None,
    ):
        """Connect snitun."""
        self.call_connect = True
        self.connect_args = [token, aes_key, aes_iv, throttling]

    async def disconnect(self):
        """Disconnect snitun."""
        self.wait_task.set()
        self.call_disconnect = True

    def __call__(self, *args, **kwarg) -> MockSnitun:
        """Init."""
        self.init_args = args
        self.init_kwarg = kwarg
        return self


def extract_log_messages(caplog: pytest.LogCaptureFixture) -> str:
    """Extract log messages as string from caplog fixture."""
    return "\n".join(
        [
            f"[{record.levelname}] {record.name}: {record.message}"
            for record in caplog.records
        ]
    )
