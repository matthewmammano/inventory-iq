"""Shared Pydantic models used across modules."""

from typing import Literal

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error response payload."""

    status: Literal["error"] = "error"
    message: str


class SuccessResponse(BaseModel):
    """Standard success response payload."""

    status: Literal["success"] = "success"
