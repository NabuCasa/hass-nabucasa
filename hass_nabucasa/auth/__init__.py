"""Authentication package."""

from __future__ import annotations

from .cognito import (
    AccountNotReady,
    AlreadyLoggedIn,
    AuthTimeoutError,
    CloudConnectionError,
    CloudError,
    CognitoAuth,
    InvalidTotpCode,
    MFARequired,
    PasswordChangeRequired,
    Unauthenticated,
    UnknownError,
    UserExists,
    UserNotConfirmed,
    UserNotFound,
)

__all__ = [
    "AccountNotReady",
    "AlreadyLoggedIn",
    "AuthTimeoutError",
    "CloudConnectionError",
    "CloudError",
    "CognitoAuth",
    "InvalidTotpCode",
    "MFARequired",
    "PasswordChangeRequired",
    "Unauthenticated",
    "UnknownError",
    "UserExists",
    "UserNotConfirmed",
    "UserNotFound",
]
