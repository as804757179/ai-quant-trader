"""订单幂等键生成。"""

from __future__ import annotations

import hashlib


def build_idempotency_key(
    *,
    mode: str,
    signal_id: str | None,
    stock_code: str,
    side: str,
    quantity: int,
    order_type: str = "LIMIT",
    limit_price: float | None = None,
) -> str:
    """
    生成稳定幂等键（≤64 字符）。

    包含 mode / 价格 / 订单类型，避免：
    - 跨 mode 撞 UNIQUE
    - 同数量不同价格被误判重复
    """
    sid = (signal_id or "manual").strip() or "manual"
    price_part = (
        f"{float(limit_price):.4f}"
        if limit_price is not None and str(order_type).upper() == "LIMIT"
        else "MKT"
    )
    raw = (
        f"{mode}|{sid}|{stock_code}|{side.upper()}|"
        f"{order_type.upper()}|{int(quantity)}|{price_part}"
    )
    # 固定 64 位 hex，兼容 VARCHAR(64)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]
