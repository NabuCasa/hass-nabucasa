"""LLM handler."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Iterable
from datetime import datetime, timedelta
import io
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypedDict,
    cast,
)

from litellm import (
    BaseResponsesAPIStreamingIterator,
    ResponseInputParam,
    ResponsesAPIResponse,
    ToolChoice,
    ToolParam,
    aimage_edit,
    aimage_generation,
    aresponses,
)
from litellm.exceptions import (
    APIError,
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
)

from hass_nabucasa.exceptions import NabuCasaNotLoggedInError
from hass_nabucasa.utils import utc_from_timestamp, utcnow

from .api import ApiBase, CloudApiError, api_exception_handler

if TYPE_CHECKING:
    from . import Cloud, _ClientT


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


class LLMHandler(ApiBase):
    """Class to handle LLM services."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize LLM services."""
        super().__init__(cloud)
        self._token: str | None = None
        self._base_url: str | None = None
        self._generate_data_model: str | None = None
        self._generate_image_model: str | None = None
        self._conversation_model: str | None = None
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

    async def _update_connection_details(self) -> None:
        """Update connection details."""
        if not self._cloud.valid_subscription:
            raise LLMAuthenticationError("Invalid subscription")

        details: LLMConnectionDetails = await self._get_connection_details()

        self._token = details["token"]
        self._valid_until = utc_from_timestamp(float(details["valid_until"]))
        self._base_url = details["base_url"]
        self._generate_data_model = details["generate_data_model"]
        self._generate_image_model = details["generate_image_model"]
        self._conversation_model = details["conversation_model"]

    async def async_ensure_token(self) -> None:
        """Ensure the LLM token is valid and available."""
        async with self._lock:
            if not self._cloud.is_logged_in:
                raise NabuCasaNotLoggedInError("User is not logged in")

            if not self._validate_token():
                await self._update_connection_details()

            if not self._token or not self._base_url:
                raise LLMError("Cloud LLM connection details are unavailable")

    async def async_generate_data(
        self,
        *,
        messages: str | ResponseInputParam,
        conversation_id: str,
        response_format: dict[str, Any] | None = None,
        stream: bool = False,
        tools: Iterable[ToolParam] | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> ResponsesAPIResponse | BaseResponsesAPIStreamingIterator:
        """Generate structured or free-form LLM data."""
        await self.async_ensure_token()

        if TYPE_CHECKING:
            assert self._generate_data_model is not None

        try:
            response = await aresponses(
                model=self._generate_data_model,
                input=messages,
                api_key=self._token,
                api_base=self._base_url,
                user=conversation_id,
                stream=stream,
                text_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                custom_llm_provider="litellm_proxy",
            )
            return cast(
                "ResponsesAPIResponse | BaseResponsesAPIStreamingIterator", response
            )
        except AuthenticationError as err:
            raise LLMAuthenticationError("Cloud LLM authentication failed") from err
        except (RateLimitError, ServiceUnavailableError) as err:
            raise LLMRateLimitError("Cloud LLM is rate limited") from err
        except APIError as err:
            raise LLMServiceError("Error talking to Cloud LLM") from err
        except Exception as err:
            raise LLMServiceError(
                "Unexpected error during LLM data generation"
            ) from err

    async def async_generate_image(
        self,
        *,
        prompt: str,
    ) -> LLMGeneratedImage:
        """Generate an image via Cloud LLM."""
        await self.async_ensure_token()

        try:
            response = await aimage_generation(
                prompt=prompt,
                api_key=self._token,
                api_base=self._base_url,
                model=self._generate_image_model,
                custom_llm_provider="litellm_proxy",
            )

        except AuthenticationError as err:
            raise LLMAuthenticationError("Cloud LLM authentication failed") from err
        except (RateLimitError, ServiceUnavailableError) as err:
            raise LLMRateLimitError("Cloud LLM is rate limited") from err
        except APIError as err:
            raise LLMServiceError("Error talking to Cloud LLM") from err
        except Exception as err:
            raise LLMServiceError(
                "Unexpected error during LLM image generation"
            ) from err
        return await self._extract_response_image_data(response)

    async def async_edit_image(
        self,
        *,
        prompt: str,
        attachments: list[LLMImageAttachment],
    ) -> LLMGeneratedImage:
        """Edit an image via Cloud LLM."""
        await self.async_ensure_token()

        image_payload: Any
        mask_payload: Any | None = None

        if TYPE_CHECKING:
            assert self._generate_image_model is not None

        file_buffers: list[io.BytesIO] = []
        for idx, attachment in enumerate(attachments):
            buffer = io.BytesIO(attachment["data"])
            buffer.name = attachment["filename"] or f"attachment_{idx}"
            file_buffers.append(buffer)

        if len(file_buffers) == 1:
            image_payload = file_buffers[0]
        else:
            mask_payload = file_buffers[1]
            remaining = [file_buffers[0], *file_buffers[2:]]
            image_payload = remaining if len(remaining) > 1 else remaining[0]

        try:
            response = await aimage_edit(
                image=image_payload,
                prompt=prompt,
                model=self._generate_image_model,
                mask=mask_payload,
                api_key=self._token,
                api_base=self._base_url,
                custom_llm_provider="litellm_proxy",
            )

        except AuthenticationError as err:
            raise LLMAuthenticationError("Cloud LLM authentication failed") from err
        except (RateLimitError, ServiceUnavailableError) as err:
            raise LLMRateLimitError("Cloud LLM is rate limited") from err
        except APIError as err:
            raise LLMServiceError("Error talking to Cloud LLM") from err
        except Exception as err:
            raise LLMServiceError("Unexpected error during LLM image editing") from err

        return await self._extract_response_image_data(response)

    async def async_process_conversation(
        self,
        *,
        messages: str | ResponseInputParam,
        conversation_id: str,
        response_format: dict[str, Any] | None = None,
        stream: bool = False,
        tools: Iterable[ToolParam] | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> ResponsesAPIResponse | BaseResponsesAPIStreamingIterator:
        """Generate a response for a conversation."""
        await self.async_ensure_token()

        if TYPE_CHECKING:
            assert self._conversation_model is not None

        try:
            response = await aresponses(
                model=self._conversation_model,
                input=messages,
                api_key=self._token,
                api_base=self._base_url,
                user=conversation_id,
                stream=stream,
                text_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                custom_llm_provider="litellm_proxy",
            )

            return cast(
                "ResponsesAPIResponse | BaseResponsesAPIStreamingIterator", response
            )
        except AuthenticationError as err:
            raise LLMAuthenticationError("Cloud LLM authentication failed") from err
        except (RateLimitError, ServiceUnavailableError) as err:
            raise LLMRateLimitError("Cloud LLM is rate limited") from err
        except APIError as err:
            raise LLMServiceError("Error talking to Cloud LLM") from err
        except Exception as err:
            raise LLMServiceError(
                "Unexpected error during LLM conversation processing"
            ) from err
