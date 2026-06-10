"""Error helpers for IR Learning Hub."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


class IRLearningHubError(HomeAssistantError):
    """Base exception with a stable error code.

    The ``code`` doubles as the translation key in the ``exceptions`` section
    of ``strings.json`` / ``translations/*.json``. Home Assistant uses
    ``translation_domain`` + ``translation_key`` to show a localized message to
    the user (falling back to English), while ``message`` stays the developer
    facing text used for logs and service responses.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        """Initialize the error."""
        super().__init__(
            message,
            translation_domain=DOMAIN,
            translation_key=code,
            translation_placeholders=placeholders,
        )
        self.code = code
        self.message = message

    def as_response(self) -> dict[str, str]:
        """Return service response compatible error data."""
        return {"error": self.code, "message": self.message}
