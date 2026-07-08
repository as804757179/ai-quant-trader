from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class APIResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: str = "OK"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error_code: str | None = None


def ok(data: Any = None, message: str = "OK") -> APIResponse:
    return APIResponse(success=True, data=data, message=message)


def error(message: str, code: str | None = None, status_code: int = 400) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=APIResponse(success=False, message=message, error_code=code).model_dump(),
    )