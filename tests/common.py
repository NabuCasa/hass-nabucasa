"""Test the helper method for writing tests."""

from hass_nabucasa.prefs import CloudPreferences


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
        self,
        *,
        google_enabled=None,
        alexa_enabled=None,
        google_allow_unlock=None,
        cloudhooks=None
    ):
        """Update user preferences."""
        for key, value in (
            (self.PREF_ENABLE_GOOGLE, google_enabled),
            (self.PREF_ENABLE_ALEXA, alexa_enabled),
            (self.PREF_GOOGLE_ALLOW_UNLOCK, google_allow_unlock),
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
    def google_allow_unlock(self):
        """Return if Google is allowed to unlock locks."""
        return self._prefs[self.PREF_GOOGLE_ALLOW_UNLOCK]

    @property
    def cloudhooks(self):
        """Return the published cloud webhooks."""
        return self._prefs[self.PREF_CLOUDHOOKS]
