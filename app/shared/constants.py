"""Global constants and enums used across modules."""

from typing import Final

ADMIN_TIMEOUT: Final[int] = 2 * 60 * 60  # 2 hours


MAX_RETRIES: Final[int] = 3
RETRY_WAIT_SECONDS: Final[int] = 1
RETRY_BACKOFF_MULTIPLIER: Final[int] = 2
REQUEST_TIMEOUT_SECONDS: Final[int] = 10
