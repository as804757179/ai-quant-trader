"""回测绩效指标。"""

from __future__ import annotations

import math
from typing import Any

from app.backtest.schemas import BacktestResult, EquityPoint, TradeRecord


def max_drawdown(equity_curve: list[EquityPoint]) -> float:
    peak = 0.0
    max_dd = 0.0
    for pt in equity_curve:
        peak = max(peak, pt.total_assets)
        if peak > 0:
            dd = (pt.total_assets - peak) / peak
            max_dd = min(max_dd, dd)
    return abs(max_dd)


def sharpe_ratio(equity_curve: list[EquityPoint], risk_free: float = 0.0) -> float:
    if len(equity_curve) < 2:
        return 0.0
    rets = [p.daily_return for p in equity_curve[1:]]
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    std = math.sqrt(var)
    if std < 1e-12:
        return 0.0
    # 年化近似（A 股约 242 交易日）
    return (mean - risk_free / 242) / std * math.sqrt(242)


def _legacy_win_rate(trades: list[TradeRecord]) -> float:
    """按完整买卖轮次近似：成对统计卖出相对成本的盈亏需持仓成本。简化为：
    仅统计 FILLED 卖出笔数中 amount 维度无法直接得盈亏时返回 0。
    这里用相邻 BUY/SELL 配对。
    """
    buys: dict[str, list[TradeRecord]] = {}
    wins = 0
    total = 0
    for t in trades:
        if t.status != "FILLED":
            continue
        if t.side == "BUY":
            buys.setdefault(t.stock_code, []).append(t)
        elif t.side == "SELL":
            lot = buys.get(t.stock_code) or []
            if not lot:
                continue
            b = lot.pop(0)
            total += 1
            # 粗略：卖出均价 > 买入均价
            if t.fill_price > b.fill_price:
                wins += 1
    return wins / total if total else 0.0


def realized_pnls(trades: list[TradeRecord]) -> list[float]:
    explicit = [
        trade.realized_pnl
        for trade in trades
        if trade.status == "FILLED" and trade.side == "SELL"
    ]
    if explicit and any(value != 0.0 for value in explicit):
        return explicit
    lots: dict[str, list[list[float]]] = {}
    pnls: list[float] = []
    for trade in trades:
        if trade.status != "FILLED":
            continue
        if trade.side == "BUY":
            unit_cost = (
                trade.amount + trade.commission + trade.transfer_fee
            ) / trade.quantity
            lots.setdefault(trade.stock_code, []).append(
                [float(trade.quantity), unit_cost]
            )
        elif trade.side == "SELL":
            remaining = float(trade.quantity)
            proceeds_per_share = (
                trade.amount
                - trade.commission
                - trade.stamp_tax
                - trade.transfer_fee
            ) / trade.quantity
            cost = 0.0
            stock_lots = lots.get(trade.stock_code) or []
            while remaining > 0 and stock_lots:
                qty, unit_cost = stock_lots[0]
                matched = min(remaining, qty)
                cost += matched * unit_cost
                remaining -= matched
                qty -= matched
                if qty <= 0:
                    stock_lots.pop(0)
                else:
                    stock_lots[0][0] = qty
            if remaining == 0:
                pnls.append(proceeds_per_share * trade.quantity - cost)
    return pnls


def win_rate(trades: list[TradeRecord]) -> float:
    pnls = realized_pnls(trades)
    return sum(1 for pnl in pnls if pnl > 0) / len(pnls) if pnls else 0.0


def profit_factor(trades: list[TradeRecord]) -> float | None:
    pnls = realized_pnls(trades)
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    if gross_loss == 0:
        return None if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def turnover_ratio(result: BacktestResult) -> float:
    filled_amount = sum(t.amount for t in result.trades if t.status == "FILLED")
    if not result.equity_curve:
        return 0.0
    average_assets = sum(p.total_assets for p in result.equity_curve) / len(
        result.equity_curve
    )
    return filled_amount / average_assets if average_assets > 0 else 0.0


def fee_summary(trades: list[TradeRecord]) -> dict[str, float]:
    filled = [trade for trade in trades if trade.status == "FILLED"]
    commission = sum(trade.commission for trade in filled)
    stamp_tax = sum(trade.stamp_tax for trade in filled)
    slippage = sum(trade.slippage_cost for trade in filled)
    transfer_fee = sum(trade.transfer_fee for trade in filled)
    return {
        "commission": round(commission, 2),
        "stamp_duty": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "slippage": round(slippage, 2),
        "explicit_fees": round(commission + stamp_tax + transfer_fee, 2),
    }


def annual_return(total_return: float, trading_days: int) -> float:
    if trading_days <= 0:
        return 0.0
    years = trading_days / 242
    if years <= 0:
        return 0.0
    return (1 + total_return) ** (1 / years) - 1


def summarize_result(result: BacktestResult) -> dict[str, Any]:
    mdd = max_drawdown(result.equity_curve)
    sharpe = sharpe_ratio(result.equity_curve)
    wr = win_rate(result.trades)
    pf = profit_factor(result.trades)
    turnover = turnover_ratio(result)
    fees = fee_summary(result.trades)
    ann = annual_return(result.total_return, result.trading_days)
    calmar = (ann / mdd) if mdd > 1e-8 else 0.0
    return {
        "total_return": round(result.total_return, 6),
        "annual_return": round(ann, 6),
        "max_drawdown": round(mdd, 6),
        "sharpe_ratio": round(sharpe, 4),
        "calmar_ratio": round(calmar, 4),
        "win_rate": round(wr, 4),
        "profit_factor": round(pf, 4) if pf is not None else None,
        "turnover": round(turnover, 6),
        "fees": fees,
        "total_trades": result.filled_trades,
        "failed_trades": result.failed_trades,
        "trading_days": result.trading_days,
        "final_cash": round(result.final_cash, 2),
        "final_market_value": round(result.final_market_value, 2),
        "final_assets": round(result.final_cash + result.final_market_value, 2),
    }
