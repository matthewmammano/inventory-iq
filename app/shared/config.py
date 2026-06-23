"""Environment configuration via pydantic-settings."""

from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

DEV_DATABASE_URL = "sqlite:///instance/inventory_iq.db"
PROD_REQUIRED_FIELDS = (
    "database_url",
    "secret_key",
    "email_api_url",
    "email_api_key",
    "email_sender_email",
)


class Settings(BaseSettings):
    """All environment variables in one place. Change here -> changes everywhere."""

    model_config = SettingsConfigDict(extra="ignore")

    # APP_ENV is the only environment switch: dev/development or prod/production.
    app_env: Literal["dev", "prod"] = Field(
        default="dev",
    )
    database_url: str = DEV_DATABASE_URL
    secret_key: str = ""

    # Blank email settings are allowed in dev; prod startup rejects blanks below.
    email_api_url: str = ""
    email_api_key: str = ""
    email_sender_email: str = ""
    email_sender_name: str = "Inventory IQ"
    email_timeout_seconds: int = 4

    scheduler_enabled: bool = False
    scheduler_poll_seconds: int = 15
    dev_clock_enabled: bool = False

    contact_phone: str = ""
    port: int = 5000

    @model_validator(mode="before")
    @classmethod
    def normalize_app_env(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values

        env = str(values.get("app_env") or values.get("APP_ENV") or "dev").strip().lower()
        values["app_env"] = {"production": "prod", "development": "dev"}.get(env, env)
        return values

    @model_validator(mode="after")
    def validate_production_config(self) -> "Settings":
        if not self.secret_key:
            raise ValueError("SECRET_KEY must be set")
        if not self.is_prod:
            return self

        # Prevent Railway/prod from silently using local-only placeholders.
        missing = [field.upper() for field in PROD_REQUIRED_FIELDS if not self._prod_value(field)]
        if missing:
            raise ValueError(f"Missing production environment variables: {', '.join(missing)}")
        if self.dev_clock_enabled:
            raise ValueError("DEV_CLOCK_ENABLED must be false in prod")
        return self

    def _prod_value(self, field: str) -> str:
        value = str(getattr(self, field, "") or "")
        if field == "database_url" and value == DEV_DATABASE_URL:
            return ""
        return value

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


settings = Settings()
