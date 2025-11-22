"""AI Task handler."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta
import io
import logging
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast

import aiohttp
from litellm import (
    BaseResponsesAPIStreamingIterator,
    ResponsesAPIResponse,
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

from hass_nabucasa.utils import utc_from_timestamp, utcnow

from .api import ApiBase, CloudApiError, api_exception_handler

if TYPE_CHECKING:
    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)


class AiError(CloudApiError):
    """Error with token handling."""


class AiConnectionDetails(TypedDict):
    """AI connection details from AI API."""

    token: str
    valid_until: int
    base_url: str
    generate_data_model: str
    generate_image_model: str
    conversation_model: str


class AiGeneratedData(TypedDict):
    """AI data generation response."""

    role: NotRequired[Literal["assistant", "user"]]
    content: str


class AiGeneratedImage(TypedDict):
    """Normalized AI image generation response."""

    mime_type: str
    image_data: bytes
    model: str | None
    width: int | None
    height: int | None
    revised_prompt: str | None


class AiImageAttachment(TypedDict):
    """Image attachment for editing requests."""

    filename: str | None
    mime_type: str | None
    data: bytes


class AiRequestError(AiError):
    """Base error for AI generation failures."""


class AiAuthenticationError(AiRequestError):
    """Raised when AI authentication fails."""


class AiRateLimitError(AiRequestError):
    """Raised when AI requests are rate limited."""


class AiServiceError(AiRequestError):
    """Raised when AI requests fail due to service issues."""


class AiResponseError(AiRequestError):
    """Raised when AI responses are unexpected."""


@api_exception_handler(AiServiceError)
async def _async_fetch_image_from_url(url: str) -> bytes:
    """Fetch image data from a URL asynchronously."""
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        response.raise_for_status()
        return await response.read()


@api_exception_handler(AiServiceError)
async def _extract_response_image_data(
    response: dict[str, Any],
) -> AiGeneratedImage:
    data = response.get("data")
    if not data or not isinstance(data, list):
        raise AiResponseError("Unexpected response from Cloud AI")

    item = data[0]

    url = item.get("url")
    b64 = item.get("b64_json")

    if not b64 and url:
        image_bytes = await _async_fetch_image_from_url(url)
        b64 = base64.b64encode(image_bytes).decode("utf-8")

    if not b64:
        raise ValueError("Image generation response contains neither url nor b64_json.")

    decoded_image = base64.b64decode(b64)

    return AiGeneratedImage(
        mime_type="image/png",
        model=response.get("model"),
        image_data=decoded_image,
        width=item.get("width"),
        height=item.get("height"),
        revised_prompt=item.get("revised_prompt"),
    )


class Ai(ApiBase):
    """Class to handle AI services."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize AI services."""
        super().__init__(cloud)
        self._token: str | None = None
        self.base_url: str | None = None
        self._generate_data_model: str | None = None
        self._generate_image_model: str | None = None
        self._conversation_model: str | None = None
        self._valid_until: datetime | None = None
        self._lock = asyncio.Lock()

    def _validate_token(self) -> bool:
        """Validate token outside of coroutine."""
        # Add a 5-minute buffer to avoid race conditions near expiry
        return self._cloud.valid_subscription and bool(
            self._valid_until and utcnow() + timedelta(minutes=5) < self._valid_until
        )

    @api_exception_handler(AiAuthenticationError)
    async def _get_connection_details(self) -> AiConnectionDetails:
        details: AiConnectionDetails = await self._call_cloud_api(
            action="ai_connection_details",
        )
        return details

    async def _update_token(self) -> None:
        """Update token details."""
        if not self._cloud.valid_subscription:
            raise AiAuthenticationError("Invalid subscription")

        details: AiConnectionDetails = await self._get_connection_details()

        self._token = details["token"]
        self._valid_until = utc_from_timestamp(float(details["valid_until"]))
        self.base_url = details["base_url"]
        self._generate_data_model = details["generate_data_model"]
        self._generate_image_model = details["generate_image_model"]
        self._conversation_model = details["conversation_model"]

    async def async_ensure_token(self) -> None:
        """Ensure the AI token is valid and available."""
        async with self._lock:
            if not self._validate_token():
                await self._update_token()

            if not self._token or not self.base_url:
                raise AiError("Cloud AI connection details are unavailable")

    async def async_generate_data(
        self,
        *,
        messages: list[dict[str, Any]],
        conversation_id: str,
        response_format: dict[str, Any] | None = None,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Literal["auto", "none", "required"] | dict[str, Any] | None = None,
    ) -> ResponsesAPIResponse | BaseResponsesAPIStreamingIterator:
        """Generate structured or free-form AI data."""
        await self.async_ensure_token()

        response_kwargs: dict[str, Any] = {
            "model": self._generate_data_model,
            "input": messages,
            "api_key": self._token,
            "api_base": self.base_url,
            "user": conversation_id,
            "stream": stream,
            "response_format": response_format,
            "tools": tools,
            "tool_choice": tool_choice,
        }

        try:
            response = await aresponses(**response_kwargs)
            return cast(
                "ResponsesAPIResponse | BaseResponsesAPIStreamingIterator", response
            )
        except AuthenticationError as err:
            raise AiAuthenticationError("Cloud AI authentication failed") from err
        except (RateLimitError, ServiceUnavailableError) as err:
            raise AiRateLimitError("Cloud AI is rate limited") from err
        except APIError as err:
            raise AiServiceError("Error talking to Cloud AI") from err

    async def async_generate_image(
        self,
        *,
        prompt: str,
        attachments: list[AiImageAttachment] | None = None,
    ) -> AiGeneratedImage:
        """Generate or edit an image via Cloud AI."""
        await self.async_ensure_token()

        try:
            if attachments:
                return await self._async_edit_image(prompt, attachments)
            return await self._async_create_image(prompt)
        except AuthenticationError as err:
            raise AiAuthenticationError("Cloud AI authentication failed") from err
        except (RateLimitError, ServiceUnavailableError) as err:
            raise AiRateLimitError("Cloud AI is rate limited") from err
        except APIError as err:
            raise AiServiceError("Error talking to Cloud AI") from err

    async def _async_create_image(self, prompt: str) -> AiGeneratedImage:
        response = await aimage_generation(
            prompt=prompt,
            api_key=self._token,
            api_base=self.base_url,
            model=self._generate_image_model,
        )

        return await _extract_response_image_data(response)

    async def _async_edit_image(
        self, prompt: str, attachments: list[AiImageAttachment]
    ) -> AiGeneratedImage:
        if not self._generate_image_model:
            raise AiServiceError("Image editing model is not configured")

        file_buffers: list[io.BytesIO] = []
        for idx, attachment in enumerate(attachments):
            buffer = io.BytesIO(attachment["data"])
            buffer.name = attachment["filename"] or f"attachment_{idx}"
            file_buffers.append(buffer)

        image_payload: Any
        mask_payload: Any | None = None
        if len(file_buffers) == 1:
            image_payload = file_buffers[0]
        else:
            mask_payload = file_buffers[1]
            remaining = [file_buffers[0], *file_buffers[2:]]
            image_payload = remaining if len(remaining) > 1 else remaining[0]

        response = await aimage_edit(
            image=image_payload,
            prompt=prompt,
            model=self._generate_image_model,
            mask=mask_payload,
            api_key=self._token,
            api_base=self.base_url,
        )

        return await _extract_response_image_data(response)

    async def async_process_conversation(
        self,
        *,
        messages: list[dict[str, Any]],
        conversation_id: str,
        response_format: dict[str, Any] | None = None,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Literal["auto", "none", "required"] | dict[str, Any] | None = None,
    ) -> ResponsesAPIResponse | BaseResponsesAPIStreamingIterator:
        """Generate structured or free-form AI data."""
        await self.async_ensure_token()

        response_kwargs: dict[str, Any] = {
            "model": self._conversation_model,
            "input": messages,
            "api_key": self._token,
            "api_base": self.base_url,
            "user": conversation_id,
            "stream": stream,
            "response_format": response_format,
            "tools": tools,
            "tool_choice": tool_choice,
        }

        try:
            response = await aresponses(**response_kwargs)
            return cast(
                "ResponsesAPIResponse | BaseResponsesAPIStreamingIterator", response
            )
        except AuthenticationError as err:
            raise AiAuthenticationError("Cloud AI authentication failed") from err
        except (RateLimitError, ServiceUnavailableError) as err:
            raise AiRateLimitError("Cloud AI is rate limited") from err
        except APIError as err:
            raise AiServiceError("Error talking to Cloud AI") from err
