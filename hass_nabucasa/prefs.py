"""Preference management for cloud."""


class CloudPreferences:
    """Handle cloud preferences."""

    async def async_initialize(self):
        """Finish initializing the preferences."""
        raise NotImplementedError()

    async def async_update(
        self,
        *,
        google_enabled=None,
        alexa_enabled=None,
        google_allow_unlock=None,
        cloudhooks=None
    ):
        """Update user preferences."""
        raise NotImplementedError()

    @property
    def alexa_enabled(self):
        """Return if Alexa is enabled."""
        raise NotImplementedError()

    @property
    def google_enabled(self):
        """Return if Google is enabled."""
        raise NotImplementedError()

    @property
    def google_allow_unlock(self):
        """Return if Google is allowed to unlock locks."""
        raise NotImplementedError()

    @property
    def cloudhooks(self):
        """Return the published cloud webhooks."""
        raise NotImplementedError()
