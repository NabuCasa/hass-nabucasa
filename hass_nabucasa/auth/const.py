"""Constants for the authentication package."""

from __future__ import annotations

AUTH_CONNECT_TIMEOUT = 5

# Requests started by the user are single-use or send an email, so they are sent
# once. The read timeout leaves room for Cognito's Lambda triggers.
AUTH_USER_READ_TIMEOUT = 30
AUTH_USER_TIMEOUT = 100

AUTH_RENEW_READ_TIMEOUT = 15
AUTH_RENEW_MAX_ATTEMPTS = 3
AUTH_RENEW_TIMEOUT = 90
