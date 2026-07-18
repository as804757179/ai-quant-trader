from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.auth import (
    Principal,
    WebSocketAuthFailure,
    authenticate_websocket,
    emit_legacy_route_review_telemetry,
)
from app.core.logging import FEATURE_WS, get_logger
from app.ws.manager import ws_manager

logger = get_logger(__name__, feature=FEATURE_WS)
router = APIRouter()


async def _authorize_channel(
    websocket: WebSocket,
    required_scope: str,
) -> Principal | None:
    if any(key in websocket.query_params for key in ("token", "access_token", "api_key")):
        logger.warning(
            "ws_query_credential_rejected",
            path=websocket.url.path,
            client=websocket.client.host if websocket.client else None,
        )
        await websocket.close(code=4403, reason="WS_QUERY_CREDENTIAL_FORBIDDEN")
        return None
    try:
        principal = await authenticate_websocket(websocket, required_scope)
    except WebSocketAuthFailure as exc:
        await websocket.close(code=exc.close_code, reason=exc.code)
        return None
    websocket.state.principal = principal
    emit_legacy_route_review_telemetry(
        "WEBSOCKET",
        websocket.url.path,
        principal,
        client=websocket.client.host if websocket.client else None,
        user_agent=websocket.headers.get("user-agent"),
    )
    return principal


async def _serve_channel(
    websocket: WebSocket,
    channel: str,
    principal: Principal,
) -> None:
    logger.info(
        "ws_connect",
        channel=channel,
        principal_id=principal.principal_id,
        credential_id=principal.credential_id,
    )
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            await ws_manager.handle_client_message(websocket, data)
    except WebSocketDisconnect:
        logger.info(
            "ws_disconnect",
            channel=channel,
            principal_id=principal.principal_id,
            reason="client_closed",
        )
    except Exception as exc:
        logger.warning(
            "ws_error",
            channel=channel,
            principal_id=principal.principal_id,
            error_type=type(exc).__name__,
        )
    finally:
        await ws_manager.disconnect(websocket)
        logger.debug("ws_cleanup", channel=channel, principal_id=principal.principal_id)


@router.websocket("/quotes/{stock_code}")
async def ws_quote(websocket: WebSocket, stock_code: str) -> None:
    principal = await _authorize_channel(websocket, "market:stream")
    if principal is None:
        return
    if not stock_code.isdigit() or len(stock_code) != 6:
        await websocket.close(code=4403, reason="WS_INVALID_STOCK_CODE")
        return
    await _serve_channel(websocket, f"quotes:{stock_code}", principal)


@router.websocket("/signals")
async def ws_signals(websocket: WebSocket) -> None:
    principal = await _authorize_channel(websocket, "ai:stream")
    if principal is not None:
        await _serve_channel(websocket, "signals", principal)


@router.websocket("/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    principal = await _authorize_channel(websocket, "risk:stream")
    if principal is not None:
        await _serve_channel(websocket, "alerts", principal)


@router.websocket("/portfolio")
async def ws_portfolio(websocket: WebSocket, mode: str = Query("simulation")) -> None:
    principal = await _authorize_channel(websocket, "portfolio:stream")
    if principal is None:
        return
    if mode not in {"simulation", "paper", "live"}:
        await websocket.close(code=4403, reason="WS_INVALID_PORTFOLIO_MODE")
        return
    await _serve_channel(websocket, f"portfolio:{mode}", principal)
