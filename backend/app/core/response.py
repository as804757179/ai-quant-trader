from __future__ import annotations

from typing import Any, NoReturn

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_bound_context, new_request_id
from app.core.timeutil import now_cn_iso


CONTRACT_VERSION = "2026-07-16"


class APIResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: str = "OK"
    timestamp: str = Field(default_factory=now_cn_iso)
    error_code: str | None = None
    request_id: str = Field(default_factory=new_request_id)
    contract_version: str = CONTRACT_VERSION
    retryable: bool | None = None
    field_errors: list[dict[str, str]] | None = None


class APIProblem(Exception):
    def __init__(
        self,
        message: str,
        code: str | None = None,
        status_code: int = 400,
        *,
        retryable: bool = False,
        field_errors: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or "BAD_REQUEST"
        self.status_code = status_code
        self.retryable = retryable
        self.field_errors = field_errors
        self.headers = headers


def _request_id(request: Request | None = None) -> str:
    if request is not None:
        value = getattr(request.state, "request_id", None)
        if isinstance(value, str) and value:
            return value
        header_value = request.headers.get("X-Request-ID")
        if header_value:
            return header_value[:128]
    context_value = get_bound_context().get("request_id")
    return str(context_value) if context_value else new_request_id()


def ok(data: Any = None, message: str = "OK") -> APIResponse:
    return APIResponse(success=True, data=data, message=message, request_id=_request_id())


def error(
    message: str,
    code: str | None = None,
    status_code: int = 400,
    *,
    retryable: bool = False,
    field_errors: list[dict[str, str]] | None = None,
) -> NoReturn:
    raise APIProblem(
        message,
        code,
        status_code,
        retryable=retryable,
        field_errors=field_errors,
    )


def problem_response(
    request: Request,
    *,
    message: str,
    code: str,
    status_code: int,
    retryable: bool = False,
    field_errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = {"X-Request-ID": request_id}
    if headers:
        response_headers.update(headers)
    payload = APIResponse(
        success=False,
        data=None,
        message=message,
        error_code=code,
        request_id=request_id,
        retryable=retryable,
        field_errors=field_errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=response_headers,
    )


_HTTP_MESSAGES = {
    400: ("请求不符合接口要求", "BAD_REQUEST"),
    401: ("未认证或认证已失效", "UNAUTHORIZED"),
    403: ("当前主体没有执行此操作的权限", "FORBIDDEN"),
    404: ("请求的资源不存在", "NOT_FOUND"),
    409: ("请求与当前资源状态冲突", "CONFLICT"),
    422: ("请求参数校验失败", "VALIDATION_ERROR"),
    429: ("请求过于频繁，请稍后重试", "RATE_LIMITED"),
    502: ("上游服务暂时不可用", "UPSTREAM_UNAVAILABLE"),
    503: ("服务暂时不可用", "SERVICE_UNAVAILABLE"),
}


def _http_problem(exc: StarletteHTTPException) -> tuple[str, str, bool]:
    message, code = _HTTP_MESSAGES.get(
        exc.status_code,
        ("请求处理失败", "HTTP_ERROR"),
    )
    if isinstance(exc.detail, dict):
        detail_message = exc.detail.get("message")
        detail_code = exc.detail.get("error_code")
        if isinstance(detail_message, str) and detail_message:
            message = detail_message
        if isinstance(detail_code, str) and detail_code:
            code = detail_code
    return message, code, exc.status_code in {429, 502, 503}


def _validation_field_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for item in exc.errors():
        location = item.get("loc", ())
        field = ".".join(str(part) for part in location if part != "body") or "request"
        fields.append(
            {
                "field": field,
                "message": str(item.get("msg") or "invalid value"),
                "type": str(item.get("type") or "validation_error"),
            }
        )
    return fields


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIProblem)
    async def api_problem_handler(request: Request, exc: APIProblem) -> JSONResponse:
        message = exc.message
        if exc.status_code >= 500:
            message = _HTTP_MESSAGES.get(
                exc.status_code,
                ("服务暂时不可用", "SERVICE_UNAVAILABLE"),
            )[0]
        return problem_response(
            request,
            message=message,
            code=exc.code,
            status_code=exc.status_code,
            retryable=exc.retryable,
            field_errors=exc.field_errors,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return problem_response(
            request,
            message="请求参数校验失败",
            code="VALIDATION_ERROR",
            status_code=422,
            field_errors=_validation_field_errors(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        message, code, retryable = _http_problem(exc)
        return problem_response(
            request,
            message=message,
            code=code,
            status_code=exc.status_code,
            retryable=retryable,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return problem_response(
            request,
            message="服务内部错误",
            code="INTERNAL_ERROR",
            status_code=500,
        )
