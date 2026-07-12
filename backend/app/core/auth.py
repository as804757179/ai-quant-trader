"""简易 API Key 鉴权。"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings

# 无需鉴权的路径前缀
PUBLIC_PATH_PREFIXES = (
    "/api/v1/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def is_public_path(path: str) -> bool:
    if path in ("/", "/favicon.ico"):
        return True
    for prefix in PUBLIC_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    # WebSocket 握手另议；HTTP 升级路径放行由 WS 层处理
    if path.startswith("/ws"):
        return True
    return False


def extract_api_key(request: Request) -> str | None:
    header_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if header_key:
        return header_key.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def api_key_middleware(request: Request, call_next):
    """
    当 settings.API_KEY 非空时，对非公开路径强制校验 X-API-Key / Bearer。
    为空时跳过（兼容本地开发与现有测试）。
    """
    if not settings.API_KEY:
        return await call_next(request)

    if is_public_path(request.url.path):
        return await call_next(request)

    provided = extract_api_key(request)
    if not provided or provided != settings.API_KEY:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "未授权：请提供有效的 X-API-Key",
                "error_code": "UNAUTHORIZED",
            },
        )
    return await call_next(request)
