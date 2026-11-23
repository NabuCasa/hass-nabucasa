"""Module to handle Google Report State."""

from __future__ import annotations

import asyncio
from asyncio.queues import Queue
from typing import TYPE_CHECKING, Any
import uuid

from aiohttp import ClientError, ClientResponse, ClientTimeout

from . import iot_base
from .api import ApiBase, CloudApiError, CloudApiRawResponse, api_exception_handler

if TYPE_CHECKING:
    from . import Cloud, _ClientT

MAX_PENDING = 100
MESSAGE_TIMEOUT = 15

ERR_DISCARD_CODE = "message_discarded"
ERR_DISCARD_MSG = "Message discarded because max messages reachced"
ERR_DISCONNECTED_CODE = "disconnected"
ERR_DISCONNECTED_MSG = "Connection lost before a response was received"
ERR_TIMEOUT_CODE = "timeout"
ERR_TIMEOUT_MSG = "No response received in time"


class GoogleReportStateError(CloudApiError):
    """Exception raised when handling Google Report State API calls."""


class ErrorResponse(Exception):
    """Raised when a request receives a success=false response."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize error response."""
        super().__init__(code)
        self.code = code
        self.message = message


class GoogleReportState(iot_base.BaseIoT, ApiBase):
    """Report states to Google.

    Uses a queue to send messages.
    """

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize Google Report State."""
        # Initialize both parent classes explicitly
        iot_base.BaseIoT.__init__(self, cloud)
        ApiBase.__init__(self, cloud)

        self._connect_lock = asyncio.Lock()
        self._to_send: Queue[dict[str, Any]] = Queue(100)
        self._message_sender_task: asyncio.Task | None = None
        # Local code waiting for a response
        self._response_handler: dict[str, asyncio.Future[None]] = {}
        # Messages written to the websocket that are waiting for a response
        self._in_flight: set[str] = set()
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
        return self.cloud.service_discovery.action_url("google_report_state_websocket")

    async def async_send_message(self, msg: Any) -> None:
        """Send a message."""
        msgid: str = uuid.uuid4().hex

        # Since connect is async, guard against send_message called twice in parallel.
        async with self._connect_lock:
            if self.state == iot_base.STATE_DISCONNECTED:
                asyncio.create_task(self.connect())
                # Give connect time to start up and change state.
                await asyncio.sleep(0)

        if self._to_send.full():
            discard_msg = self._to_send.get_nowait()
            self._fail_message(discard_msg["msgid"], ERR_DISCARD_CODE, ERR_DISCARD_MSG)

        fut = self._response_handler[msgid] = asyncio.Future()

        self._to_send.put_nowait({"msgid": msgid, "payload": msg})

        try:
            async with asyncio.timeout(MESSAGE_TIMEOUT):
                return await fut
        except TimeoutError:
            raise ErrorResponse(ERR_TIMEOUT_CODE, ERR_TIMEOUT_MSG) from None
        finally:
            self._response_handler.pop(msgid, None)
            self._in_flight.discard(msgid)

    def _fail_message(self, msgid: str, code: str, message: str) -> None:
        """Fail the future of a message if its caller is still waiting."""
        fut = self._response_handler.get(msgid)
        if fut is not None and not fut.done():
            fut.set_exception(ErrorResponse(code, message))

    def async_handle_message(self, msg: dict[str, Any]) -> None:
        """Handle a message."""
        self._in_flight.discard(msg["msgid"])
        response_handler = self._response_handler.get(msg["msgid"])

        if response_handler is not None:
            if "error" in msg:
                response_handler.set_exception(
                    ErrorResponse(msg["error"], msg["message"]),
                )
            else:
                response_handler.set_result(msg.get("payload"))
            return

        self._logger.warning("Unhandled message received: %s", msg)

    async def _async_on_connect(self) -> None:
        """On Connect handler."""
        self._message_sender_task = asyncio.create_task(self._async_message_sender())

    async def _async_on_disconnect(self) -> None:
        """On disconnect handler."""
        if self._message_sender_task is not None:
            self._message_sender_task.cancel()
            self._message_sender_task = None

        for msgid in self._in_flight:
            self._fail_message(msgid, ERR_DISCONNECTED_CODE, ERR_DISCONNECTED_MSG)
        self._in_flight.clear()

    async def _async_message_sender(self) -> None:
        """Start sending messages."""
        self._logger.debug("Message sender task activated")
        try:
            while True:
                message = await self._to_send.get()
                msgid = message["msgid"]
                if msgid not in self._response_handler:
                    continue

                self._in_flight.add(msgid)
                try:
                    await self.async_send_json_message(message)
                except (
                    iot_base.NotConnected,
                    ClientError,
                    ConnectionResetError,
                ) as err:
                    self._logger.debug("Unable to send message: %r", err)
                    self._in_flight.discard(msgid)
                    self._fail_message(
                        msgid, ERR_DISCONNECTED_CODE, ERR_DISCONNECTED_MSG
                    )
                    if self.client is not None:
                        await self.client.close()
                    break
        except asyncio.CancelledError:
            pass
        self._logger.debug("Message sender task shut down")

    @api_exception_handler(GoogleReportStateError)
    async def request_sync(self) -> ClientResponse:
        """Request a Google Actions sync request."""
        resp: CloudApiRawResponse = await self._call_cloud_api(
            method="POST",
            action="google_report_state_request_sync",
            raw_response=True,
            client_timeout=ClientTimeout(total=300),
        )
        return resp.response
