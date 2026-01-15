"""LLM handler."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
import io
import json
import logging
from types import SimpleNamespace
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    ParamSpec,
    TypedDict,
    TypeVar,
    cast,
)

from aiohttp import (
    ClientResponse,
    ClientResponseError,
    ClientTimeout,
    ContentTypeError,
    FormData,
)

from hass_nabucasa.exceptions import NabuCasaNotLoggedInError
from hass_nabucasa.utils import utc_from_timestamp, utcnow

from .api import ApiBase, CloudApiError, api_exception_handler

if TYPE_CHECKING:
    from . import Cloud, _ClientT


_LOGGER = logging.getLogger(__name__)

ResponsesAPIResponse = dict[str, Any]
ResponseInputParam = dict[str, Any] | list[Any]
ToolParam = dict[str, Any]
ToolChoice = Literal["auto", "none"] | dict[str, Any]


class LLMError(CloudApiError):
    """Base exception for LLM-related errors."""


class LLMConnectionDetails(TypedDict):
    """LLM connection details from LLM API."""

    token: str
    valid_until: int
    base_url: str
    generate_data_model: str
    generate_image_model: str
    conversation_model: str


class LLMGeneratedData(TypedDict):
    """LLM data generation response."""

    content: str
    role: Literal["assistant", "user"] | None


class LLMGeneratedImage(TypedDict):
    """Normalized LLM image generation response."""

    mime_type: str
    image_data: bytes
    model: str | None
    width: int | None
    height: int | None
    revised_prompt: str | None


class LLMImageAttachment(TypedDict):
    """Image attachment for editing requests."""

    filename: str | None
    mime_type: str | None
    data: bytes


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


IMAGE_MIME_TYPE = "image/png"
TOKEN_EXP_BUFFER_MINUTES = timedelta(minutes=5)
RESPONSES_API_TIMEOUT = 30.0
IMAGE_API_TIMEOUT = 60.0


class ResponsesAPIStreamEvent(SimpleNamespace):
    """Simple namespace with helper to convert back to plain dicts."""

    def to_dict(self) -> dict[str, Any]:
        """Convert the namespace back to a plain dict recursively."""
        return {
            key: _namespace_to_primitive(value) for key, value in self.__dict__.items()
        }


@dataclass
class _ServerSentEvent:
    """Minimal Server-Sent Event container."""

    event: str | None = None
    data: str = ""
    id: str | None = None
    retry: int | None = None


def _namespace_to_primitive(value: Any) -> Any:
    """Convert a namespace to a primitive value."""
    if isinstance(value, ResponsesAPIStreamEvent):
        return value.to_dict()
    if isinstance(value, list):
        return [_namespace_to_primitive(item) for item in value]
    return value


def _build_stream_event(payload: Any) -> Any:
    """Convert a JSON payload into a Responses API stream event object."""
    if isinstance(payload, dict):
        return ResponsesAPIStreamEvent(
            **{key: _build_stream_event(value) for key, value in payload.items()}
        )
    if isinstance(payload, list):
        return [_build_stream_event(item) for item in payload]
    return payload


P = ParamSpec("P")
R = TypeVar("R")


class _SSEDecoder:
    """Decode Server-Sent Events (SSE) lines into events.

    Based on the WHATWG SSE spec.
    """

    def __init__(self) -> None:
        self._event: str | None = None
        self._data: list[str] = []
        self._last_event_id: str | None = None
        self._retry: int | None = None

    def decode(self, line: str) -> _ServerSentEvent | None:
        """Feed a single decoded line (without trailing newline).

        Returns an event when a blank line indicates the end of an SSE event.
        See: https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation
        """
        # Blank line terminates the current event
        if not line:
            if (
                not self._event
                and not self._data
                and not self._last_event_id
                and self._retry is None
            ):
                return None

            sse = _ServerSentEvent(
                event=self._event,
                data="\n".join(self._data),
                id=self._last_event_id,
                retry=self._retry,
            )

            # NOTE: as per the SSE spec, do not reset last_event_id.
            self._event = None
            self._data = []
            self._retry = None
            return sse

        # Comment line
        if line.startswith(":"):
            return None

        fieldname, _, value = line.partition(":")
        if value.startswith(" "):
            value = value.removeprefix(" ")

        if fieldname == "event":
            self._event = value
        elif fieldname == "data":
            self._data.append(value)
        elif fieldname == "id":
            if "\0" not in value:
                self._last_event_id = value
        elif fieldname == "retry":
            with suppress(TypeError, ValueError):
                self._retry = int(value)

        return None


def llm_http_exception_handler(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Convert HTTP/client errors into LLM-specific exceptions."""

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except LLMRequestError:
            raise
        except ClientResponseError as err:
            if err.status == 401:
                raise LLMAuthenticationError("Cloud LLM authentication failed") from err
            if err.status in (429, 503):
                raise LLMRateLimitError("Cloud LLM is rate limited") from err
            raise LLMServiceError("Error talking to Cloud LLM") from err
        except CloudApiError as err:
            raise LLMServiceError("Error talking to Cloud LLM") from err
        except Exception as err:
            _LOGGER.debug("Unexpected error during LLM API call: %s", err)
            raise LLMServiceError("Error talking to Cloud LLM") from err

    return wrapper


async def stream_llm_response_events(
    response: ClientResponse,
) -> AsyncIterator[Any]:
    """Yield response events from the Cloud LLM stream."""
    try:
        decoder = _SSEDecoder()
        while True:
            line_bytes = await response.content.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8").rstrip("\r\n")
            sse = decoder.decode(line)
            if sse is None:
                continue

            data = sse.data
            if not data:
                # Allow keepalive/empty events
                continue

            if data.startswith("[DONE]"):
                break

            try:
                payload = json.loads(data)
            except json.JSONDecodeError as err:
                _LOGGER.error(
                    "Failed to decode Cloud LLM stream event: %s; data=%r",
                    err,
                    data,
                )
                raise LLMResponseError(
                    "There was an error processing the Cloud LLM response"
                ) from err
            yield _build_stream_event(payload)
    finally:
        response.release()


class LLMHandler(ApiBase):
    """Class to handle LLM services."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize LLM services."""
        super().__init__(cloud)
        self._token: str | None = None
        self._base_url: str | None = None
        self._models: dict[str, str | None] = {}
        self._valid_until: datetime | None = None
        self._lock = asyncio.Lock()

    def _validate_token(self) -> bool:
        """Validate token outside of coroutine."""
        # Check subscription and token expiry with buffer
        return self._cloud.valid_subscription and bool(
            self._valid_until
            and utcnow() + TOKEN_EXP_BUFFER_MINUTES < self._valid_until
        )

    @api_exception_handler(LLMAuthenticationError)
    async def _get_connection_details(self) -> LLMConnectionDetails:
        details: LLMConnectionDetails = await self._call_cloud_api(
            action="llm_connection_details",
        )
        return details

    @api_exception_handler(LLMServiceError)
    async def _async_fetch_image_from_url(self, url: str) -> bytes:
        """Fetch image data from a URL asynchronously."""
        async with self._cloud.websession.get(url) as response:
            response.raise_for_status()
            return await response.read()

    async def _update_connection_details(self) -> None:
        """Update connection details."""
        if not self._cloud.valid_subscription:
            raise LLMAuthenticationError("Invalid subscription")

        details: LLMConnectionDetails = await self._get_connection_details()

        self._token = details["token"]
        self._valid_until = utc_from_timestamp(float(details["valid_until"]))
        self._base_url = details["base_url"]
        self._models = {
            "generate_data": details["generate_data_model"],
            "generate_image": details["generate_image_model"],
            "conversation": details["conversation_model"],
        }

    async def async_ensure_token(self) -> None:
        """Ensure the LLM token is valid and available."""
        async with self._lock:
            if not self._cloud.is_logged_in:
                raise NabuCasaNotLoggedInError("User is not logged in")

            if not self._validate_token():
                await self._update_connection_details()

            if not self._token or not self._base_url:
                raise LLMError("Cloud LLM connection details are unavailable")

    @llm_http_exception_handler
    async def _call_llm_api(
        self,
        endpoint: str,
        *,
        method: str = "POST",
        accept: str = "application/json",
        content_type: str | None = "application/json",
        payload: dict[str, Any] | None = None,
        data: Any | None = None,
        include_path_in_log: bool = False,
    ) -> ClientResponse:
        """Call the Cloud LLM API and ensure errors are handled uniformly."""
        if TYPE_CHECKING:
            assert self._base_url is not None

        await self.async_ensure_token()

        url = f"{self._base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
        }
        if content_type:
            headers["Content-Type"] = content_type

        timeout = RESPONSES_API_TIMEOUT
        if "/images" in endpoint:
            timeout = IMAGE_API_TIMEOUT

        response = await self._call_raw_api(
            method=method,
            url=url,
            headers=headers,
            jsondata=payload,
            data=data,
            client_timeout=ClientTimeout(total=timeout),
            include_path_in_log=include_path_in_log,
        )

        if response.status >= 400:
            error_body = await response.text()
            self._do_log_response(response, error_body, include_path_in_log)
            response.raise_for_status()

        return response

    async def _get_response(
        self,
        response: ClientResponse,
        *,
        include_path_in_log: bool = False,
    ) -> dict[str, Any]:
        """Parse a JSON response from the Cloud LLM API."""
        try:
            data = cast("dict[str, Any]", await response.json())
        except (ContentTypeError, json.JSONDecodeError) as err:
            raise LLMResponseError("Invalid JSON response from Cloud LLM") from err

        self._do_log_response(response, data, include_path_in_log)
        return data

    def _build_responses_payload(
        self,
        *,
        model: str,
        messages: str | ResponseInputParam,
        conversation_id: str,
        response_format: dict[str, Any] | None,
        stream: bool,
        tools: Iterable[ToolParam] | None,
        tool_choice: ToolChoice | None,
    ) -> dict[str, Any]:
        """Build the payload for the Responses API."""
        payload: dict[str, Any] = {
            "model": model,
            "input": messages,
            "stream": stream,
            "conversation": conversation_id,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if tools is not None:
            payload["tools"] = list(tools)
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

    @llm_http_exception_handler
    async def _responses_api_call(
        self,
        payload: dict[str, Any],
        *,
        stream: bool,
    ) -> ResponsesAPIResponse | AsyncIterator[ResponsesAPIStreamEvent]:
        """Call the Responses API via HTTP."""
        accept = "text/event-stream" if stream else "application/json"
        response = await self._call_llm_api(
            "responses",
            accept=accept,
            payload=payload,
        )

        if not stream:
            return await self._get_response(response)

        return cast(
            "ResponsesAPIResponse | AsyncIterator[ResponsesAPIStreamEvent]",
            stream_llm_response_events(response),
        )

    async def _extract_response_image_data(
        self,
        response: dict[str, Any],
    ) -> LLMGeneratedImage:
        data = response.get("data")
        if not data or not isinstance(data, list) or len(data) == 0:
            raise LLMResponseError("Unexpected response from Cloud LLM")

        item = data[0]

        url = item.get("url")
        b64 = item.get("b64_json")

        if not b64 and url:
            image_bytes = await self._async_fetch_image_from_url(url)
            b64 = base64.b64encode(image_bytes).decode("utf-8")

        if not b64:
            raise LLMResponseError(
                "Image generation response contains neither url nor b64_json"
            )

        decoded_image = base64.b64decode(b64)

        return LLMGeneratedImage(
            mime_type=IMAGE_MIME_TYPE,
            model=response.get("model"),
            image_data=decoded_image,
            width=item.get("width"),
            height=item.get("height"),
            revised_prompt=item.get("revised_prompt"),
        )

    async def async_generate_data(
        self,
        *,
        messages: str | ResponseInputParam,
        conversation_id: str,
        response_format: dict[str, Any] | None = None,
        stream: bool = False,
        tools: Iterable[ToolParam] | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> ResponsesAPIResponse | AsyncIterator[ResponsesAPIStreamEvent]:
        """Generate structured or free-form LLM data."""
        if TYPE_CHECKING:
            assert self._models["generate_data"] is not None

        payload = self._build_responses_payload(
            model=self._models["generate_data"],
            messages=messages,
            conversation_id=conversation_id,
            response_format=response_format,
            stream=stream,
            tools=tools,
            tool_choice=tool_choice,
        )

        return await self._responses_api_call(
            payload,
            stream=stream,
        )

    async def async_generate_image(
        self,
        *,
        prompt: str,
    ) -> LLMGeneratedImage:
        """Generate an image via Cloud LLM."""
        if TYPE_CHECKING:
            assert self._models["generate_image"] is not None

        payload = {
            "prompt": prompt,
            "model": self._models["generate_image"],
        }

        response = await self._call_llm_api(
            "images/generations",
            payload=payload,
        )
        data = await self._get_response(response)

        return await self._extract_response_image_data(data)

    async def async_edit_image(
        self,
        *,
        prompt: str,
        attachments: list[LLMImageAttachment],
    ) -> LLMGeneratedImage:
        """Edit an image via Cloud LLM."""
        if TYPE_CHECKING:
            assert self._models["generate_image"] is not None

        file_buffers: list[tuple[io.BytesIO, str | None]] = []
        for idx, attachment in enumerate(attachments):
            buffer = io.BytesIO(attachment["data"])
            buffer.name = attachment["filename"] or f"attachment_{idx}"
            file_buffers.append((buffer, attachment["mime_type"]))

        if not file_buffers:
            raise LLMRequestError("No attachments provided for LLM image editing")

        image_buffers: list[tuple[io.BytesIO, str | None]]

        if len(file_buffers) == 1:
            image_buffers = file_buffers
        else:
            # HA doesn't support masks, so we can ignore it here at file_buffers[1]
            image_buffers = [file_buffers[0], *file_buffers[2:]]

        form = FormData()
        for key, value in {
            "prompt": prompt,
            "model": self._models["generate_image"],
        }.items():
            form.add_field(key, str(value))

        for image_buffer, mime_type in image_buffers:
            image_buffer.seek(0)
            form.add_field(
                "image",
                image_buffer,
                filename=getattr(image_buffer, "name", "image.png"),
                content_type=mime_type or IMAGE_MIME_TYPE,
            )

        response = await self._call_llm_api(
            "images/edits",
            content_type=None,
            data=form,
        )
        result = await self._get_response(response)

        return await self._extract_response_image_data(result)

    async def async_process_conversation(
        self,
        *,
        messages: str | ResponseInputParam,
        conversation_id: str,
        response_format: dict[str, Any] | None = None,
        stream: bool = False,
        tools: Iterable[ToolParam] | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> ResponsesAPIResponse | AsyncIterator[ResponsesAPIStreamEvent]:
        """Generate a response for a conversation."""
        if TYPE_CHECKING:
            assert self._models["conversation"] is not None
        payload = self._build_responses_payload(
            model=self._models["conversation"],
            messages=messages,
            conversation_id=conversation_id,
            response_format=response_format,
            stream=stream,
            tools=tools,
            tool_choice=tool_choice,
        )

        return await self._responses_api_call(
            payload,
            stream=stream,
        )
