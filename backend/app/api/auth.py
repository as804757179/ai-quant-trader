from fastapi import APIRouter, Request, Response

from app.core.auth import AuthFailure, get_request_principal
from app.core.config import settings
from app.core.response import APIResponse, error, ok


router = APIRouter()


def _raise_auth_failure(exc: AuthFailure) -> None:
    error(
        exc.message,
        exc.code,
        exc.status_code,
        retryable=exc.retryable,
    )


@router.post("/session", response_model=APIResponse)
async def create_session(request: Request, response: Response):
    principal = get_request_principal(request)
    service = request.state.auth_service
    try:
        issue = await service.issue_session(principal, request)
    except AuthFailure as exc:
        _raise_auth_failure(exc)
    response.set_cookie(
        key=settings.API_SESSION_COOKIE_NAME,
        value=issue.session_token,
        max_age=settings.API_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.is_production(),
        samesite="lax",
        path="/",
    )
    return ok(
        {
            "principal": principal.public_payload(),
            "csrf_token": issue.csrf_token,
            "expires_at": issue.expires_at.isoformat(),
        },
        message="会话已创建",
    )


@router.get("/me", response_model=APIResponse)
async def get_current_session(request: Request):
    return ok({"principal": get_request_principal(request).public_payload()})


@router.delete("/session", response_model=APIResponse)
async def delete_session(request: Request, response: Response):
    principal = get_request_principal(request)
    service = request.state.auth_service
    try:
        revoked = await service.revoke_session(principal, request)
    except AuthFailure as exc:
        _raise_auth_failure(exc)
    response.delete_cookie(
        key=settings.API_SESSION_COOKIE_NAME,
        secure=settings.is_production(),
        samesite="lax",
        path="/",
    )
    return ok({"revoked": revoked}, message="会话已注销")
