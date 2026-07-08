from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.core.response import ok
from app.schemas.screener import ScreenRequest, ThemeScreenRequest
from app.screener.engine import ScreenerEngine
from app.screener.presets import list_presets

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_screener_engine() -> ScreenerEngine:
    return ScreenerEngine()


@router.post("/screen")
async def screen_stocks(
    request: ScreenRequest,
    engine: ScreenerEngine = Depends(get_screener_engine),
):
    """自定义条件或预设条件筛选股票。"""
    try:
        if request.preset_id:
            result = await engine.screen_preset(request.preset_id, limit=request.limit)
        else:
            conditions = request.conditions or {"filters": []}
            result = await engine.screen(conditions, limit=request.limit)
        logger.info(
            "screener_screen_done",
            preset_id=request.preset_id,
            total=result.get("total"),
            from_cache=result.get("from_cache"),
        )
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/presets")
async def get_presets():
    """获取预设选股条件列表。"""
    return ok({"items": list_presets(), "total": len(list_presets())})


@router.post("/theme")
async def screen_by_theme(
    request: ThemeScreenRequest,
    engine: ScreenerEngine = Depends(get_screener_engine),
):
    """AI 主题选股（关键词 + 行业 + 公告匹配）。"""
    try:
        result = await engine.screen_by_theme(request.theme, limit=request.limit)
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc