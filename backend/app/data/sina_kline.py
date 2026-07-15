"""新浪 K 线直连（a-stock-data 不可用时的后端降级）。"""

from __future__ import annotations

import httpx

_SCALE = {
    "1min": 1,
    "5min": 5,
    "15min": 15,
    "30min": 30,
    "60min": 60,
    "1d": 240,
    "1w": 1200,
    "1M": 7200,
}


def _symbol(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"sh{c}"
    return f"sz{c}"


async def fetch_sina_kline(code: str, period: str, limit: int = 200) -> list[dict]:
    scale = _SCALE.get(period)
    # 1min 常为空，用 5min 顶替
    if scale is None:
        return []
    scales = [scale]
    if period == "1min":
        scales = [1, 5]

    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/"
        "json_v2.php/CN_MarketData.getKLineData"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.sina.com.cn",
    }

    async with httpx.AsyncClient(trust_env=False, timeout=25.0) as client:
        for sc in scales:
            try:
                resp = await client.get(
                    url,
                    params={
                        "symbol": _symbol(code),
                        "scale": sc,
                        "ma": "no",
                        "datalen": min(int(limit), 1023),
                    },
                    headers=headers,
                )
                resp.raise_for_status()
                text = (resp.text or "").strip()
                if not text or text == "null":
                    continue
                data = resp.json()
            except Exception:
                continue
            if not isinstance(data, list) or not data:
                continue
            rows: list[dict] = []
            for row in data:
                try:
                    day = str(row.get("day") or "")
                    o = float(row.get("open") or 0)
                    h = float(row.get("high") or 0)
                    l = float(row.get("low") or 0)
                    c = float(row.get("close") or 0)
                    vol = int(float(row.get("volume") or 0))
                    if " " in day:
                        d, hm = day.split(" ", 1)
                        time_iso = (
                            f"{d}T{hm}+08:00" if ":" in hm else f"{d}T{hm}:00+08:00"
                        )
                    else:
                        time_iso = f"{day}T15:00:00+08:00"
                    rows.append(
                        {
                            "time": time_iso,
                            "open": o,
                            "high": h,
                            "low": l,
                            "close": c,
                            "volume": vol,
                            "amount": 0.0,
                            "adj_factor": 1.0,
                        }
                    )
                except (TypeError, ValueError):
                    continue
            rows.sort(key=lambda x: x["time"])
            if rows:
                return rows[-limit:]
    return []
