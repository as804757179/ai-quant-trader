from datetime import date

from fastapi import APIRouter, Query

from app.core.response import ok
from app.data.certified_kline_repository import CertifiedKlineRepository


router = APIRouter()


@router.get("/certified-klines")
async def list_certified_klines(
    stock_code: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    period: str = Query("1d", min_length=1, max_length=10),
    adjustment: str = Query("raw", pattern="^(raw|qfq|hfq)$"),
    batch_id: str | None = Query(None, min_length=1, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    data = await CertifiedKlineRepository().list_lineage(
        stock_code=stock_code,
        date_from=date_from,
        date_to=date_to,
        period=period,
        adjustment=adjustment,
        batch_id=batch_id,
        page=page,
        page_size=page_size,
    )
    data.update(
        {
            "certification_scope": "certified_store_observation",
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.certified_klines",
            "source_version": "certified-kline-lineage-v1",
        }
    )
    return ok(data)
