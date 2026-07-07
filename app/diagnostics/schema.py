"""Pydantic schema for client-collected diagnostics reports."""

from pydantic import BaseModel, Field


class ClientDiagnosticsReport(BaseModel):
    """Validated browser/device payload reported by the client for debugging."""

    correlated_request_id: str | None = Field(default=None, max_length=64)
    user_agent: str = Field(max_length=512)
    screen_px: str = Field(max_length=32)
    viewport_px: str = Field(max_length=32)
    pixel_ratio: float = Field(ge=0, le=10)
    color_depth: int = Field(ge=0, le=128)
    touch: bool
    cpu_cores: int | None = Field(default=None, ge=0, le=256)
    memory_gb: float | None = Field(default=None, ge=0, le=1024)
    timezone: str = Field(max_length=64)
    locale: str = Field(max_length=35)
