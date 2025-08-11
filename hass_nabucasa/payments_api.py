"""This module provides Payments API functionalities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

from .api import ApiBase, CloudApiError, api_exception_handler

_LOGGER = logging.getLogger(__name__)


class PaymentsApiError(CloudApiError):
    """Exception raised when handling payments API."""


class BillingInformation(TypedDict):
    """Billing information from payments API."""

    address: dict[str, str | None]
    name: str


class Subscription(TypedDict):
    """Subscription data from payments API."""

    status: str | None
    trial_end: int | None
    cancel_at_period_end: bool | None
    canceled_at: int | None
    current_period_end: int | None


class SubscriptionInfo(TypedDict):
    """Subscription information from payments API."""

    amount: float
    automatic_tax: bool
    billing_information: BillingInformation
    billing_plan_type: str
    country: str
    currency: str
    customer_exists: bool
    delete_requested: bool
    email: str
    human_description: str
    plan_renewal_date: int | None
    provider: str | None
    renewal_active: bool
    source: dict[str, str | int | None] | None
    subscription: Subscription | None
    tax: float


class MigratePaypalAgreementInfo(TypedDict):
    """Migration information from payments API."""

    url: str


class PaymentsApi(ApiBase):
    """Class to help communicate with the payments API."""

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.accounts_server is not None
        return self._cloud.accounts_server

    @api_exception_handler(PaymentsApiError)
    async def subscription_info(self, skip_renew: bool = False) -> SubscriptionInfo:
        """Get the subscription information."""
        info: SubscriptionInfo = await self._call_cloud_api(
            path="/payments/subscription_info",
        )

        # If subscription info indicates we are subscribed, force a refresh of the token
        if info.get("provider") and not self._cloud.started and not skip_renew:
            _LOGGER.debug(
                "Found disconnected account with valid subscription, connecting"
            )
            await self._cloud.auth.async_renew_access_token()

        return info

    @api_exception_handler(PaymentsApiError)
    async def migrate_paypal_agreement(self) -> MigratePaypalAgreementInfo:
        """Migrate a PayPal agreement to the new system."""
        response: MigratePaypalAgreementInfo = await self._call_cloud_api(
            path="/payments/migrate_paypal_agreement",
            method="POST",
        )
        return response
