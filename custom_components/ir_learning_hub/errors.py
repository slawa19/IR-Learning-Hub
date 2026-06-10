"""Error helpers for IR Learning Hub."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


class IRLearningHubError(HomeAssistantError):
    """Base exception with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize the error."""
        super().__init__(message)
        self.code = code
        self.message = message

    def as_response(self) -> dict[str, str]:
        """Return service response compatible error data."""
        return {"error": self.code, "message": self.message}
