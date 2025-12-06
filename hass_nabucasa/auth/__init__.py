"""Authentication package."""

from __future__ import annotations

from .cognito import (
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
