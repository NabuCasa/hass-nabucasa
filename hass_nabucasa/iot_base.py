"""Base class to keep a websocket connection open to a server."""
import asyncio
import logging
import pprint
import random

from aiohttp import WSMsgType, client_exceptions, hdrs

from .auth import CloudError
from .const import (
    MESSAGE_EXPIRATION,
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_DISCONNECTED,
)


class NotConnected(Exception):
    """Exception raised when trying to handle unknown handler."""


class BaseIoT:
    """Class to manage the IoT connection."""

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
        self._on_connect = []
        self._on_disconnect = []
        self._logger = logging.getLogger(self.package_name)

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

    def register_on_connect(self, on_connect_cb):
        """Register an async on_connect callback."""
        self._on_connect.append(on_connect_cb)

    def register_on_disconnect(self, on_disconnect_cb):
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

        while True:
            try:
                await self._handle_connection()
            except Exception:  # pylint: disable=broad-except
                # Safety net. This should never hit.
                # Still adding it here to make sure we can always reconnect
                self._logger.exception("Unexpected error")

            if self.state == STATE_CONNECTED and self._on_disconnect:
                try:
                    await asyncio.wait([cb() for cb in self._on_disconnect])
                except Exception:  # pylint: disable=broad-except
                    # Safety net. This should never hit.
                    # Still adding it here to make sure we don't break the flow
                    self._logger.exception(
                        "Unexpected error in on_disconnect callbacks"
                    )

            if self.close_requested:
                break

            self.state = STATE_CONNECTING
            self.tries += 1

            try:
                await self._wait_retry()
            except asyncio.CancelledError:
                # Happens if disconnect called
                break

        self.state = STATE_DISCONNECTED

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
            self.cloud.auth.async_check_token()
        except CloudError as err:
            self._logger.warning(
                "Cannot connect because unable to refresh token: %s", err
            )
            return

        if self.require_subscription and self.cloud.subscription_expired:
            self.cloud.client.user_message(
                "cloud_subscription_expired", "Home Assistant Cloud", MESSAGE_EXPIRATION
            )
            self.close_requested = True
            return

        client = None
        disconnect_warn = None
        try:
            self.client = client = await self.cloud.websession.ws_connect(
                self.ws_server_url,
                heartbeat=55,
                headers={hdrs.AUTHORIZATION: "Bearer {}".format(self.cloud.id_token)},
            )
            self.tries = 0

            self._logger.info("Connected")
            self.state = STATE_CONNECTED

            if self._on_connect:
                results = await asyncio.gather(*[cb() for cb in self._on_connect])
                for result, callback in zip(results, self._on_connect):
                    if isinstance(result, Exception):
                        self._logger.error(
                            "Unexpected error in on_connect %s",
                            callback,
                            exc_info=result,
                        )

            while not client.closed:
                msg = await client.receive()

                if msg.type in (WSMsgType.CLOSED, WSMsgType.CLOSING):
                    break

                if msg.type == WSMsgType.ERROR:
                    disconnect_warn = "Connection error"
                    break

                if msg.type != WSMsgType.TEXT:
                    disconnect_warn = "Received non-Text message: {}".format(msg.type)
                    break

                try:
                    msg = msg.json()
                except ValueError:
                    disconnect_warn = "Received invalid JSON."
                    break

                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug("Received message:\n%s\n", pprint.pformat(msg))

                self.async_handle_message(msg)

        except client_exceptions.WSServerHandshakeError as err:
            if err.status == 401:
                disconnect_warn = "Invalid auth."
                self.close_requested = True
                # Should we notify user?
            else:
                self._logger.warning("Unable to connect: %s", err)

        except client_exceptions.ClientError as err:
            self._logger.warning("Unable to connect: %s", err)

        finally:
            if disconnect_warn is None:
                self._logger.info("Connection closed")
            else:
                self._logger.warning("Connection closed: %s", disconnect_warn)

    async def disconnect(self):
        """Disconnect the client."""
        self.close_requested = True

        if self.client is not None:
            await self.client.close()
        elif self.retry_task is not None:
            self.retry_task.cancel()