"""Constants for the hass-nabucasa."""

from __future__ import annotations

from enum import StrEnum

ACCOUNT_URL = "https://account.nabucasa.com/"

CONFIG_DIR = ".cloud"

REQUEST_TIMEOUT = 10

MODE_PROD = "production"
MODE_DEV = "development"

STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"

DISPATCH_CERTIFICATE_STATUS = "certificate_status"
DISPATCH_REMOTE_CONNECT = "remote_connect"
DISPATCH_REMOTE_DISCONNECT = "remote_disconnect"
DISPATCH_REMOTE_BACKEND_UP = "remote_backend_up"
DISPATCH_REMOTE_BACKEND_DOWN = "remote_backend_down"

DEFAULT_SERVERS: dict[str, dict[str, str]] = {
    "production": {
        "account_link": "account-link.nabucasa.com",
        "accounts": "accounts.nabucasa.com",
        "acme": "acme-v02.api.letsencrypt.org",
        "cloudhook": "webhooks-api.nabucasa.com",
        "relayer": "cloud.nabucasa.com",
        "remotestate": "remotestate.nabucasa.com",
        "servicehandlers": "servicehandlers.nabucasa.com",
    },
    "development": {},
}

DEFAULT_VALUES: dict[str, dict[str, str]] = {
    "production": {
        "cognito_client_id": "60i2uvhvbiref2mftj7rgcrt9u",
        "user_pool_id": "us-east-1_87ll5WOP8",
        "region": "us-east-1",
    },
    "development": {},
}

MESSAGE_EXPIRATION = """
It looks like your Home Assistant Cloud subscription has expired. Please check
your [account page](/config/cloud/account) to continue using the service.
"""

MESSAGE_AUTH_FAIL = """
You have been logged out of Home Assistant Cloud because we have been unable
to verify your credentials. Please [log in](/config/cloud) again to continue
using the service.
"""

MESSAGE_REMOTE_READY = """
Your remote access is now available.
You can manage your connectivity on the
[Cloud panel](/config/cloud) or with our [portal](https://account.nabucasa.com/).
"""

MESSAGE_REMOTE_SETUP = """
Unable to create a certificate. We will automatically
retry it and notify you when it's available.
"""

MESSAGE_LOAD_CERTIFICATE_FAILURE = """
Unable to load the certificate. We will automatically
recreate it and notify you when it's available.
"""


class CertificateStatus(StrEnum):
    """Representation of the certificate status."""

    ACME_ACCOUNT_CREATED = "acme_account_created"
    ACME_ACCOUNT_CREATING = "acme_account_creating"
    CERTIFICATE_FINALIZATION_FAILED = "certificate_finalization_failed"
    CERTIFICATE_FINALIZING = "certificate_finalizing"
    CERTIFICATE_LOAD_ERROR = "certificate_load_error"
    CHALLENGE_ANSWER_FAILED = "challenge_answer_failed"
    CHALLENGE_ANSWERED = "challenge_answered"
    CHALLENGE_ANSWERING = "challenge_answering"
    CHALLENGE_CLEANUP = "challenge_cleanup"
    CHALLENGE_CREATED = "challenge_created"
    CHALLENGE_DNS_FAILED = "challenge_dns_failed"
    CHALLENGE_DNS_PROPAGATING = "challenge_dns_propagating"
    CHALLENGE_DNS_UPDATED = "challenge_dns_updated"
    CHALLENGE_DNS_UPDATING = "challenge_dns_updating"
    CHALLENGE_PENDING = "challenge_pending"
    CHALLENGE_UNEXPECTED_ERROR = "challenge_unexpected_error"
    CSR_GENERATING = "csr_generating"
    DOMAIN_VALIDATION_FAILED = "domain_validation_failed"
    ERROR = "error"
    EXPIRED = "expired"
    EXPIRING_SOON = "expiring_soon"
    GENERATING = "generating"
    INITIAL_CERT_ERROR = "initial_cert_error"
    INITIAL_GENERATING = "initial_generating"
    INITIAL_LOADED = "initial_loaded"
    LOADED = "loaded"
    LOADING = "loading"
    NO_CERTIFICATE = "no_certificate"
    READY = "ready"
    RENEWAL_FAILED = "renewal_failed"
    RENEWAL_GENERATING = "renewal_generating"
    RENEWAL_LOADED = "renewal_loaded"
    SSL_CONTEXT_ERROR = "ssl_context_error"
    VALIDATING = "validating"


class SubscriptionReconnectionReason(StrEnum):
    """Subscription reconnection reason."""

    CONNECTION_ERROR = "connection_error"
    NO_SUBSCRIPTION = "no_subscription"
    SUBSCRIPTION_EXPIRED = "subscription_expired"
