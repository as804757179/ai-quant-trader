from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.core.timeutil import now_cn_iso


class APIResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: str = "OK"
    timestamp: str = Field(default_factory=now_cn_iso)
    error_code: str | None = None


def ok(data: Any = None, message: str = "OK") -> APIResponse:
    return APIResponse(success=True, data=data, message=message)


def error(message: str, code: str | None = None, status_code: int = 400) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=APIResponse(success=False, message=message, error_code=code).model_dump(),
    )
