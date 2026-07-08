from fastapi import APIRouter

from app.core.response import ok

router = APIRouter()


@router.post("/run")
async def run_backtest():
    return ok(message="Phase 4: not implemented")


@router.get("/{task_id}/status")
async def get_backtest_status(task_id: int):
    return ok({"task_id": task_id, "progress": 0}, message="Phase 4: not implemented")