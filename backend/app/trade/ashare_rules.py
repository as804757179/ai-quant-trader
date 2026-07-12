"""A 股交易规则工具（模拟盘/校验共用）。

说明：
- 价格优先使用真实行情接口返回的 last/prev_close/涨跌停；
- 规则按沪深京常见制度实现（手数、涨跌停、佣金印花税、交易时段、T+1）；
- 不连接券商柜台，仅本地模拟撮合。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")

# 佣金万三、最低 5 元；印花税卖出 0.05%（2023-08-28 起）
COMMISSION_RATE = Decimal("0.0003")
MIN_COMMISSION = Decimal("5")
STAMP_TAX_RATE = Decimal("0.0005")
# 市价滑点（模拟）
SLIPPAGE_RATE = Decimal("0.001")
TICK = Decimal("0.01")


def now_cn(dt: datetime | None = None) -> datetime:
    if dt is None:
        return datetime.now(CN_TZ)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CN_TZ)
    return dt.astimezone(CN_TZ)


def round_price(value: float | Decimal) -> float:
    d = Decimal(str(value)).quantize(TICK, rounding=ROUND_HALF_UP)
    return float(d)


def is_st_name(name: str | None) -> bool:
    if not name:
        return False
    u = str(name).upper()
    return "ST" in u or "退" in str(name)


def board_limit_pct(code: str, name: str | None = None) -> float:
    """涨跌幅限制比例（不含 % 符号，如 0.10）。"""
    code = str(code).zfill(6)
    if is_st_name(name):
        return 0.05
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith(("4", "8", "92")):
        return 0.30  # 北交所
    return 0.10


def calc_limit_prices(prev_close: float, code: str, name: str | None = None) -> tuple[float, float]:
    pct = board_limit_pct(code, name)
    if prev_close <= 0:
        return 0.0, 0.0
    up = round_price(prev_close * (1 + pct))
    down = round_price(prev_close * (1 - pct))
    if down < TICK:
        down = float(TICK)
    return up, down


def is_weekday(dt: datetime | None = None) -> bool:
    d = now_cn(dt)
    return d.weekday() < 5  # 0=Mon … 不含法定节假日表（可后续扩展）


def is_continuous_auction(dt: datetime | None = None) -> bool:
    """连续竞价时段：09:30-11:30、13:00-15:00（工作日）。"""
    d = now_cn(dt)
    if d.weekday() >= 5:
        return False
    t = d.time()
    am = time(9, 30) <= t <= time(11, 30)
    pm = time(13, 0) <= t <= time(15, 0)
    return am or pm


def is_order_accept_time(dt: datetime | None = None) -> bool:
    """可接受委托时段（含集合竞价申报 09:15-09:25，以及连续竞价）。"""
    d = now_cn(dt)
    if d.weekday() >= 5:
        return False
    t = d.time()
    call = time(9, 15) <= t < time(9, 25)
    # 9:25-9:30 不可撤单但仍可能在部分券商显示；模拟允许从 9:15 到 15:00
    morning = time(9, 15) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(15, 0)
    return call or morning or afternoon


def validate_lot(code: str, quantity: int, side: str) -> str | None:
    """校验数量。返回错误信息或 None。"""
    if quantity <= 0:
        return "委托数量必须大于 0"
    code = str(code).zfill(6)
    # 科创板买入申报数量 ≥200，且 1 股递增；卖出可零股
    if code.startswith("688"):
        if side == "BUY" and quantity < 200:
            return "科创板买入不少于 200 股"
        return None
    # 主板/创业板：100 股整数倍（卖出零股最后一笔允许 <100，此处简化：卖出也要求 100 的倍数，除非 quantity==可用全部由上层处理）
    if quantity % 100 != 0:
        return "A 股委托数量须为 100 股整数倍（1 手）"
    return None


def validate_price_tick(price: float | None) -> str | None:
    if price is None:
        return None
    if price <= 0:
        return "价格必须大于 0"
    # 允许浮点误差，统一四舍五入到分
    return None


def normalize_limit_price(price: float | None) -> float | None:
    if price is None:
        return None
    return round_price(price)


def fees(side: str, amount: float) -> tuple[float, float, float]:
    """返回 (commission, stamp_tax, total_fee)。"""
    amt = Decimal(str(amount))
    commission = max(amt * COMMISSION_RATE, MIN_COMMISSION)
    stamp = amt * STAMP_TAX_RATE if side == "SELL" else Decimal("0")
    return float(commission), float(stamp), float(commission + stamp)


@dataclass
class MarketSnapshot:
    stock_code: str
    price: float
    prev_close: float
    limit_up: float
    limit_down: float
    name: str = ""
    source: str = "quote"  # quote | kline
    bid1: float | None = None
    ask1: float | None = None
    change_pct: float | None = None


def build_snapshot_from_quote(code: str, quote: dict) -> MarketSnapshot | None:
    price = float(quote.get("price") or 0)
    if price <= 0:
        return None
    prev = float(quote.get("prev_close") or 0) or price
    name = str(quote.get("name") or "")
    lu = quote.get("limit_up")
    ld = quote.get("limit_down")
    if lu and ld and float(lu) > 0 and float(ld) > 0:
        limit_up, limit_down = float(lu), float(ld)
    else:
        limit_up, limit_down = calc_limit_prices(prev, code, name)
    return MarketSnapshot(
        stock_code=str(code).zfill(6),
        price=round_price(price),
        prev_close=round_price(prev),
        limit_up=round_price(limit_up),
        limit_down=round_price(limit_down),
        name=name,
        source="quote",
        bid1=float(quote["bid1_price"]) if quote.get("bid1_price") else None,
        ask1=float(quote["ask1_price"]) if quote.get("ask1_price") else None,
        change_pct=float(quote["change_pct"]) if quote.get("change_pct") is not None else None,
    )


def build_snapshot_from_kline(code: str, klines: list[dict], name: str = "") -> MarketSnapshot | None:
    if not klines:
        return None
    last = klines[-1]
    close = float(last.get("close") or 0)
    if close <= 0:
        return None
    prev = float(klines[-2]["close"]) if len(klines) > 1 else close
    if prev <= 0:
        prev = close
    limit_up, limit_down = calc_limit_prices(prev, code, name)
    return MarketSnapshot(
        stock_code=str(code).zfill(6),
        price=round_price(close),
        prev_close=round_price(prev),
        limit_up=limit_up,
        limit_down=limit_down,
        name=name,
        source="kline",
        change_pct=round((close / prev - 1) * 100, 2) if prev else 0.0,
    )


def check_limit_board(side: str, snap: MarketSnapshot) -> str | None:
    """涨跌停无法对手成交。"""
    p, up, down = snap.price, snap.limit_up, snap.limit_down
    if side == "BUY" and up > 0 and p >= up * 0.999:
        return f"涨停（{up:.2f}）无法买入"
    if side == "SELL" and down > 0 and p <= down * 1.001:
        return f"跌停（{down:.2f}）无法卖出"
    return None


def clamp_limit_price(limit_price: float, snap: MarketSnapshot) -> tuple[float, str | None]:
    """将限价夹到涨跌停内，返回 (调整后价格, 提示)。"""
    lp = round_price(limit_price)
    note = None
    if snap.limit_down > 0 and lp < snap.limit_down - 1e-9:
        note = f"限价已调整为跌停价 {snap.limit_down:.2f}"
        lp = snap.limit_down
    if snap.limit_up > 0 and lp > snap.limit_up + 1e-9:
        note = f"限价已调整为涨停价 {snap.limit_up:.2f}"
        lp = snap.limit_up
    return round_price(lp), note


def resolve_fill_price(
    side: str,
    order_type: str,
    limit_price: float | None,
    snap: MarketSnapshot,
) -> tuple[float | None, str | None, str]:
    """
    计算成交价。
    返回 (fill_price, error_or_note, status)
    status: FILLED | SUBMITTED | FAILED
    """
    p = snap.price
    ask = snap.ask1 if snap.ask1 and snap.ask1 > 0 else p
    bid = snap.bid1 if snap.bid1 and snap.bid1 > 0 else p

    if order_type == "MARKET":
        if side == "BUY":
            raw = ask * float(1 + SLIPPAGE_RATE)
            fill = min(round_price(raw), snap.limit_up or raw)
        else:
            raw = bid * float(1 - SLIPPAGE_RATE)
            fill = max(round_price(raw), snap.limit_down or raw)
        return fill, None, "FILLED"

    # LIMIT
    if limit_price is None or limit_price <= 0:
        return None, "限价单必须指定委托价格", "FAILED"
    lp, clamp_note = clamp_limit_price(float(limit_price), snap)

    if side == "BUY":
        # 卖一/现价不高于限价才成交
        if ask > lp + 1e-9 and p > lp + 1e-9:
            return None, clamp_note or "限价买单未触及现价，已挂单等待", "SUBMITTED"
        fill = min(lp, ask if ask > 0 else p)
        return round_price(fill), clamp_note, "FILLED"
    else:
        # 卖出限价=最低接受价：现价/买一 >= 限价 才成交
        if bid + 1e-9 < lp and p + 1e-9 < lp:
            return None, clamp_note or "限价卖单未触及现价，已挂单等待", "SUBMITTED"
        # 成交价取盘口与限价中对卖方更优者，但不低于限价
        ref = bid if bid > 0 else p
        fill = max(lp, min(ref, snap.limit_up or ref))
        return round_price(fill), clamp_note, "FILLED"
