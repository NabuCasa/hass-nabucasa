"""Aiohttp test utils."""

from contextlib import contextmanager
import json as _json
import re
from types import TracebackType
from typing import Self
from unittest import mock
from urllib.parse import parse_qs

from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientResponseError
from aiohttp.streams import StreamReader
import pytest
from yarl import URL

retype = type(re.compile(""))


def mock_stream(data):
    """Mock a stream with data."""
    protocol = mock.Mock(_reading_paused=False)
    stream = StreamReader(protocol)
    stream.feed_data(data)
    stream.feed_eof()
    return stream


class AiohttpClientMocker:
    """Mock Aiohttp client requests."""

    def __init__(self) -> None:
        """Initialize the request mocker."""
        self._mocks = []
        self._cookies = {}
        self.mock_calls = []

    def request(
        self,
        method,
        url,
        *,
        auth=None,
        status=200,
        text=None,
        data=None,
        content=None,
        json=None,
        params=None,
        headers=None,
        exc=None,
        cookies=None,
    ):
        """Mock a request."""
        if json is not None:
            text = _json.dumps(json)
        if text is not None:
            content = text.encode("utf-8")
        if content is None:
            content = b""

        if not isinstance(url, retype):
            url = URL(url)
        if params:
            url = url.with_query(params)

        self._mocks.append(
            AiohttpClientMockResponse(
                method,
                url,
                status,
                content,
                cookies,
                exc,
                headers or {},
            ),
        )

    def get(self, *args, **kwargs):
        """Register a mock get request."""
        self.request("get", *args, **kwargs)

    def put(self, *args, **kwargs):
        """Register a mock put request."""
        self.request("put", *args, **kwargs)

    def post(self, *args, **kwargs):
        """Register a mock post request."""
        self.request("post", *args, **kwargs)

    def delete(self, *args, **kwargs):
        """Register a mock delete request."""
        self.request("delete", *args, **kwargs)

    def options(self, *args, **kwargs):
        """Register a mock options request."""
        self.request("options", *args, **kwargs)

    @property
    def call_count(self):
        """Return the number of requests made."""
        return len(self.mock_calls)

    def clear_requests(self):
        """Reset mock calls."""
        self._mocks.clear()
        self._cookies.clear()
        self.mock_calls.clear()

    def create_session(self, loop):
        """Create a ClientSession that is bound to this mocker."""
        session = ClientSession(loop=loop)
        # Setting directly on `session` will raise deprecation warning
        object.__setattr__(session, "_request", self.match_request)
        return session

    async def match_request(
        self,
        method,
        url,
        *,
        data=None,
        auth=None,
        params=None,
        headers=None,
        allow_redirects=None,
        timeout=None,
        json=None,
        expect100=None,
        chunked=None,
    ):
        """Match a request against pre-registered requests."""
        data = data or json
        url = URL(url)
        if params:
            url = url.with_query(params)

        for response in self._mocks:
            if response.match_request(method, url, params):
                self.mock_calls.append((method, url, data, headers))

                if response.exc:
                    raise response.exc
                return response

        pytest.fail(f"No mock registered for {method.upper()} {url} {params}")


class AiohttpClientMockResponse:
    """Mock Aiohttp client response."""

    def __init__(
        self,
        method,
        url,
        status,
        response,
        cookies=None,
        exc=None,
        headers=None,
    ) -> None:
        """Initialize a fake response."""
        self.method = method
        self._url = url
        self.status = status
        self.response = response
        self.exc = exc

        self._headers = headers or {}
        self._cookies = {}

        if cookies:
            for name, data in cookies.items():
                cookie = mock.MagicMock()
                cookie.value = data
                self._cookies[name] = cookie

    def match_request(self, method, url, params=None):
        """Test if response answers request."""
        if method.lower() != self.method.lower():
            return False

        # regular expression matching
        if isinstance(self._url, retype):
            return self._url.search(str(url)) is not None

        if (
            self._url.scheme != url.scheme
            or self._url.host != url.host
            or self._url.path != url.path
        ):
            return False

        # Ensure all query components in matcher are present in the request
        request_qs = parse_qs(url.query_string)
        matcher_qs = parse_qs(self._url.query_string)
        for key, vals in matcher_qs.items():
            for val in vals:
                try:
                    request_qs.get(key, []).remove(val)
                except ValueError:
                    return False

        return True

    @property
    def headers(self):
        """Return content_type."""
        return self._headers

    @property
    def cookies(self):
        """Return dict of cookies."""
        return self._cookies

    @property
    def url(self):
        """Return yarl of URL."""
        return self._url

    @property
    def content_type(self):
        """Return yarl of URL."""
        return self._headers.get("content-type")

    @property
    def content(self):
        """Return content."""
        return mock_stream(self.response)

    async def read(self):
        """Return mock response."""
        return self.response

    async def text(self, encoding="utf-8"):
        """Return mock response as a string."""
        return self.response.decode(encoding)

    async def json(self, encoding="utf-8"):
        """Return mock response as a json."""
        return _json.loads(self.response.decode(encoding))

    def release(self):
        """Mock release."""

    def raise_for_status(self):
        """Raise error if status is 400 or higher."""
        if self.status >= 400:
            raise ClientResponseError(
                None,
                None,
                status=self.status,
                headers=self.headers,
            )

    def close(self):
        """Mock close."""

    async def wait_for_close(self):
        """Mock wait_for_close."""

    async def __aenter__(self) -> Self:
        """Enter the context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the context manager."""


@contextmanager
def mock_aiohttp_client(loop):
    """Context manager to mock aiohttp client."""
    mocker = AiohttpClientMocker()

    with mock.patch(
        "hass_nabucasa.Cloud.websession",
        new_callable=mock.PropertyMock,
    ) as mock_websession:
        session = mocker.create_session(loop)
        mock_websession.return_value = session
        yield mocker
