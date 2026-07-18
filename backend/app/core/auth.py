"""Principal, credential, session, and route-scope enforcement."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocket

from app.core.config import settings
from app.core.logging import get_logger
from app.core.response import problem_response
from app.db import get_db


logger = get_logger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

KNOWN_SCOPES = frozenset(
    {
        "market:read",
        "market:operate",
        "market:stream",
        "ai:read",
        "ai:run",
        "ai:stream",
        "screener:read",
        "screener:run",
        "strategy:read",
        "strategy:write",
        "strategy:approve",
        "backtest:read",
        "backtest:run",
        "backtest:execute",
        "jobs:read",
        "jobs:cancel",
        "jobs:execute",
        "risk:read",
        "risk:fuse.activate",
        "risk:fuse.recover",
        "risk:precheck",
        "risk:stream",
        "trade:read",
        "trade:approval.request",
        "trade:approval.approve",
        "trade:order.create",
        "trade:order.cancel",
        "trade:simulation.operate",
        "trade:broker.sync",
        "trade:reconcile",
        "portfolio:read",
        "portfolio:stream",
        "research:read",
        "research:review.append",
        "system:docs.read",
        "system:metrics.read",
        "system:notify.test",
        "system:readiness.read",
    }
)

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "viewer": frozenset(
        {
            "market:read",
            "ai:read",
            "screener:read",
            "research:read",
            "market:stream",
            "ai:stream",
        }
    ),
    "data_operator": frozenset(
        {"market:read", "market:operate", "market:stream", "jobs:read", "jobs:cancel"}
    ),
    "research_reviewer": frozenset({"research:read", "research:review.append"}),
    "strategy_admin": frozenset(
        {
            "market:read",
            "ai:read",
            "ai:run",
            "ai:stream",
            "screener:read",
            "screener:run",
            "strategy:read",
            "strategy:write",
            "backtest:read",
            "backtest:run",
            "jobs:read",
            "jobs:cancel",
            "research:read",
        }
    ),
    "risk_admin": frozenset(
        {
            "market:read",
            "risk:read",
            "risk:fuse.activate",
            "risk:fuse.recover",
            "risk:precheck",
            "risk:stream",
            "strategy:approve",
            "trade:read",
            "trade:approval.request",
            "trade:approval.approve",
            "portfolio:read",
            "portfolio:stream",
        }
    ),
    "trader": frozenset(
        {
            "market:read",
            "market:stream",
            "ai:read",
            "ai:stream",
            "risk:read",
            "risk:precheck",
            "risk:stream",
            "trade:read",
            "trade:approval.request",
            "trade:order.create",
            "trade:order.cancel",
            "portfolio:read",
            "portfolio:stream",
        }
    ),
    "auditor": frozenset(
        {
            "market:read",
            "market:stream",
            "ai:read",
            "ai:stream",
            "screener:read",
            "strategy:read",
            "backtest:read",
            "jobs:read",
            "risk:read",
            "risk:stream",
            "trade:read",
            "portfolio:read",
            "portfolio:stream",
            "research:read",
            "system:docs.read",
            "system:metrics.read",
            "system:readiness.read",
        }
    ),
    "service_worker": frozenset(
        {
            "ai:read",
            "ai:run",
            "screener:read",
            "screener:run",
            "backtest:read",
            "backtest:run",
            "backtest:execute",
            "jobs:read",
            "jobs:execute",
            "risk:precheck",
        }
    ),
    "admin": frozenset(
        {
            "system:docs.read",
            "system:metrics.read",
            "system:notify.test",
            "system:readiness.read",
            "trade:approval.request",
            "trade:simulation.operate",
            "trade:broker.sync",
            "trade:reconcile",
            "jobs:read",
            "jobs:cancel",
        }
    ),
}

ANONYMOUS_READ_SCOPES = frozenset(
    {"market:read", "ai:read", "screener:read", "research:read"}
)


@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str
    principal_type: str
    role: str
    scopes: frozenset[str]
    source: str
    credential_id: str | None = None
    session_id: str | None = None
    csrf_digest: str | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.principal_type == "anonymous"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def public_payload(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "display_name": self.display_name,
            "principal_type": self.principal_type,
            "role": self.role,
            "scopes": sorted(self.scopes),
            "auth_source": self.source,
        }


@dataclass(frozen=True)
class SessionIssue:
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class RouteAccess:
    scope: str | None = None
    public: bool = False
    undeclared: bool = False
    csrf_required: bool = True


class AuthFailure(Exception):
    def __init__(
        self,
        message: str,
        code: str,
        status_code: int,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


class WebSocketAuthFailure(Exception):
    def __init__(self, close_code: int, code: str) -> None:
        super().__init__(code)
        self.close_code = close_code
        self.code = code


CredentialLoader = Callable[[str], Awaitable[Principal | None]]
SessionLoader = Callable[[str], Awaitable[Principal | None]]


def _digest(namespace: str, raw_value: str) -> str:
    secret = settings.SECRET_KEY.strip()
    if not secret:
        raise AuthFailure("认证密钥未配置", "AUTH_SECRET_UNAVAILABLE", 503, retryable=True)
    payload = f"{namespace}:{raw_value}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _normalize_scopes(values: Any) -> frozenset[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(str(value) for value in values if str(value) in KNOWN_SCOPES)


def _principal_scopes(role: str, credential_scopes: Any | None = None) -> frozenset[str]:
    role_scopes = ROLE_SCOPES.get(role, frozenset())
    if credential_scopes is None:
        return role_scopes
    return role_scopes & _normalize_scopes(credential_scopes)


def _anonymous_principal() -> Principal:
    return Principal(
        principal_id="development-anonymous",
        display_name="development-anonymous",
        principal_type="anonymous",
        role="anonymous",
        scopes=ANONYMOUS_READ_SCOPES,
        source="anonymous",
    )


def _header_credential(headers: Mapping[str, str]) -> str | None:
    authorization = (headers.get("Authorization") or headers.get("authorization") or "").strip()
    api_key = (headers.get("X-API-Key") or headers.get("x-api-key") or "").strip()
    bearer: str | None = None
    if authorization:
        scheme, separator, raw_value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not raw_value.strip():
            raise AuthFailure("认证头格式无效", "INVALID_AUTHORIZATION", 401)
        bearer = raw_value.strip()
    if bearer and api_key and not hmac.compare_digest(bearer, api_key):
        raise AuthFailure("请求携带了冲突的认证凭据", "CONFLICTING_CREDENTIALS", 401)
    return bearer or api_key or None


def extract_api_key(request: Request) -> str | None:
    """Compatibility helper for callers that only need the supplied credential."""
    try:
        return _header_credential(request.headers)
    except AuthFailure:
        return None


class AuthService:
    def __init__(
        self,
        *,
        credential_loader: CredentialLoader | None = None,
        session_loader: SessionLoader | None = None,
    ) -> None:
        self._credential_loader = credential_loader
        self._session_loader = session_loader

    async def authenticate(
        self,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
        *,
        allow_anonymous: bool,
    ) -> Principal:
        credential = _header_credential(headers)
        if credential:
            principal = await self._load_credential(credential)
            if principal is None:
                raise AuthFailure("认证凭据无效、已过期或已撤销", "INVALID_CREDENTIAL", 401)
            return principal

        session_token = cookies.get(settings.API_SESSION_COOKIE_NAME)
        if session_token:
            principal = await self._load_session(session_token)
            if principal is None:
                raise AuthFailure("会话无效、已过期或已撤销", "INVALID_SESSION", 401)
            return principal

        if allow_anonymous and not settings.is_production() and settings.API_ALLOW_ANONYMOUS_READS:
            return _anonymous_principal()
        raise AuthFailure("请提供有效的认证凭据", "UNAUTHORIZED", 401)

    async def _load_credential(self, raw_token: str) -> Principal | None:
        if self._credential_loader is not None:
            return await self._credential_loader(raw_token)
        digest = _digest("credential", raw_token)
        try:
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT c.credential_id, c.principal_id, c.scopes,
                               p.display_name, p.principal_type, p.role
                        FROM auth.api_credentials AS c
                        JOIN auth.principals AS p ON p.principal_id = c.principal_id
                        WHERE c.token_digest = :digest
                          AND c.revoked_at IS NULL
                          AND (c.expires_at IS NULL OR c.expires_at > NOW())
                          AND p.is_active IS TRUE
                        """
                    ),
                    {"digest": digest},
                )
                row = result.mappings().first()
        except SQLAlchemyError as exc:
            logger.warning("auth_credential_store_unavailable", error_type=type(exc).__name__)
            raise AuthFailure(
                "认证存储暂时不可用",
                "AUTH_STORE_UNAVAILABLE",
                503,
                retryable=True,
            ) from exc
        if row is None:
            return None
        scopes = _principal_scopes(str(row["role"]), row["scopes"])
        return Principal(
            principal_id=str(row["principal_id"]),
            display_name=str(row["display_name"]),
            principal_type=str(row["principal_type"]),
            role=str(row["role"]),
            scopes=scopes,
            source="credential",
            credential_id=str(row["credential_id"]),
        )

    async def _load_session(self, raw_token: str) -> Principal | None:
        if self._session_loader is not None:
            return await self._session_loader(raw_token)
        digest = _digest("session", raw_token)
        try:
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        SELECT s.session_id, s.credential_id, s.scopes, s.csrf_digest,
                               p.principal_id, p.display_name, p.principal_type, p.role
                        FROM auth.api_sessions AS s
                        JOIN auth.principals AS p ON p.principal_id = s.principal_id
                        WHERE s.session_digest = :digest
                          AND s.revoked_at IS NULL
                          AND s.expires_at > NOW()
                          AND p.is_active IS TRUE
                        """
                    ),
                    {"digest": digest},
                )
                row = result.mappings().first()
        except SQLAlchemyError as exc:
            logger.warning("auth_session_store_unavailable", error_type=type(exc).__name__)
            raise AuthFailure(
                "认证存储暂时不可用",
                "AUTH_STORE_UNAVAILABLE",
                503,
                retryable=True,
            ) from exc
        if row is None:
            return None
        scopes = _principal_scopes(str(row["role"]), row["scopes"])
        return Principal(
            principal_id=str(row["principal_id"]),
            display_name=str(row["display_name"]),
            principal_type=str(row["principal_type"]),
            role=str(row["role"]),
            scopes=scopes,
            source="session",
            credential_id=str(row["credential_id"]),
            session_id=str(row["session_id"]),
            csrf_digest=str(row["csrf_digest"]),
        )

    async def issue_session(self, principal: Principal, request: Request) -> SessionIssue:
        if principal.principal_type != "human" or not principal.credential_id:
            raise AuthFailure(
                "仅人工主体可创建浏览器会话",
                "HUMAN_CREDENTIAL_REQUIRED",
                403,
            )
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        session_id = str(uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.API_SESSION_TTL_SECONDS
        )
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")[:512]
        try:
            async with get_db() as db:
                await db.execute(
                    text(
                        """
                        INSERT INTO auth.api_sessions (
                            session_id, principal_id, credential_id, session_digest,
                            csrf_digest, scopes, expires_at, created_ip, user_agent
                        ) VALUES (
                            CAST(:session_id AS uuid), CAST(:principal_id AS uuid),
                            CAST(:credential_id AS uuid), :session_digest, :csrf_digest,
                            :scopes, :expires_at, CAST(:client_ip AS inet), :user_agent
                        )
                        """
                    ),
                    {
                        "session_id": session_id,
                        "principal_id": principal.principal_id,
                        "credential_id": principal.credential_id,
                        "session_digest": _digest("session", session_token),
                        "csrf_digest": _digest("csrf", csrf_token),
                        "scopes": sorted(principal.scopes),
                        "expires_at": expires_at,
                        "client_ip": client_ip,
                        "user_agent": user_agent,
                    },
                )
                await self._write_audit_event(
                    db,
                    principal=principal,
                    session_id=session_id,
                    request=request,
                    operation="AUTH_SESSION_CREATED",
                    result="SUCCESS",
                    after_data={"expires_at": expires_at.isoformat()},
                )
        except SQLAlchemyError as exc:
            logger.warning("auth_session_issue_failed", error_type=type(exc).__name__)
            raise AuthFailure(
                "会话创建失败",
                "SESSION_ISSUE_FAILED",
                503,
                retryable=True,
            ) from exc
        return SessionIssue(
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    async def revoke_session(self, principal: Principal, request: Request) -> bool:
        if principal.source != "session" or not principal.session_id:
            raise AuthFailure("该操作需要浏览器会话", "SESSION_COOKIE_REQUIRED", 403)
        try:
            async with get_db() as db:
                result = await db.execute(
                    text(
                        """
                        UPDATE auth.api_sessions
                        SET revoked_at = NOW()
                        WHERE session_id = CAST(:session_id AS uuid)
                          AND principal_id = CAST(:principal_id AS uuid)
                          AND revoked_at IS NULL
                        """
                    ),
                    {
                        "session_id": principal.session_id,
                        "principal_id": principal.principal_id,
                    },
                )
                revoked = bool(result.rowcount)
                if revoked:
                    await self._write_audit_event(
                        db,
                        principal=principal,
                        session_id=principal.session_id,
                        request=request,
                        operation="AUTH_SESSION_REVOKED",
                        result="SUCCESS",
                        after_data={},
                    )
        except SQLAlchemyError as exc:
            logger.warning("auth_session_revoke_failed", error_type=type(exc).__name__)
            raise AuthFailure(
                "会话撤销失败",
                "SESSION_REVOKE_FAILED",
                503,
                retryable=True,
            ) from exc
        return revoked

    async def _write_audit_event(
        self,
        db: Any,
        *,
        principal: Principal,
        session_id: str,
        request: Request,
        operation: str,
        result: str,
        after_data: dict[str, Any],
    ) -> None:
        client_ip = request.client.host if request.client else None
        await db.execute(
            text(
                """
                INSERT INTO audit.operation_logs (
                    session_id, operator, ip_address, operation, entity_type,
                    entity_id, after_data, result
                ) VALUES (
                    :session_id, :operator, CAST(:client_ip AS inet), :operation,
                    'auth_session', :entity_id, CAST(:after_data AS jsonb), :result
                )
                """
            ),
            {
                "session_id": session_id,
                "operator": principal.display_name[:50],
                "client_ip": client_ip,
                "operation": operation,
                "entity_id": session_id,
                "after_data": json.dumps(after_data, ensure_ascii=False),
                "result": result,
            },
        )

    def validate_csrf(self, principal: Principal, raw_token: str | None) -> None:
        if principal.source != "session":
            return
        if not raw_token or not principal.csrf_digest:
            raise AuthFailure("缺少 CSRF 令牌", "CSRF_REQUIRED", 403)
        supplied = _digest("csrf", raw_token)
        if not hmac.compare_digest(supplied, principal.csrf_digest):
            raise AuthFailure("CSRF 令牌无效", "CSRF_INVALID", 403)


_auth_service_override: AuthService | None = None


def get_auth_service() -> AuthService:
    return _auth_service_override or AuthService()


def set_auth_service_for_testing(service: AuthService | None) -> None:
    global _auth_service_override
    _auth_service_override = service


_READ_SCOPE_PREFIXES = (
    ("/api/v1/stock", "market:read"),
    ("/api/v1/ai", "ai:read"),
    ("/api/v1/screener", "screener:read"),
    ("/api/v1/strategy", "strategy:read"),
    ("/api/v1/backtest", "backtest:read"),
    ("/api/v1/jobs", "jobs:read"),
    ("/api/v1/risk", "risk:read"),
    ("/api/v1/trade", "trade:read"),
    ("/api/v1/portfolio", "portfolio:read"),
    ("/api/v1/research", "research:read"),
)

_POST_SCOPES = {
    "/api/v1/stock/sync-universe": "market:operate",
    "/api/v1/stock/backfill-kline": "market:operate",
    "/api/v1/ai/analyze": "ai:run",
    "/api/v1/screener/screen": "screener:run",
    "/api/v1/screener/theme": "screener:run",
    "/api/v1/strategy/create": "strategy:write",
    "/api/v1/backtest/run": "backtest:run",
    "/api/v1/risk/fuse/activate": "risk:fuse.activate",
    "/api/v1/risk/fuse/recover": "risk:fuse.recover",
    "/api/v1/risk/pre-check": "risk:precheck",
    "/api/v1/risk/alerts/test-dingtalk": "system:notify.test",
    "/api/v1/trade/order": "trade:order.create",
    "/api/v1/trade/approvals": "trade:approval.request",
    "/api/v1/trade/order/cancel": "trade:order.cancel",
    "/api/v1/trade/simulation/release-t1": "trade:simulation.operate",
    "/api/v1/trade/orders/sync": "trade:broker.sync",
    "/api/v1/trade/reconcile": "trade:reconcile",
}


def _has_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def legacy_route_review_id(method: str, path: str) -> str | None:
    method = method.upper()
    if method == "POST" and path == "/api/v1/strategy/create":
        return "strategy-create"
    if (
        method == "POST"
        and path.startswith("/api/v1/strategy/")
        and path.endswith("/update")
    ):
        return "strategy-update"
    if method == "POST" and path == "/api/v1/trade/simulation/release-t1":
        return "simulation-release-t1"
    if method == "POST" and path == "/api/v1/risk/alerts/test-dingtalk":
        return "risk-dingtalk-test"
    if method == "WEBSOCKET" and path.startswith("/ws/quotes/"):
        return "ws-quotes"
    if method == "WEBSOCKET" and path == "/ws/signals":
        return "ws-signals"
    if method == "WEBSOCKET" and path == "/ws/alerts":
        return "ws-alerts"
    if method == "WEBSOCKET" and path == "/ws/portfolio":
        return "ws-portfolio"
    return None


def emit_legacy_route_review_telemetry(
    method: str,
    path: str,
    principal: Principal,
    *,
    request_id: str | None = None,
    client: str | None = None,
    user_agent: str | None = None,
) -> None:
    review_id = legacy_route_review_id(method, path)
    if review_id is None:
        return
    logger.warning(
        "legacy_route_review_invoked",
        review_id=review_id,
        method=method.upper(),
        path=path,
        principal_id=principal.principal_id,
        principal_type=principal.principal_type,
        credential_id=principal.credential_id,
        auth_source=principal.source,
        request_id=request_id,
        client=client,
        user_agent=(user_agent or "")[:256],
    )


def route_access(method: str, path: str) -> RouteAccess:
    method = method.upper()
    if method == "OPTIONS":
        return RouteAccess(public=True, csrf_required=False)
    if method in {"GET", "HEAD"} and path == "/api/v1/health":
        return RouteAccess(public=True, csrf_required=False)
    if method == "POST" and path == "/api/v1/auth/session":
        return RouteAccess(csrf_required=False)
    if method == "GET" and path == "/api/v1/auth/me":
        return RouteAccess(csrf_required=False)
    if method == "DELETE" and path == "/api/v1/auth/session":
        return RouteAccess()
    if method in {"GET", "HEAD"} and path == "/api/v1/readiness":
        return RouteAccess(scope="system:readiness.read", csrf_required=False)
    if method in {"GET", "HEAD"} and path == "/metrics":
        return RouteAccess(scope="system:metrics.read", csrf_required=False)
    if method in {"GET", "HEAD"} and path in {
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
    }:
        return RouteAccess(scope="system:docs.read", csrf_required=False)
    if method in {"GET", "HEAD"}:
        for prefix, scope in _READ_SCOPE_PREFIXES:
            if _has_prefix(path, prefix):
                return RouteAccess(scope=scope, csrf_required=False)
    if method == "POST":
        if path in _POST_SCOPES:
            return RouteAccess(scope=_POST_SCOPES[path])
        if path.startswith("/api/v1/backtest/jobs/") and path.endswith("/execute"):
            return RouteAccess(scope="backtest:execute")
        if path.startswith("/api/v1/backtest/jobs/") and path.endswith("/cancel"):
            return RouteAccess(scope="backtest:run")
        if path.startswith("/api/v1/jobs/") and path.endswith("/execute"):
            return RouteAccess(scope="jobs:execute")
        if path.startswith("/api/v1/jobs/") and path.endswith("/cancel"):
            return RouteAccess(scope="jobs:cancel")
        if path.startswith("/api/v1/ai/") and path.endswith("/analyze"):
            return RouteAccess(scope="ai:run")
        if path.startswith("/api/v1/strategy/versions/") and path.endswith("/approve"):
            return RouteAccess(scope="strategy:approve")
        if path.startswith("/api/v1/strategy/") and path.endswith("/update"):
            return RouteAccess(scope="strategy:write")
        if path.startswith("/api/v1/trade/orders/") and path.endswith("/sync"):
            return RouteAccess(scope="trade:broker.sync")
        if path.startswith("/api/v1/trade/approvals/") and path.endswith("/approve"):
            return RouteAccess(scope="trade:approval.approve")
        if path.startswith("/api/v1/research/evidence/") and (
            path.endswith("/reviews")
            or path.endswith("/financial-location-reviews")
        ):
            return RouteAccess(scope="research:review.append")
    if path.startswith("/api/") or path == "/metrics":
        return RouteAccess(undeclared=True, csrf_required=False)
    return RouteAccess(public=True, csrf_required=False)


async def api_security_middleware(request: Request, call_next: Any) -> Any:
    access = route_access(request.method, request.url.path)
    if access.public:
        return await call_next(request)
    if access.undeclared:
        return problem_response(
            request,
            message="该 API 路径尚未登记权限契约",
            code="ROUTE_SCOPE_UNDECLARED",
            status_code=403,
        )

    allow_anonymous = (
        request.method.upper() in SAFE_METHODS
        and access.scope in ANONYMOUS_READ_SCOPES
    )
    service = get_auth_service()
    principal: Principal | None = None
    try:
        principal = await service.authenticate(
            request.headers,
            request.cookies,
            allow_anonymous=allow_anonymous,
        )
        if (
            principal.principal_type == "human"
            and principal.source == "credential"
            and (
                request.method.upper() != "POST"
                or request.url.path != "/api/v1/auth/session"
            )
        ):
            raise AuthFailure(
                "人类主体必须先建立浏览器会话",
                "HUMAN_SESSION_REQUIRED",
                403,
            )
        if access.scope and not principal.has_scope(access.scope):
            raise AuthFailure("当前主体没有执行此操作的权限", "FORBIDDEN", 403)
        if (
            access.csrf_required
            and request.method.upper() not in SAFE_METHODS
            and principal.source == "session"
        ):
            service.validate_csrf(principal, request.headers.get("X-CSRF-Token"))
    except AuthFailure as exc:
        logger.warning(
            "api_auth_rejected",
            method=request.method,
            path=request.url.path,
            error_code=exc.code,
            status_code=exc.status_code,
            principal_id=principal.principal_id if principal else None,
            credential_id=principal.credential_id if principal else None,
            auth_source=principal.source if principal else None,
            request_id=getattr(request.state, "request_id", None),
        )
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return problem_response(
            request,
            message=exc.message,
            code=exc.code,
            status_code=exc.status_code,
            retryable=exc.retryable,
            headers=headers,
        )
    request.state.principal = principal
    request.state.auth_service = service
    emit_legacy_route_review_telemetry(
        request.method,
        request.url.path,
        principal,
        request_id=getattr(request.state, "request_id", None),
        client=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    logger.debug(
        "api_auth_allowed",
        principal_id=principal.principal_id,
        credential_id=principal.credential_id,
        auth_source=principal.source,
        scope=access.scope,
    )
    return await call_next(request)


def get_request_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise AuthFailure("请求未通过认证", "UNAUTHORIZED", 401)
    return principal


async def authenticate_websocket(websocket: WebSocket, scope: str) -> Principal:
    origin = websocket.headers.get("origin")
    if not origin or origin not in settings.ALLOWED_ORIGINS:
        logger.warning(
            "ws_origin_rejected",
            origin=origin or "",
            path=getattr(getattr(websocket, "url", None), "path", None),
        )
        raise WebSocketAuthFailure(4403, "WS_ORIGIN_FORBIDDEN")
    service = get_auth_service()
    try:
        principal = await service.authenticate(
            websocket.headers,
            websocket.cookies,
            allow_anonymous=False,
        )
    except AuthFailure as exc:
        logger.warning(
            "ws_auth_rejected",
            error_code=exc.code,
            path=getattr(getattr(websocket, "url", None), "path", None),
        )
        raise WebSocketAuthFailure(4401 if exc.status_code == 401 else 1011, exc.code) from exc
    if not principal.has_scope(scope):
        logger.warning(
            "ws_scope_rejected",
            principal_id=principal.principal_id,
            credential_id=principal.credential_id,
            required_scope=scope,
            path=getattr(getattr(websocket, "url", None), "path", None),
        )
        raise WebSocketAuthFailure(4403, "WS_SCOPE_FORBIDDEN")
    if principal.principal_type == "human" and principal.source == "credential":
        logger.warning(
            "ws_human_session_required",
            principal_id=principal.principal_id,
            credential_id=principal.credential_id,
            path=getattr(getattr(websocket, "url", None), "path", None),
        )
        raise WebSocketAuthFailure(4403, "HUMAN_SESSION_REQUIRED")
    return principal
