"""内置策略信号生成器（供回测引擎使用）。"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from app.backtest.schemas import BacktestSignal, DailyBar, PositionSnapshot, SignalGenerator


def _closes_up_to(
    bars: dict[date, DailyBar], as_of: date
) -> list[tuple[date, float]]:
    items = sorted((d, b.close) for d, b in bars.items() if d <= as_of)
    return items


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _qty_from_pct(cash_or_assets: float, price: float, pct: float, lot: int = 100) -> int:
    if price <= 0:
        return 0
    raw = int(cash_or_assets * pct / price / lot) * lot
    return max(raw, lot) if raw > 0 else 0


def make_signal_generator(
    strategy_type: str,
    universe: list[str],
    params: dict[str, Any],
    *,
    initial_cash: float = 1_000_000,
) -> SignalGenerator:
    factories: dict[str, Callable[..., SignalGenerator]] = {
        "dual_ma": _make_dual_ma,
        "bollinger": _make_bollinger,
        "rsi": _make_rsi,
        "macd": _make_macd,
    }
    factory = factories.get(strategy_type)
    if not factory:
        raise ValueError(f"不支持的策略类型: {strategy_type}")
    return factory(universe, params, initial_cash=initial_cash)


def _make_dual_ma(
    universe: list[str], params: dict[str, Any], *, initial_cash: float
) -> SignalGenerator:
    fast_p = int(params.get("fast_period", 5))
    slow_p = int(params.get("slow_period", 20))
    pct = float(params.get("position_pct", 0.2))

    def gen(
        trade_date: date,
        positions: dict[str, PositionSnapshot],
        bars_by_stock: dict[str, dict[date, DailyBar]],
    ) -> list[BacktestSignal]:
        signals: list[BacktestSignal] = []
        for code in universe:
            series = _closes_up_to(bars_by_stock.get(code, {}), trade_date)
            if len(series) < slow_p + 1:
                continue
            closes = [c for _, c in series]
            dates = [d for d, _ in series]
            if dates[-1] != trade_date:
                continue
            fast_now = _sma(closes, fast_p)
            slow_now = _sma(closes, slow_p)
            fast_prev = _sma(closes[:-1], fast_p)
            slow_prev = _sma(closes[:-1], slow_p)
            if None in (fast_now, slow_now, fast_prev, slow_prev):
                continue
            price = closes[-1]
            pos = positions.get(code)
            held = pos.total_qty if pos else 0
            # 金叉
            if fast_prev <= slow_prev and fast_now > slow_now and held == 0:
                qty = _qty_from_pct(initial_cash, price, pct)
                if qty > 0:
                    signals.append(
                        BacktestSignal(
                            code, "BUY", qty, trade_date, reason="dual_ma_golden_cross"
                        )
                    )
            # 死叉
            elif fast_prev >= slow_prev and fast_now < slow_now and held > 0:
                signals.append(
                    BacktestSignal(
                        code,
                        "SELL",
                        held,
                        trade_date,
                        reason="dual_ma_death_cross",
                    )
                )
        return signals

    return gen


def _make_bollinger(
    universe: list[str], params: dict[str, Any], *, initial_cash: float
) -> SignalGenerator:
    period = int(params.get("period", 20))
    mult = float(params.get("std_mult", 2.0))
    pct = float(params.get("position_pct", 0.2))

    def gen(
        trade_date: date,
        positions: dict[str, PositionSnapshot],
        bars_by_stock: dict[str, dict[date, DailyBar]],
    ) -> list[BacktestSignal]:
        import statistics

        signals: list[BacktestSignal] = []
        for code in universe:
            series = _closes_up_to(bars_by_stock.get(code, {}), trade_date)
            if len(series) < period:
                continue
            closes = [c for _, c in series]
            if series[-1][0] != trade_date:
                continue
            window = closes[-period:]
            mid = sum(window) / period
            std = statistics.pstdev(window) if len(window) > 1 else 0.0
            upper = mid + mult * std
            lower = mid - mult * std
            price = closes[-1]
            held = positions.get(code).total_qty if code in positions else 0
            if price <= lower and held == 0:
                qty = _qty_from_pct(initial_cash, price, pct)
                if qty:
                    signals.append(
                        BacktestSignal(
                            code, "BUY", qty, trade_date, reason="bollinger_lower"
                        )
                    )
            elif price >= upper and held > 0:
                signals.append(
                    BacktestSignal(
                        code, "SELL", held, trade_date, reason="bollinger_upper"
                    )
                )
        return signals

    return gen


def _make_rsi(
    universe: list[str], params: dict[str, Any], *, initial_cash: float
) -> SignalGenerator:
    period = int(params.get("period", 14))
    oversold = float(params.get("oversold", 30))
    overbought = float(params.get("overbought", 70))
    pct = float(params.get("position_pct", 0.2))

    def _rsi(closes: list[float]) -> float | None:
        if len(closes) < period + 1:
            return None
        gains = []
        losses = []
        for i in range(-period, 0):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - 100 / (1 + rs)

    def gen(
        trade_date: date,
        positions: dict[str, PositionSnapshot],
        bars_by_stock: dict[str, dict[date, DailyBar]],
    ) -> list[BacktestSignal]:
        signals: list[BacktestSignal] = []
        for code in universe:
            series = _closes_up_to(bars_by_stock.get(code, {}), trade_date)
            closes = [c for _, c in series]
            if not series or series[-1][0] != trade_date:
                continue
            val = _rsi(closes)
            if val is None:
                continue
            price = closes[-1]
            held = positions.get(code).total_qty if code in positions else 0
            if val <= oversold and held == 0:
                qty = _qty_from_pct(initial_cash, price, pct)
                if qty:
                    signals.append(
                        BacktestSignal(
                            code, "BUY", qty, trade_date, reason=f"rsi_oversold_{val:.1f}"
                        )
                    )
            elif val >= overbought and held > 0:
                signals.append(
                    BacktestSignal(
                        code, "SELL", held, trade_date, reason=f"rsi_overbought_{val:.1f}"
                    )
                )
        return signals

    return gen


def _make_macd(
    universe: list[str], params: dict[str, Any], *, initial_cash: float
) -> SignalGenerator:
    fast_p = int(params.get("fast_period", 12))
    slow_p = int(params.get("slow_period", 26))
    signal_p = int(params.get("signal_period", 9))
    pct = float(params.get("position_pct", 0.2))

    def gen(
        trade_date: date,
        positions: dict[str, PositionSnapshot],
        bars_by_stock: dict[str, dict[date, DailyBar]],
    ) -> list[BacktestSignal]:
        signals: list[BacktestSignal] = []
        need = slow_p + signal_p + 2
        for code in universe:
            series = _closes_up_to(bars_by_stock.get(code, {}), trade_date)
            if len(series) < need or series[-1][0] != trade_date:
                continue
            closes = [c for _, c in series]
            ema_fast = _ema_series(closes, fast_p)
            ema_slow = _ema_series(closes, slow_p)
            dif = [f - s for f, s in zip(ema_fast, ema_slow)]
            dea = _ema_series(dif, signal_p)
            if len(dif) < 2 or len(dea) < 2:
                continue
            price = closes[-1]
            held = positions.get(code).total_qty if code in positions else 0
            # 金叉
            if dif[-2] <= dea[-2] and dif[-1] > dea[-1] and held == 0:
                qty = _qty_from_pct(initial_cash, price, pct)
                if qty:
                    signals.append(
                        BacktestSignal(
                            code, "BUY", qty, trade_date, reason="macd_golden_cross"
                        )
                    )
            elif dif[-2] >= dea[-2] and dif[-1] < dea[-1] and held > 0:
                signals.append(
                    BacktestSignal(
                        code, "SELL", held, trade_date, reason="macd_death_cross"
                    )
                )
        return signals

    return gen
