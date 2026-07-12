"""按环境创建 QMT 适配器。"""

from __future__ import annotations

import os
from pathlib import Path

import structlog

from app.core.config import settings
from app.trade.qmt.adapter import QmtAdapter
from app.trade.qmt.mock_adapter import MockQmtAdapter
from app.trade.qmt.xtquant_adapter import QmtNotAvailableError, XtQuantAdapter

logger = structlog.get_logger(__name__)


def create_qmt_adapter(mode: str = "paper") -> QmtAdapter:
    """
    mode:
      - paper/test: 始终 Mock
      - live: 仅允许真实 xtquant/QMT，任何前置条件缺失均失败
    """
    prefer_mock = os.getenv("QMT_FORCE_MOCK", "").lower() in ("1", "true", "yes")
    cash = float(os.getenv("MOCK_QMT_CASH", "1000000"))

    if mode in ("paper", "test"):
        logger.info("qmt_adapter_selected", adapter="mock", mode=mode)
        return MockQmtAdapter(initial_cash=cash)

    if mode != "live":
        raise ValueError(f"unsupported broker mode: {mode}")
    if prefer_mock:
        raise QmtNotAvailableError("live mode forbids QMT_FORCE_MOCK")

    probe = XtQuantAdapter()
    probe._import_xt()
    if not probe.qmt_path:
        raise QmtNotAvailableError("QMT_PATH 未配置")
    if not Path(probe.qmt_path).exists():
        raise QmtNotAvailableError(f"QMT_PATH 不存在: {probe.qmt_path}")
    if not probe.account_id:
        raise QmtNotAvailableError("QMT_ACCOUNT_ID 未配置")
    logger.info("qmt_adapter_selected", adapter="xtquant", mode=mode)
    return probe


def probe_broker_environment() -> dict:
    """供 /trade/broker-status 使用。"""
    xt = XtQuantAdapter()
    info = xt.probe_status()
    info["allow_mock_live"] = False
    info["trade_mode"] = settings.TRADE_MODE
    info["force_mock"] = os.getenv("QMT_FORCE_MOCK", "").lower() in ("1", "true", "yes")
    try:
        adapter = create_qmt_adapter(
            "live" if settings.TRADE_MODE == "live" else "paper"
        )
        info["selected_adapter"] = adapter.name
    except Exception as exc:
        info["selected_adapter"] = None
        info["select_error"] = str(exc)
    return info
