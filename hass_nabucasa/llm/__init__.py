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
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionCallOutputItem,
    ResponseImageOutputItem,
    ResponseIncompleteEvent,
    ResponseMessageOutputItem,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseReasoningOutputItem,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseWebSearchCallOutputItem,
    ResponseWebSearchCallSearchingEvent,
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
    "LLMResponseError",
    "LLMServiceError",
    "LLMStreamEventError",
    "LLMStreamEventParseError",
    "ResponseCompletedEvent",
    "ResponseErrorEvent",
    "ResponseFailedEvent",
    "ResponseFunctionCallArgumentsDeltaEvent",
    "ResponseFunctionCallArgumentsDoneEvent",
    "ResponseFunctionCallOutputItem",
    "ResponseImageOutputItem",
    "ResponseIncompleteEvent",
    "ResponseInputParam",
    "ResponseMessageOutputItem",
    "ResponseOutputItemAddedEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseReasoningOutputItem",
    "ResponseReasoningSummaryTextDeltaEvent",
    "ResponseWebSearchCallOutputItem",
    "ResponseWebSearchCallSearchingEvent",
]
