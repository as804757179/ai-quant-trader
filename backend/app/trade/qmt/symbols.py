"""A 股代码与 QMT 合约代码互转。"""

from __future__ import annotations


def to_qmt_symbol(code: str) -> str:
    """000001 / 000001.SZ -> 000001.SZ"""
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("空股票代码")
    if "." in code:
        return code
    pure = code
    if pure.startswith(("5", "6", "9")):
        return f"{pure}.SH"
    if pure.startswith(("0", "1", "2", "3")):
        return f"{pure}.SZ"
    if pure.startswith(("4", "8")):
        return f"{pure}.BJ"
    return f"{pure}.SZ"


def from_qmt_symbol(symbol: str) -> str:
    """000001.SZ -> 000001"""
    symbol = (symbol or "").strip().upper()
    if "." in symbol:
        return symbol.split(".", 1)[0]
    return symbol
