"""LLM package.

This package contains the Cloud LLM handler and related stream event models.
It replaces the historical `hass_nabucasa.llm` module (now a package).
"""

from __future__ import annotations

from .errors import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMRequestError,
    LLMResponseError,
    LLMServiceError,
    LLMStreamEventError,
    LLMStreamEventParseError,
)
from .handler import (
    LLMConnectionDetails,
    LLMGeneratedData,
    LLMGeneratedImage,
    LLMHandler,
    LLMImageAttachment,
    ResponseInputParam,
)
from .stream_events import (
    LLMResponseCompletedEvent,
    LLMResponseErrorEvent,
    LLMResponseFailedEvent,
    LLMResponseFunctionCallArgumentsDeltaEvent,
    LLMResponseFunctionCallArgumentsDoneEvent,
    LLMResponseFunctionCallOutputItem,
    LLMResponseImageOutputItem,
    LLMResponseIncompleteEvent,
    LLMResponseMessageOutputItem,
    LLMResponseOutputItemAddedEvent,
    LLMResponseOutputItemDoneEvent,
    LLMResponseOutputTextDeltaEvent,
    LLMResponseReasoningOutputItem,
    LLMResponseReasoningSummaryTextDeltaEvent,
    LLMResponseWebSearchCallOutputItem,
    LLMResponseWebSearchCallSearchingEvent,
)

__all__ = [
    "LLMAuthenticationError",
    "LLMConnectionDetails",
    "LLMError",
    "LLMGeneratedData",
    "LLMGeneratedImage",
    "LLMHandler",
    "LLMImageAttachment",
    "LLMRateLimitError",
    "LLMRequestError",
    "LLMResponseCompletedEvent",
    "LLMResponseError",
    "LLMResponseErrorEvent",
    "LLMResponseFailedEvent",
    "LLMResponseFunctionCallArgumentsDeltaEvent",
    "LLMResponseFunctionCallArgumentsDoneEvent",
    "LLMResponseFunctionCallOutputItem",
    "LLMResponseImageOutputItem",
    "LLMResponseIncompleteEvent",
    "LLMResponseMessageOutputItem",
    "LLMResponseOutputItemAddedEvent",
    "LLMResponseOutputItemDoneEvent",
    "LLMResponseOutputTextDeltaEvent",
    "LLMResponseReasoningOutputItem",
    "LLMResponseReasoningSummaryTextDeltaEvent",
    "LLMResponseWebSearchCallOutputItem",
    "LLMResponseWebSearchCallSearchingEvent",
    "LLMServiceError",
    "LLMStreamEventError",
    "LLMStreamEventParseError",
    "ResponseInputParam",
]
