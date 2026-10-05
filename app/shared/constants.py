"""Global constants and enums used across modules."""

from typing import Final

ADMIN_TIMEOUT: Final[int] = 2 * 60 * 60  # 2 hours
IDLE_TIMEOUT: Final[int] = 60 * 60  # 1 hour
IDLE_WARNING_SECONDS: Final[int] = 10
SAVE_RETRY_MESSAGE: Final[str] = "Changes could not be saved. Review entries and try again."
