"""Module to handle messages from Home Assistant cloud."""
import asyncio
import logging
import pprint
import uuid
import random

from . import iot_base
from .utils import Registry

HANDLERS = Registry()
_LOGGER = logging.getLogger(__name__)


class UnknownHandler(Exception):
    """Exception raised when trying to handle unknown handler."""


class ErrorMessage(Exception):
    """Exception raised when there was error handling message in the cloud."""

    def __init__(self, error):
        """Initialize Error Message."""
        super().__init__(self, "Error in Cloud")
        self.error = error


class CloudIoT(iot_base.BaseIoT):
    """Class to manage the IoT connection."""

    def __init__(self, cloud):
        """Initialize the CloudIoT class."""
        super().__init__(cloud)
        # Local code waiting for a response
        self._response_handler = {}

        # Register start/stop
        cloud.register_on_start(self.start)
        cloud.register_on_stop(self.disconnect)

    @property
    def package_name(self) -> str:
        """Return the package name for logging."""
        return __name__

    @property
    def ws_server_url(self) -> str:
        """Server to connect to."""
        return self.cloud.relayer

    async def start(self) -> None:
        """Start the CloudIoT server."""
        self.cloud.run_task(self.connect())

    async def async_send_message(self, handler, payload, expect_answer=True):
        """Send a message."""
        msgid = uuid.uuid4().hex

        if expect_answer:
            fut = self._response_handler[msgid] = asyncio.Future()

        try:
            await self.async_send_json_message(
                {"msgid": msgid, "handler": handler, "payload": payload}
            )

            if expect_answer:
                return await fut
        finally:
            self._response_handler.pop(msgid, None)

    def async_handle_message(self, msg):
        """Handle a message."""
        response_handler = self._response_handler.get(msg["msgid"])

        if response_handler is not None:
            if "payload" in msg:
                response_handler.set_result(msg["payload"])
            else:
                response_handler.set_exception(ErrorMessage(msg["error"]))
            return

        self.cloud.run_task(self._async_handle_handler_message(msg))

    async def _async_handle_handler_message(self, message):
        """Handle incoming IoT message."""
        response = {"msgid": message["msgid"]}

        try:
            handler = HANDLERS.get(message["handler"])

            if handler is None:
                raise UnknownHandler()

            result = await handler(self.cloud, message["payload"])

            # No response from handler
            if result is None:
                return

            response["payload"] = result

        except UnknownHandler:
            response["error"] = "unknown-handler"

        except Exception:  # pylint: disable=broad-except
            self._logger.exception("Error handling message")
            response["error"] = "exception"

        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("Publishing message:\n%s\n", pprint.pformat(response))

        await self.client.send_json(response)


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
    elif action == "disconnect_remote":
        # Disconect Remote connection
        await cloud.remote.disconnect(clear_snitun_token=True)
    elif action == "evaluate_remote_security":

        async def _reconnect() -> None:
            """Reconnect after a random timeout."""
            await asyncio.sleep(random.randint(60, 7200))
            await cloud.remote.disconnect(clear_snitun_token=True)
            await cloud.remote.connect()

        # Reconnect to remote frontends
        cloud.client.loop.create_task(_reconnect())
    elif action in ("user_notification", "critical_user_notification"):
        # Send user Notification
        cloud.client.user_message(
            "homeassistant_cloud_notification",
            payload["title"],
            payload["message"],
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
