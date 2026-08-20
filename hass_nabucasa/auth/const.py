"""Constants for the authentication package."""

from __future__ import annotations

DEFAULT_AUTH_TIMEOUT = 30

# Auto-login retry backoff (register + auto-login after confirmation).
AUTO_LOGIN_INITIAL_BACKOFF = 5  # seconds; delay before the first retry
AUTO_LOGIN_MAX_TOTAL_BACKOFF = 86400  # seconds; give up after ~1 day of waiting
