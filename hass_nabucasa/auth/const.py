"""Constants for the authentication package."""

from __future__ import annotations

AUTH_CONNECT_TIMEOUT = 5
AUTH_READ_TIMEOUT = 15
AUTH_MAX_ATTEMPTS = 3

# Worst case for a single Cognito round-trip, rounded up.
AUTH_CALL_TIMEOUT = 65

# Logging in performs two sequential round-trips (initiate_auth, then
# respond_to_auth_challenge), so it needs twice the budget.
AUTH_LOGIN_TIMEOUT = AUTH_CALL_TIMEOUT * 2
