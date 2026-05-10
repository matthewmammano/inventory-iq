"""Environment configuration via pydantic-settings."""

from datetime import timedelta

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """All environment variables in one place. Change here -> changes everywhere."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    secret_key: str
    debug: bool = False

    mail_server: str = ""
    mail_port: int = 587
    mail_use_tls: bool = True
    mail_username: str = ""
    mail_password: str = ""
    mail_default_sender: str = ""
    mail_timeout_seconds: int = 4

    session_lifetime_days: int = 30
    scheduler_enabled: bool = False
    scheduler_poll_seconds: int = 15
    dev_clock_enabled: bool = False

    contact_phone: str = "(908) 910-5439"
    port: int = 5000

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> object:
        """Handle the deployment value that was breaking app startup."""
        if isinstance(value, str) and value.strip().lower() == "release":
            return False
        return value

    @property
    def session_lifetime(self) -> timedelta:
        """Timedelta form of session_lifetime_days for Flask config."""
        return timedelta(days=self.session_lifetime_days)


settings = Settings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
