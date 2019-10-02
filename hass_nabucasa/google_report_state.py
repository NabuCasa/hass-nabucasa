"""Module to handle Google Report State."""
import asyncio
from asyncio.queues import Queue
import logging

from . import iot_base

_LOGGER = logging.getLogger(__name__)
MAX_PENDING = 100


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
        self.register_on_connect(self._async_on_connect)
        self.register_on_disconnect(self._async_on_disconnect)

    @property
    def package_name(self) -> str:
        """Return the package name for logging."""
        return __name__

    @property
    def ws_server_url(self) -> str:
        """Server to connect to."""
        return self.cloud.google_actions_report_state_url

    async def async_send_message(self, msg):
        """Send a message."""
        # Since connect is async, guard against send_message called twice in parallel.
        async with self._connect_lock:
            if self.state == iot_base.STATE_DISCONNECTED:
                self.cloud.run_task(self.connect())
                # Give connect time to start up and change state.
                await asyncio.sleep(0)

        if self._to_send.qsize() == MAX_PENDING:
            self._to_send.get_nowait()
            self._to_send.task_done()

        self._to_send.put_nowait(msg)

    def async_handle_message(self, msg):
        """Handle a message."""
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
        try:
            while True:
                await self.async_send_json_message(await self._to_send.get())
        except asyncio.CancelledError:
            pass
