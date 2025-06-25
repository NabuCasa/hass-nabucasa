"""Manage cloud cloudhooks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

import async_timeout

from .api import ApiBase, CloudApiError, api_exception_handler

if TYPE_CHECKING:
    from . import Cloud, _ClientT


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
            assert self._cloud.cloudhook_server is not None
        return self._cloud.cloudhook_server

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

    async def async_create(self, webhook_id: str, managed: bool) -> dict[str, Any]:
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
        cloudhooks = dict(cloudhooks)
        hook = cloudhooks[webhook_id] = {
            "webhook_id": webhook_id,
            "cloudhook_id": cloudhook_id,
            "cloudhook_url": cloudhook_url,
            "managed": managed,
        }
        await self._cloud.client.async_cloudhooks_update(cloudhooks)

        await self.async_publish_cloudhooks()
        return hook

    async def async_delete(self, webhook_id: str) -> None:
        """Delete a cloud webhook."""
        cloudhooks = self._cloud.client.cloudhooks

        if webhook_id not in cloudhooks:
            raise ValueError("Hook is not enabled for the cloud.")

        # Remove hook
        cloudhooks = dict(cloudhooks)
        cloudhooks.pop(webhook_id)
        await self._cloud.client.async_cloudhooks_update(cloudhooks)

        await self.async_publish_cloudhooks()

    @api_exception_handler(CloudhookApiError)
    async def generate(self) -> GeneratedCloudhookDetails:
        """Get the voice connection details."""
        details: GeneratedCloudhookDetails = await self._call_cloud_api(
            method="POST",
            path="/generate",
        )
        return details
