"""Test the base API module."""

from __future__ import annotations

import pytest

from hass_nabucasa.api import (
    CloudApiError,
    CloudApiNonRetryableError,
    api_exception_handler,
)


class CustomException(CloudApiError):
    """Custom exception for testing."""


@pytest.mark.parametrize(
    "exception,expected",
    [
        (CloudApiError("Oh no!"), CloudApiError),
        (CloudApiNonRetryableError("Oh no!", code="616"), CloudApiNonRetryableError),
        (CustomException("Oh no!"), CustomException),
        (KeyError("stt"), CustomException),
    ],
)
async def test_raising_exception(exception, expected) -> None:
    """Test raising a custom exception."""

    @api_exception_handler(CustomException)
    async def mock_func() -> None:
        raise exception

    with pytest.raises(expected):
        await mock_func()
