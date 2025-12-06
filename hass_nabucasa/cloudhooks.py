"""Manage cloud cloudhooks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

import async_timeout

from .api import ApiBase, CloudApiError, api_exception_handler
from .events.types import CloudhookCreatedEvent, CloudhookDeletedEvent

if TYPE_CHECKING:
    from . import Cloud, _ClientT


class CloudhookDetails(TypedDict):
    """Details of a cloudhook."""

    webhook_id: str
    cloudhook_id: str
    cloudhook_url: str
    managed: bool


class GeneratedCloudhookDetails(TypedDict):
    """Details of a generated cloudhook."""

    url: str
    cloudhook_id: str


class CloudhookApiError(CloudApiError):
    """Error raised when a cloudhook API call fails."""


class Cloudhooks(ApiBase):
    """Class to help manage cloudhooks."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize cloudhooks."""
        super().__init__(cloud)
        cloud.iot.register_on_connect(self.async_publish_cloudhooks)

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.servicehandlers_server is not None
        return self._cloud.servicehandlers_server

    async def async_publish_cloudhooks(self) -> None:
        """Inform the Relayer of the cloudhooks that we support."""
        if not self._cloud.is_connected:
            return

        cloudhooks = self._cloud.client.cloudhooks
        await self._cloud.iot.async_send_message(
            "webhook-register",
            {"cloudhook_ids": [info["cloudhook_id"] for info in cloudhooks.values()]},
            expect_answer=False,
        )

    async def async_create(self, webhook_id: str, managed: bool) -> CloudhookDetails:
        """Create a cloud webhook."""
        cloudhooks = self._cloud.client.cloudhooks

        if webhook_id in cloudhooks:
            raise ValueError("Hook is already enabled for the cloud.")

        if not self._cloud.iot.connected:
            raise ValueError("Cloud is not connected")

        # Create cloud hook
        async with async_timeout.timeout(10):
            data = await self.generate()

        cloudhook_id = data["cloudhook_id"]
        cloudhook_url = data["url"]

        # Store hook
        cloudhooks_updated: dict[str, Any] = dict(cloudhooks)
        cloudhook: CloudhookDetails = {
            "webhook_id": webhook_id,
            "cloudhook_id": cloudhook_id,
            "cloudhook_url": cloudhook_url,
            "managed": managed,
        }
        cloudhooks_updated[webhook_id] = cloudhook
        await self._cloud.client.async_cloudhooks_update(cloudhooks_updated)

        await self.async_publish_cloudhooks()
        await self._cloud.events.publish(CloudhookCreatedEvent(cloudhook=cloudhook))
        return cloudhook

    async def async_delete(self, webhook_id: str) -> None:
        """Delete a cloud webhook."""
        cloudhooks = self._cloud.client.cloudhooks

        if webhook_id not in cloudhooks:
            raise ValueError("Hook is not enabled for the cloud.")

        # Remove hook
        cloudhooks_updated: dict[str, Any] = dict(cloudhooks)
        cloudhook: CloudhookDetails = cloudhooks_updated.pop(webhook_id)
        await self._cloud.client.async_cloudhooks_update(cloudhooks_updated)

        await self._cloud.events.publish(CloudhookDeletedEvent(cloudhook=cloudhook))
        await self.async_publish_cloudhooks()

    @api_exception_handler(CloudhookApiError)
    async def generate(self) -> GeneratedCloudhookDetails:
        """Get generated cloudhook details."""
        details: GeneratedCloudhookDetails = await self._call_cloud_api(
            path="/instance/webhook",
        )
        return details
