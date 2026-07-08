from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.ws.manager import ws_manager

router = APIRouter()


async def _serve_channel(websocket: WebSocket, channel: str) -> None:
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            await ws_manager.handle_client_message(websocket, data)
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket)


@router.websocket("/quotes/{stock_code}")
async def ws_quote(websocket: WebSocket, stock_code: str) -> None:
    """单股实时行情推送（订阅 Redis channel:quotes:{code}）。"""
    await _serve_channel(websocket, f"quotes:{stock_code}")


@router.websocket("/signals")
async def ws_signals(websocket: WebSocket) -> None:
    """AI 信号实时推送。"""
    await _serve_channel(websocket, "signals")


@router.websocket("/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    """风控/熔断告警推送。"""
    await _serve_channel(websocket, "alerts")


@router.websocket("/portfolio")
async def ws_portfolio(websocket: WebSocket, mode: str = Query("simulation")) -> None:
    """持仓更新推送（按交易模式订阅）。"""
    await _serve_channel(websocket, f"portfolio:{mode}")