from __future__ import annotations

import json
from datetime import date, datetime, timezone

import requests

from validate_sprint07_providers import (
    STOCKS,
    _load_sina_decoder,
    _prefix,
    fetch_sina,
    fetch_sohu,
)


TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SINA_DAILY_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/"
    "json_v2.php/CN_MarketData.getKLineData"
)


def fetch_tencent_day(symbol: str) -> dict[str, float]:
    prefixed = _prefix(symbol)
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        TENCENT_URL,
        params={"param": f"{prefixed},day,2026-06-30,2026-06-30,10,"},
        timeout=30,
    )
    response.raise_for_status()
    row = response.json()["data"][prefixed]["day"][0]
    return {
        "open": float(row[1]),
        "close": float(row[2]),
        "high": float(row[3]),
        "low": float(row[4]),
        "volume": float(row[5]) * 100,
    }


def fetch_sina_daily_day(symbol: str) -> dict[str, float]:
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        SINA_DAILY_URL,
        params={"symbol": _prefix(symbol), "scale": 240, "ma": "no", "datalen": 1023},
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
        timeout=30,
    )
    response.raise_for_status()
    row = next(item for item in response.json() if item["day"].startswith("2026-06-30"))
    return {
        "open": float(row["open"]),
        "close": float(row["close"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "volume": float(row["volume"]),
    }


def main() -> None:
    decoder = _load_sina_decoder()
    stocks = []
    for symbol in STOCKS:
        sohu_rows, _ = fetch_sohu(symbol, date(2026, 6, 30), date(2026, 6, 30))
        sohu = sohu_rows["2026-06-30"]
        tencent = fetch_tencent_day(symbol)
        sina_daily = fetch_sina_daily_day(symbol)
        sina_archive, _ = fetch_sina(symbol, decoder)
        comparisons = {}
        for field in ("open", "high", "low", "close", "volume"):
            tolerance = 0.01 if field != "volume" else 100
            comparisons[field] = {
                "sohu": sohu[field],
                "tencent": tencent[field],
                "sina_daily": sina_daily[field],
                "max_absolute_difference": max(
                    abs(sohu[field] - tencent[field]),
                    abs(sohu[field] - sina_daily[field]),
                ),
                "tolerance": tolerance,
            }
        stocks.append(
            {
                "stock_code": symbol,
                "is_confirmed_trading_day": True,
                "sina_archive_has_date": "2026-06-30" in sina_archive,
                "sina_daily_has_date": True,
                "tencent_has_date": True,
                "ohlcv_comparisons": comparisons,
                "amount_cross_provider_status": "unresolved",
                "missingness_conclusion": "provider_missing",
                "readiness_conclusion": "review_required",
            }
        )
    print(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "missing_endpoint": "sina_klc_kl_archive",
                "conclusion": "endpoint_specific_provider_missing",
                "stocks": stocks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
