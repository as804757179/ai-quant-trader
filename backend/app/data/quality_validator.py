from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class QualityResult:
    passed: bool
    score: float
    reasons: list[str] = field(default_factory=list)


class KlineQualityValidator:
    """Pure validation for one import batch before certification."""

    REQUIRED = ("stock_code", "period", "time", "open", "high", "low", "close", "volume", "amount")

    def validate_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        provider: str,
        source: str,
        is_synthetic: bool = False,
    ) -> QualityResult:
        reasons: list[str] = []
        if not rows:
            reasons.append("rows are required")
        if not provider or provider.lower() == "unknown":
            reasons.append("provider is required")
        if not source or source.lower() == "unknown":
            reasons.append("source is required")
        if is_synthetic or source.lower() == "synthetic":
            reasons.append("synthetic data cannot be certified")
        seen_days: set[tuple[str, str, str]] = set()
        hours: set[int] = set()
        for row in rows:
            reasons.extend(self._validate_row(row))
            if str(row.get("period")) == "1d" and row.get("time"):
                ts = self._parse_time(row["time"])
                if ts is None:
                    continue
                hours.add(ts.hour)
                key = (str(row.get("stock_code")), str(row.get("period")), ts.date().isoformat())
                if key in seen_days:
                    reasons.append("duplicate natural-day kline")
                seen_days.add(key)
        if hours and hours != {15}:
            reasons.append("daily bars must normalize to 15:00")
        unique = list(dict.fromkeys(reasons))
        score = max(0.0, 100.0 - min(100.0, 20.0 * len(unique)))
        return QualityResult(passed=not unique, score=score, reasons=unique)

    def _validate_row(self, row: dict[str, Any]) -> list[str]:
        reasons = [f"missing {name}" for name in self.REQUIRED if row.get(name) is None or row.get(name) == ""]
        if reasons:
            return reasons
        try:
            open_, high, low, close = (float(row[k]) for k in ("open", "high", "low", "close"))
            if min(open_, high, low, close) <= 0 or high < max(open_, close, low) or low > min(open_, close, high):
                reasons.append("invalid OHLC")
            if float(row["volume"]) <= 0:
                reasons.append("volume must be positive")
            if float(row["amount"]) <= 0:
                reasons.append("amount must be positive")
            if self._parse_time(row["time"]) is None:
                reasons.append("invalid time")
        except (TypeError, ValueError):
            reasons.append("invalid numeric value")
        return reasons

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
