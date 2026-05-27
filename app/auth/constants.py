"""Auth-specific constants and enums."""

from typing import Final

BLACK_HEX: Final[str] = "#000000"
WHITE_HEX: Final[str] = "#ffffff"
RESET_PIN_DIGITS: Final[int] = 6
RESET_PIN_TTL_MINUTES: Final[int] = 15
RESET_PIN_MAX_ATTEMPTS: Final[int] = 5
PASSWORD_MIN_LENGTH: Final[int] = 10
PASSWORD_REQUIREMENTS_MESSAGE: Final[str] = (
    "Password must be at least 10 characters and include a letter, number, and symbol."
)
