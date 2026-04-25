"""Exceptions for the Blink Charging client."""

from __future__ import annotations


class BlinkChargingError(Exception):
    """Base exception."""


class BlinkChargingAuthError(BlinkChargingError):
    """Raised when authentication fails (bad creds, expired refresh token, etc.)."""


class BlinkChargingAPIError(BlinkChargingError):
    """Raised when an API call returns an error status or error envelope."""

    def __init__(
        self, message: str, *, status_code: int | None = None, errorcode: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errorcode = errorcode
