"""Auth-specific constants and enums."""

from typing import Final

from app.shared.validation_types import RESET_PIN_LENGTH

BLACK_HEX: Final[str] = "#000000"
WHITE_HEX: Final[str] = "#ffffff"
RESET_PIN_DIGITS: Final[int] = RESET_PIN_LENGTH
RESET_PIN_TTL_MINUTES: Final[int] = 15
RESET_PIN_MAX_ATTEMPTS: Final[int] = 5
