"""LLM error hierarchy.

Kept in a separate module to avoid import cycles between the handler and stream
event parsing modules.
"""

from __future__ import annotations

from ..api import CloudApiError


class LLMError(CloudApiError):
    """Base exception for LLM-related errors."""


class LLMRequestError(LLMError):
    """Base error for LLM generation failures."""


class LLMAuthenticationError(LLMRequestError):
    """Raised when LLM authentication fails."""


class LLMRateLimitError(LLMRequestError):
    """Raised when LLM requests are rate limited."""


class LLMServiceError(LLMRequestError):
    """Raised when LLM requests fail due to service issues."""


class LLMResponseError(LLMRequestError):
    """Raised when LLM responses are unexpected."""


class LLMStreamEventError(LLMError):
    """Base error for LLM stream event processing."""


class LLMStreamEventParseError(LLMStreamEventError):
    """Raised when a stream event payload has an unexpected shape."""


__all__ = [
    "LLMAuthenticationError",
    "LLMError",
    "LLMRateLimitError",
    "LLMRequestError",
    "LLMResponseError",
    "LLMServiceError",
    "LLMStreamEventError",
    "LLMStreamEventParseError",
]
