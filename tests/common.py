"""Test the helper method for writing tests."""

from hass_nabucasa.prefs import CloudPreferences


def mock_coro(return_value=None, exception=None):
    """Return a coro that returns a value or raise an exception."""
    return mock_coro_func(return_value, exception)()


def mock_coro_func(return_value=None, exception=None):
    """Return a method to create a coro function that returns a value."""

    @asyncio.coroutine
    def coro(*args, **kwargs):
        """Fake coroutine."""
        if exception:
            raise exception
        return return_value

    return coro
