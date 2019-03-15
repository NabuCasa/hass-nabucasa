"""Module to handle messages from Home Assistant cloud."""
import asyncio
import logging
import pprint
import random
import uuid

from aiohttp import WSMsgType, client_exceptions, hdrs

from .auth import Unauthenticated, CloudError
from .const import (
    MESSAGE_AUTH_FAIL,
    MESSAGE_EXPIRATION,
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_DISCONNECTED,
)
from .utils import Registry

HANDLERS = Registry()
_LOGGER = logging.getLogger(__name__)


class UnknownHandler(Exception):
    """Exception raised when trying to handle unknown handler."""


class NotConnected(Exception):
    """Exception raised when trying to handle unknown handler."""


class ErrorMessage(Exception):
    """Exception raised when there was error handling message in the cloud."""

    def __init__(self, error):
        """Initialize Error Message."""
        super().__init__(self, "Error in Cloud")
        self.error = error


class CloudIoT:
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
        # Local code waiting for a response
        self._response_handler = {}
        self._on_connect = []
        self._on_disconnect = []

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
                _LOGGER.exception("Unexpected error")

            if self.state == STATE_CONNECTED and self._on_disconnect:
                try:
                    await asyncio.wait([cb() for cb in self._on_disconnect])
                except Exception:  # pylint: disable=broad-except
                    # Safety net. This should never hit.
                    # Still adding it here to make sure we don't break the flow
                    _LOGGER.exception("Unexpected error in on_disconnect callbacks")

            if self.close_requested:
                break

            self.state = STATE_CONNECTING
            self.tries += 1

            try:
                # Sleep 2^tries + 0…tries*3 seconds between retries
                self.retry_task = self.cloud.run_task(
                    asyncio.sleep(
                        2 ** min(9, self.tries) + random.randint(0, self.tries * 3)
                    )
                )
                await self.retry_task
                self.retry_task = None
            except asyncio.CancelledError:
                # Happens if disconnect called
                break

        self.state = STATE_DISCONNECTED

    async def async_send_message(self, handler, payload, expect_answer=True):
        """Send a message."""
        if self.state != STATE_CONNECTED:
            raise NotConnected

        msgid = uuid.uuid4().hex

        if expect_answer:
            fut = self._response_handler[msgid] = asyncio.Future()

        message = {"msgid": msgid, "handler": handler, "payload": payload}
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Publishing message:\n%s\n", pprint.pformat(message))
        await self.client.send_json(message)

        if expect_answer:
            return await fut

    async def _handle_connection(self):
        """Connect to the IoT broker."""
        try:
            await self.cloud.run_executor(self.cloud.auth.check_token)
        except Unauthenticated as err:
            _LOGGER.error("Unable to refresh token: %s", err)

            self.cloud.client.user_message(
                "cloud_subscription_expired", "Home Assistant Cloud", MESSAGE_AUTH_FAIL
            )

            # Don't await it because it will cancel this task
            self.cloud.run_task(self.cloud.logout())
            return
        except CloudError as err:
            _LOGGER.warning("Unable to refresh token: %s", err)
            return

        if self.cloud.subscription_expired:
            self.cloud.client.user_message(
                "cloud_subscription_expired", "Home Assistant Cloud", MESSAGE_EXPIRATION
            )
            self.close_requested = True
            return

        client = None
        disconnect_warn = None
        try:
            self.client = client = await self.cloud.websession.ws_connect(
                self.cloud.relayer,
                heartbeat=55,
                headers={hdrs.AUTHORIZATION: "Bearer {}".format(self.cloud.id_token)},
            )
            self.tries = 0

            _LOGGER.info("Connected")
            self.state = STATE_CONNECTED

            if self._on_connect:
                try:
                    await asyncio.wait([cb() for cb in self._on_connect])
                except Exception:  # pylint: disable=broad-except
                    # Safety net. This should never hit.
                    # Still adding it here to make sure we don't break the flow
                    _LOGGER.exception("Unexpected error in on_connect callbacks")

            while not client.closed:
                msg = await client.receive()

                if msg.type in (WSMsgType.CLOSED, WSMsgType.CLOSING):
                    break

                elif msg.type == WSMsgType.ERROR:
                    disconnect_warn = "Connection error"
                    break

                elif msg.type != WSMsgType.TEXT:
                    disconnect_warn = "Received non-Text message: {}".format(msg.type)
                    break

                try:
                    msg = msg.json()
                except ValueError:
                    disconnect_warn = "Received invalid JSON."
                    break

                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Received message:\n%s\n", pprint.pformat(msg))

                response_handler = self._response_handler.pop(msg["msgid"], None)

                if response_handler is not None:
                    if "payload" in msg:
                        response_handler.set_result(msg["payload"])
                    else:
                        response_handler.set_exception(ErrorMessage(msg["error"]))
                    continue

                response = {"msgid": msg["msgid"]}
                try:
                    result = await async_handle_message(
                        self.cloud, msg["handler"], msg["payload"]
                    )

                    # No response from handler
                    if result is None:
                        continue

                    response["payload"] = result

                except UnknownHandler:
                    response["error"] = "unknown-handler"

                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Error handling message")
                    response["error"] = "exception"

                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Publishing message:\n%s\n", pprint.pformat(response))
                await client.send_json(response)

        except client_exceptions.WSServerHandshakeError as err:
            if err.status == 401:
                disconnect_warn = "Invalid auth."
                self.close_requested = True
                # Should we notify user?
            else:
                _LOGGER.warning("Unable to connect: %s", err)

        except client_exceptions.ClientError as err:
            _LOGGER.warning("Unable to connect: %s", err)

        finally:
            if disconnect_warn is None:
                _LOGGER.info("Connection closed")
            else:
                _LOGGER.warning("Connection closed: %s", disconnect_warn)

    async def disconnect(self):
        """Disconnect the client."""
        self.close_requested = True

        if self.client is not None:
            await self.client.close()
        elif self.retry_task is not None:
            self.retry_task.cancel()


async def async_handle_message(cloud, handler_name, payload):
    """Handle incoming IoT message."""
    handler = HANDLERS.get(handler_name)

    if handler is None:
        raise UnknownHandler()

    return await handler(cloud, payload)


@HANDLERS.register("alexa")
async def async_handle_alexa(cloud, payload):
    """Handle an incoming IoT message for Alexa."""
    return await cloud.client.async_alexa_message(payload)


@HANDLERS.register("google_actions")
async def async_handle_google_actions(cloud, payload):
    """Handle an incoming IoT message for Google Actions."""
    return await cloud.client.async_google_message(payload)


@HANDLERS.register("cloud")
async def async_handle_cloud(cloud, payload):
    """Handle an incoming IoT message for cloud component."""
    action = payload["action"]

    if action == "logout":
        # Log out of Home Assistant Cloud
        await cloud.logout()
        _LOGGER.error(
            "You have been logged out from Home Assistant cloud: %s", payload["reason"]
        )
    else:
        _LOGGER.warning("Received unknown cloud action: %s", action)


@HANDLERS.register("remote_sni")
async def async_handle_remote_sni(cloud, payload):
    """Handle remote UI requests for cloud."""
    caller_ip = payload["ip_address"]

    await cloud.remote.handle_connection_requests(caller_ip)
    return {"server": cloud.remote.snitun_server}


@HANDLERS.register("webhook")
async def async_handle_webhook(cloud, payload):
    """Handle an incoming IoT message for cloud webhooks."""
    return await cloud.client.async_webhook_message(payload)
