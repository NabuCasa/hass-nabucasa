"""Manage accounts API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .api import ApiBase, CloudApiError, api_exception_handler


class AccountsApiError(CloudApiError):
    """Exception raised when handling account API."""


class AccountsApi(ApiBase):
    """Class to help communicate with the accounts API."""

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.accounts_server is not None
        return self._cloud.accounts_server

    @api_exception_handler(AccountsApiError)
    async def instance_resolve_dns_cname(self, *, hostname: str) -> list[str]:
        """Resolve DNS CNAME."""
        details: list[str] = await self._call_cloud_api(
            method="POST",
            path="/instance/resolve_dns_cname",
            jsondata={"hostname": hostname},
        )
        return details
