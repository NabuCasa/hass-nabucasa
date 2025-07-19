"""Custom base exceptions for the Nabu Casa integration."""

from __future__ import annotations


class NabuCasaBaseError(Exception):
    """Base class for all Nabu Casa exceptions."""


class NabuCasaConnectionError(NabuCasaBaseError):
    """Base class for all Nabu Casa connection exceptions."""


class NabuCasaAuthenticationError(NabuCasaBaseError):
    """Base class for all Nabu Casa authentication exceptions."""


class CloudError(NabuCasaBaseError):
    """
    Base class for all Nabu Casa cloud exceptions.

    Kept for compatibility with existing code.
    """
