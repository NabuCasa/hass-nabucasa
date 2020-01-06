"""Module to handle Google Report State."""
import asyncio
from asyncio.queues import Queue
import logging
from typing import Dict
import uuid

from . import iot_base

_LOGGER = logging.getLogger(__name__)
MAX_PENDING = 100

ERR_DISCARD_CODE = "message_discarded"
ERR_DISCARD_MSG = "Message discarded because max messages reachced"


class ErrorResponse(Exception):
    """Raised when a request receives a success=false response."""

    def __init__(self, code: str, message: str):
        """Initialize error response."""
        super().__init__(code)
        self.code = code
        self.message = message


class GoogleReportState(iot_base.BaseIoT):
    """Report states to Google.

    Uses a queue to send messages.
    """

    def __init__(self, cloud):
        """Initialize Google Report State."""
        super().__init__(cloud)
        self._connect_lock = asyncio.Lock()
        self._to_send = Queue(100)
        self._message_sender_task = None
        # Local code waiting for a response
        self._response_handler: Dict[str, asyncio.Future] = {}
        self.register_on_connect(self._async_on_connect)
        self.register_on_disconnect(self._async_on_disconnect)

        # Register start/stop
        cloud.register_on_stop(self.disconnect)

    @property
    def package_name(self) -> str:
        """Return the package name for logging."""
        return __name__

    @property
    def ws_server_url(self) -> str:
        """Server to connect to."""
        # https -> wss, http -> ws
        return f"ws{self.cloud.google_actions_report_state_url[4:]}/v1"

    async def async_send_message(self, msg):
        """Send a message."""
        msgid = uuid.uuid4().hex

        # Since connect is async, guard against send_message called twice in parallel.
        async with self._connect_lock:
            if self.state == iot_base.STATE_DISCONNECTED:
                self.cloud.run_task(self.connect())
                # Give connect time to start up and change state.
                await asyncio.sleep(0)

        if self._to_send.full():
            discard_msg = self._to_send.get_nowait()
            self._response_handler.pop(discard_msg["msgid"]).set_exception(
                ErrorResponse(ERR_DISCARD_CODE, ERR_DISCARD_MSG)
            )

        fut = self._response_handler[msgid] = asyncio.Future()

        self._to_send.put_nowait({"msgid": msgid, "payload": msg})

        try:
            return await fut
        finally:
            self._response_handler.pop(msgid, None)

    def async_handle_message(self, msg):
        """Handle a message."""
        response_handler = self._response_handler.get(msg["msgid"])

        if response_handler is not None:
            if "error" in msg:
                response_handler.set_exception(
                    ErrorResponse(msg["error"], msg["message"])
                )
            else:
                response_handler.set_result(msg.get("payload"))
            return

        self._logger.warning("Got unhandled message: %s", msg)

    async def _async_on_connect(self):
        """On Connect handler."""
        self._message_sender_task = self.cloud.run_task(self._async_message_sender())

    async def _async_on_disconnect(self):
        """On disconnect handler."""
        self._message_sender_task.cancel()
        self._message_sender_task = None

    async def _async_message_sender(self):
        """Start sending messages."""
        self._logger.debug("Message sender task activated")
        try:
            while True:
                await self.async_send_json_message(await self._to_send.get())
        except asyncio.CancelledError:
            pass
        self._logger.debug("Message sender task shut down")
