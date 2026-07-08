from fastapi import APIRouter

from app.core.response import ok

router = APIRouter()


@router.get("/list")
async def list_strategies():
    return ok({"items": []}, message="Phase 4: not implemented")


@router.post("/create")
async def create_strategy():
    return ok(message="Phase 4: not implemented")