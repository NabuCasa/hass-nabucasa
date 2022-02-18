"""Base class to keep a websocket connection open to a server."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import pprint
import random
from typing import Awaitable, Callable, List

from aiohttp import WSMsgType, client_exceptions, hdrs

from .auth import CloudError
from .const import (
    MESSAGE_EXPIRATION,
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_DISCONNECTED,
)
from .utils import gather_callbacks


@dataclasses.dataclass
class DisconnectReason:
    """Disconnect reason."""

    clean: bool
    reason: str


class NotConnected(Exception):
    """Exception raised when trying to handle unknown handler."""


class BaseIoT:
    """Class to manage the IoT connection."""

    mark_connected_after_first_message = False

    def __init__(self, cloud):
        """Initialize the CloudIoT class."""
        self.cloud = cloud
        # The WebSocket client
        self.client = None
        # Scheduled sleep task till next connection retry
        self.retry_task = None
        # Boolean to indicate if we wanted the connection to close
        self.close_requested = False
        # The current number of attempts to connect, impacts wait time
        self.tries = 0
        # Current state of the connection
        self.state = STATE_DISCONNECTED
        self._on_connect: List[Callable[[], Awaitable[None]]] = []
        self._on_disconnect: List[Callable[[], Awaitable[None]]] = []
        self._logger = logging.getLogger(self.package_name)
        self._disconnect_event = None
        self.last_disconnect_reason: DisconnectReason | None = None

    @property
    def package_name(self) -> str:
        """Return package name for logging."""
        raise NotImplementedError

    @property
    def ws_server_url(self) -> str:
        """Server to connect to."""
        raise NotImplementedError

    @property
    def require_subscription(self) -> bool:
        """If the server requires a valid subscription."""
        return True

    def async_handle_message(self, msg) -> None:
        """Handle incoming message.

        Run all async tasks in a wrapper to log appropriately.
        """
        raise NotImplementedError

    # --- Do not override after this line ---

    def register_on_connect(self, on_connect_cb: Callable[[], Awaitable[None]]):
        """Register an async on_connect callback."""
        self._on_connect.append(on_connect_cb)

    def register_on_disconnect(self, on_disconnect_cb: Callable[[], Awaitable[None]]):
        """Register an async on_disconnect callback."""
        self._on_disconnect.append(on_disconnect_cb)

    @property
    def connected(self):
        """Return if we're currently connected."""
        return self.state == STATE_CONNECTED

    async def async_send_json_message(self, message):
        """Send a message.

        Raises NotConnected if client not connected.
        """
        if self.state != STATE_CONNECTED:
            raise NotConnected

        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("Publishing message:\n%s\n", pprint.pformat(message))

        await self.client.send_json(message)

    async def connect(self):
        """Connect to the IoT broker."""
        if self.state != STATE_DISCONNECTED:
            raise RuntimeError("Connect called while not disconnected")

        self.close_requested = False
        self.state = STATE_CONNECTING
        self.tries = 0
        self._disconnect_event = asyncio.Event()

        while True:
            try:
                self._logger.debug("Trying to connect")
                await self._handle_connection()
            except Exception:  # pylint: disable=broad-except
                # Safety net. This should never hit.
                # Still adding it here to make sure we can always reconnect
                self._logger.exception("Unexpected error")

            if self.state == STATE_CONNECTED and self._on_disconnect:
                await gather_callbacks(
                    self._logger, "on_disconnect", self._on_disconnect
                )

            if self.close_requested:
                break

            if self.require_subscription and self.cloud.subscription_expired:
                break

            self.state = STATE_CONNECTING
            self.tries += 1

            try:
                await self._wait_retry()
            except asyncio.CancelledError:
                # Happens if disconnect called
                break

        self.state = STATE_DISCONNECTED
        self._disconnect_event.set()
        self._disconnect_event = None

    async def _wait_retry(self):
        """Wait until it's time till the next retry."""
        # Sleep 2^tries + 0…tries*3 seconds between retries
        self.retry_task = self.cloud.run_task(
            asyncio.sleep(2 ** min(9, self.tries) + random.randint(0, self.tries * 3))
        )
        await self.retry_task
        self.retry_task = None

    async def _handle_connection(self):
        """Connect to the IoT broker."""
        try:
            await self.cloud.auth.async_check_token()
        except CloudError as err:
            self._logger.warning(
                "Cannot connect because unable to refresh token: %s", err
            )
            return

        if self.require_subscription and self.cloud.subscription_expired:
            self._logger.debug("Cloud subscription expired. Cancelling connecting.")
            self.cloud.client.user_message(
                "cloud_subscription_expired", "Home Assistant Cloud", MESSAGE_EXPIRATION
            )
            self.close_requested = True
            return

        client = None
        disconnect_clean = False
        disconnect_reason = None
        try:
            self.client = client = await self.cloud.websession.ws_connect(
                self.ws_server_url,
                headers={hdrs.AUTHORIZATION: f"Bearer {self.cloud.id_token}"},
            )

            if not self.mark_connected_after_first_message:
                await self._connected()

            while not client.closed:
                try:
                    msg = await client.receive(55)
                except asyncio.TimeoutError:
                    await client.ping()
                    continue

                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING):
                    disconnect_clean = self.state == STATE_CONNECTED
                    disconnect_reason = f"Closed by server: {msg.extra} ({msg.data})"
                    break

                # Do this inside the loop because if 2 clients are connected, it can happen that
                # we get connected with valid auth, but then server decides to drop our connection.
                if self.state != STATE_CONNECTED:
                    await self._connected()

                if msg.type == WSMsgType.ERROR:
                    disconnect_reason = "Connection error"
                    break

                if msg.type != WSMsgType.TEXT:
                    disconnect_reason = f"Received non-Text message: {msg.type}"
                    break

                try:
                    msg = msg.json()
                except ValueError:
                    disconnect_reason = "Received invalid JSON."
                    break

                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug("Received message:\n%s\n", pprint.pformat(msg))

                try:
                    self.async_handle_message(msg)
                except Exception:  # pylint: disable=broad-except
                    self._logger.exception("Unexpected error handling %s", msg)

            if client.closed and disconnect_reason is None:
                disconnect_clean = True
                disconnect_reason = "Closed by server: unknown"

        except client_exceptions.WSServerHandshakeError as err:
            if err.status == 401:
                disconnect_reason = "Invalid auth."
                self.close_requested = True
                # Should we notify user?
            else:
                self._logger.warning("Unable to connect: %s", err)

        except client_exceptions.ClientError as err:
            self._logger.warning("Unable to connect: %s", err)

        except asyncio.CancelledError:
            pass

        finally:
            self.last_disconnect_reason = DisconnectReason(
                disconnect_clean, disconnect_reason
            )
            meth = self._logger.info if disconnect_clean else self._logger.warning
            meth("Connection closed: %s", disconnect_reason)

    async def disconnect(self):
        """Disconnect the client."""
        self.close_requested = True

        if self.client is not None:
            await self.client.close()
        elif self.retry_task is not None:
            self.retry_task.cancel()

        if self._disconnect_event is not None:
            await self._disconnect_event.wait()

    async def _connected(self):
        """Handle connected."""
        self.last_disconnect_reason = None
        self.tries = 0
        self.state = STATE_CONNECTED
        self._logger.info("Connected")

        if self._on_connect:
            await gather_callbacks(self._logger, "on_connect", self._on_connect)
