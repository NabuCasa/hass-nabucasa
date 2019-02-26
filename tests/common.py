"""Test the helper method for writing tests."""
from pathlib import Path

from hass_nabucasa.prefs import CloudPreferences
from hass_nabucasa.client import CloudClient


def mock_coro(return_value=None, exception=None):
    """Return a coro that returns a value or raise an exception."""
    return mock_coro_func(return_value, exception)()


def mock_coro_func(return_value=None, exception=None):
    """Return a method to create a coro function that returns a value."""

    async def coro(*args, **kwargs):
        """Fake coroutine."""
        if exception:
            raise exception
        return return_value

    return coro


class TestPreferences(CloudPreferences):
    """Handle cloud preferences."""

    PREF_ENABLE_ALEXA = "enable_alexa"
    PREF_ENABLE_GOOGLE = "enable_google"
    PREF_GOOGLE_ALLOW_UNLOCK = "google_allow_unlock"
    PREF_CLOUDHOOKS = "cloudhooks"

    def __init__(self):
        """Initialize Test preferences."""
        self._prefs = {}

    async def async_initialize(self):
        """Finish initializing the preferences."""
        self._prefs = {
            self.PREF_ENABLE_ALEXA: True,
            self.PREF_ENABLE_GOOGLE: True,
            self.PREF_GOOGLE_ALLOW_UNLOCK: False,
            self.PREF_CLOUDHOOKS: {},
        }

    async def async_update(
        self, *, google_enabled=None, alexa_enabled=None, cloudhooks=None
    ):
        """Update user preferences."""
        for key, value in (
            (self.PREF_ENABLE_GOOGLE, google_enabled),
            (self.PREF_ENABLE_ALEXA, alexa_enabled),
            (self.PREF_CLOUDHOOKS, cloudhooks),
        ):
            if value is not None:
                self._prefs[key] = value

    @property
    def alexa_enabled(self):
        """Return if Alexa is enabled."""
        return self._prefs[self.PREF_ENABLE_ALEXA]

    @property
    def google_enabled(self):
        """Return if Google is enabled."""
        return self._prefs[self.PREF_ENABLE_GOOGLE]

    @property
    def cloudhooks(self):
        """Return the published cloud webhooks."""
        return self._prefs[self.PREF_CLOUDHOOKS]


class TestClient(CloudClient):
    """Interface class for Home Assistant."""

    def __init__(self, loop, websession):
        """Initialize TestClient."""
        self._loop = loop
        self._websession = websession

        self.mock_user = []
        self.mock_alexa = []
        self.mock_google = []
        self.mock_webhooks = []

        self.mock_return = []

    @property
    def base_dir(self):
        """Return path to base dir."""
        Path("/tmp")

    @property
    def loop(self):
        """Return client loop."""
        return self._loop

    @property
    def websession(self):
        """Return client session for aiohttp."""
        raise self._websession

    @property
    def app(self):
        """Return client webinterface aiohttp application."""
        raise NotImplementedError()

    async def async_user_message(
        self, identifier: str, title: str, message: str
    ) -> None:
        """Create a message for user to UI."""
        self.mock_user.append((identifier, title, message))

    async def async_alexa_message(self, payload):
        """process cloud alexa message to client."""
        self.mock_alexa.append(payload)
        return self.mock_return.pop()

    async def async_google_message(self, payload):
        """Process cloud google message to client."""
        self.mock_google.append(payload)
        return self.mock_return.pop()

    async def async_webhook_message(self, payload):
        """Process cloud webhook message to client."""
        self.mock_webhooks.append(payload)
        return self.mock_return.pop()
