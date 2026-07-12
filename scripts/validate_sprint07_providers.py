from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone

import requests
from py_mini_racer import py_mini_racer


STOCKS = ("300308.SZ", "603986.SH", "300502.SZ")
AKSHARE_COMMIT = "fcdbf25aa864a218c54864c3f6ab6a2ed19cce28"
DECODER_URL = (
    "https://raw.githubusercontent.com/akfamily/akshare/"
    f"{AKSHARE_COMMIT}/akshare/stock/cons.py"
)
SOHU_URL = "https://q.stock.sohu.com/hisHq"
TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SINA_URL = "https://finance.sina.com.cn/realstock/company/{symbol}/hisdata_klc2/klc_kl.js"


def _prefix(symbol: str) -> str:
    code, exchange = symbol.split(".")
    return exchange.lower() + code


def fetch_sohu(symbol: str, start: date, end: date) -> tuple[dict[str, dict], str]:
    code = symbol.split(".", 1)[0]
    response = requests.get(
        SOHU_URL,
        params={
            "code": f"cn_{code}",
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "stat": "1",
            "order": "D",
            "period": "d",
            "rt": "json",
        },
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://q.stock.sohu.com/"},
    )
    response.raise_for_status()
    payload = json.loads(response.content.decode("gb18030"))
    raw_rows = payload[0]["hq"]
    rows = {
        row[0]: {
            "open": float(row[1]),
            "close": float(row[2]),
            "high": float(row[6]),
            "low": float(row[5]),
            "volume": int(float(row[7]) * 100),
            "amount": float(row[8]) * 10_000,
        }
        for row in raw_rows
        if start <= date.fromisoformat(row[0]) <= end
    }
    return rows, hashlib.sha256(response.content).hexdigest()


def fetch_tencent(symbol: str, year: int, adjustment: str) -> dict[str, dict]:
    prefixed = _prefix(symbol)
    response = requests.get(
        TENCENT_URL,
        params={
            "param": (
                f"{prefixed},day,{year}-01-01,{year}-12-31,640,{adjustment}"
            )
        },
        timeout=30,
    )
    response.raise_for_status()
    key = f"{adjustment}day" if adjustment else "day"
    raw_rows = response.json()["data"][prefixed][key]
    return {
        row[0]: {
            "open": float(row[1]),
            "close": float(row[2]),
            "high": float(row[3]),
            "low": float(row[4]),
        }
        for row in raw_rows
    }


def _load_sina_decoder() -> str:
    source = requests.get(DECODER_URL, timeout=30)
    source.raise_for_status()
    match = re.search(r'hk_js_decode\s*=\s*r?"""(.*?)"""', source.text, re.S)
    if not match:
        raise ValueError("pinned Sina decoder was not found")
    return match.group(1)


def fetch_sina(symbol: str, decoder: str) -> tuple[dict[str, dict], str]:
    prefixed = _prefix(symbol)
    response = requests.get(SINA_URL.format(symbol=prefixed), timeout=30)
    response.raise_for_status()
    encoded = response.text.split("=", 1)[1].split(";", 1)[0].replace('"', "")
    runtime = py_mini_racer.MiniRacer()
    runtime.eval(decoder)
    raw_rows = runtime.call("d", encoded)
    rows = {
        row["date"][:10]: {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "amount": float(row["amount"]),
        }
        for row in raw_rows
        if "2026-06-01" <= row["date"] <= "2026-06-30"
    }
    return rows, hashlib.sha256(response.content).hexdigest()


def adjustment_evidence() -> dict:
    checks = []
    for symbol in STOCKS:
        for year in (2020, 2023, 2025):
            sohu, _ = fetch_sohu(symbol, date(year, 1, 1), date(year, 12, 31))
            provider_rows = {
                name: fetch_tencent(symbol, year, name if name != "raw" else "")
                for name in ("raw", "qfq", "hfq")
            }
            errors = {}
            for name, rows in provider_rows.items():
                common = sorted(set(sohu) & set(rows))
                errors[name] = max(
                    abs(sohu[day][field] - rows[day][field])
                    for day in common
                    for field in ("open", "high", "low", "close")
                )
            checks.append(
                {
                    "stock_code": symbol,
                    "year": year,
                    "common_days": len(set(sohu) & set(provider_rows["raw"])),
                    "max_ohlc_abs_error": errors,
                }
            )
    raw_proven = all(item["max_ohlc_abs_error"]["raw"] <= 0.01 for item in checks)
    alternatives_differ = any(
        item["max_ohlc_abs_error"][name] > 0.01
        for item in checks
        for name in ("qfq", "hfq")
    )
    return {
        "conclusion": "raw" if raw_proven and alternatives_differ else "unknown",
        "method": "Sohu OHLC compared with explicit Tencent raw/qfq/hfq responses",
        "tolerance_cny": 0.01,
        "checks": checks,
    }


def cross_provider_evidence() -> dict:
    decoder = _load_sina_decoder()
    output = []
    for symbol in STOCKS:
        sohu, sohu_hash = fetch_sohu(symbol, date(2026, 6, 1), date(2026, 6, 30))
        sina, sina_hash = fetch_sina(symbol, decoder)
        common = sorted(set(sohu) & set(sina))
        comparisons = []
        for day in common[:5]:
            fields = {}
            review_required = False
            for field in ("open", "high", "low", "close", "volume", "amount"):
                left = sohu[day][field]
                right = sina[day][field]
                absolute = abs(left - right)
                relative = absolute / abs(right) if right else None
                if field in ("open", "high", "low", "close"):
                    passed = absolute <= 0.01
                    tolerance = "abs<=0.01 CNY"
                elif field == "volume":
                    passed = absolute <= 100
                    tolerance = "abs<=100 shares"
                else:
                    passed = absolute <= 5000 and (relative or 0) <= 0.000001
                    tolerance = "abs<=5000 CNY and rel<=1e-6"
                review_required = review_required or not passed
                fields[field] = {
                    "sohu": left,
                    "sina": right,
                    "absolute_difference": absolute,
                    "relative_difference": relative,
                    "tolerance": tolerance,
                    "passed": passed,
                }
            comparisons.append(
                {"trading_date": day, "fields": fields, "review_required": review_required}
            )
        output.append(
            {
                "stock_code": symbol,
                "sohu_rows": len(sohu),
                "sina_rows": len(sina),
                "common_rows": len(common),
                "primary_only_dates": sorted(set(sohu) - set(sina)),
                "secondary_only_dates": sorted(set(sina) - set(sohu)),
                "sohu_response_hash": sohu_hash,
                "sina_response_hash": sina_hash,
                "comparisons": comparisons,
                "review_required": set(sohu) != set(sina)
                or len(comparisons) < 5
                or any(row["review_required"] for row in comparisons),
            }
        )
    return {
        "primary_provider": "sohu",
        "secondary_provider": "sina",
        "secondary_provider_mode": "read_only_no_fallback",
        "decoder_source": DECODER_URL,
        "stocks": output,
    }


def main() -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "adjustment_evidence": adjustment_evidence(),
        "cross_provider_evidence": cross_provider_evidence(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
