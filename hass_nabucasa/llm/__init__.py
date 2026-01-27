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
    IMAGE_API_TIMEOUT,
    IMAGE_MIME_TYPE,
    RESPONSES_API_TIMEOUT,
    TOKEN_EXP_BUFFER_MINUTES,
    JSONPrimitive,
    LLMConnectionDetails,
    LLMGeneratedData,
    LLMGeneratedImage,
    LLMHandler,
    LLMImageAttachment,
    ResponseInputParam,
    ResponsesAPIResponse,
    ToolChoice,
    ToolParam,
    stream_llm_response_events,
)
from .stream_events import ResponsesAPIStreamEvent

__all__ = [
    "IMAGE_API_TIMEOUT",
    "IMAGE_MIME_TYPE",
    "RESPONSES_API_TIMEOUT",
    "TOKEN_EXP_BUFFER_MINUTES",
    "JSONPrimitive",
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
    "ResponseInputParam",
    "ResponsesAPIResponse",
    "ResponsesAPIStreamEvent",
    "ToolChoice",
    "ToolParam",
    "stream_llm_response_events",
]
