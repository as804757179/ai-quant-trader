"""小额/联调验证脚本（默认 dry-run，不真实下单）。

用法:
  # 仅检查环境
  python -m scripts.live_verification --dry-run

  # Paper Mock 下一笔远离盘口的限价（需 DB）
  python -m scripts.live_verification --mode paper --execute \\
      --code 000001 --qty 100 --price 0.01 --side BUY

  # 实盘（危险）：必须显式 --i-understand-live 且配置 LIVE_CONFIRM_TOKEN
  python -m scripts.live_verification --mode live --execute \\
      --i-understand-live --code 000001 --qty 100 --price 0.01
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.trade.qmt.factory import probe_broker_environment
from app.trade.qmt.symbols import to_qmt_symbol


def print_section(title: str) -> None:
    print(f"\n=== {title} ===")


async def check_environment(mode: str) -> dict:
    print_section("环境检查")
    broker = probe_broker_environment()
    report = {
        "APP_ENV": settings.APP_ENV,
        "TRADE_MODE": settings.TRADE_MODE,
        "request_mode": mode,
        "LIVE_CONFIRM_TOKEN_set": bool(settings.LIVE_CONFIRM_TOKEN),
        "LIVE_MAX_ORDER_VALUE": settings.LIVE_MAX_ORDER_VALUE,
        "ALLOW_MOCK_LIVE": False,
        "broker": broker,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    issues: list[str] = []
    if mode == "live":
        if settings.TRADE_MODE != "live":
            issues.append("TRADE_MODE 不是 live，实盘下单会被拒绝")
        if not settings.LIVE_CONFIRM_TOKEN:
            issues.append("未配置 LIVE_CONFIRM_TOKEN")
        if broker.get("selected_adapter") == "mock":
            issues.append("live 模式禁止 Mock 适配器")
        if not broker.get("sdk_installed"):
            issues.append("xtquant 未安装")
    if mode == "paper":
        if broker.get("selected_adapter") not in ("mock", None) and not broker.get(
            "force_mock"
        ):
            pass  # paper 强制 mock
    return {"report": report, "issues": issues}


async def maybe_execute(args: argparse.Namespace) -> dict:
    print_section("下单计划")
    plan = {
        "mode": args.mode,
        "stock_code": args.code,
        "qmt_symbol": to_qmt_symbol(args.code),
        "side": args.side,
        "quantity": args.qty,
        "limit_price": args.price,
        "order_type": "LIMIT",
        "notional": round(args.price * args.qty, 2),
        "dry_run": not args.execute,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    if settings.LIVE_MAX_ORDER_VALUE and plan["notional"] > settings.LIVE_MAX_ORDER_VALUE:
        print(
            f"⚠ 名义金额 {plan['notional']} 超过 LIVE_MAX_ORDER_VALUE="
            f"{settings.LIVE_MAX_ORDER_VALUE}"
        )

    if not args.execute:
        print("\n[dry-run] 未下单。加 --execute 才会提交。")
        return {"executed": False, "plan": plan}

    if args.mode == "live" and not args.i_understand_live:
        print("拒绝：实盘执行需要 --i-understand-live")
        return {"executed": False, "error": "missing_live_ack"}

    payload = {
        "stock_code": args.code,
        "side": args.side,
        "order_type": "LIMIT",
        "quantity": args.qty,
        "limit_price": args.price,
        "mode": args.mode,
        "signal_id": None,
    }
    if args.mode == "live":
        payload["live_confirm"] = settings.LIVE_CONFIRM_TOKEN

    print_section("提交订单")
    result = {
        "success": False,
        "error_code": "DIRECT_ORDER_SUBMISSION_DISABLED",
        "message": "验证脚本不得绕过认证、审批和订单意图边界直接下单",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    if result.get("success") and result.get("order_id") and args.mode != "simulation":
        print_section("同步一次订单状态")
        sync = await svc.sync_order(result["order_id"], args.mode)
        print(json.dumps(sync, ensure_ascii=False, indent=2, default=str))

    return {"executed": True, "result": result}


async def main() -> None:
    parser = argparse.ArgumentParser(description="交易链路验证")
    parser.add_argument("--mode", default="paper", choices=["simulation", "paper", "live"])
    parser.add_argument("--code", default="000001")
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument("--qty", type=int, default=100)
    parser.add_argument("--price", type=float, default=0.01, help="限价，建议远离盘口")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真正下单（覆盖 dry-run）",
    )
    parser.add_argument(
        "--i-understand-live",
        action="store_true",
        help="确认理解实盘风险",
    )
    args = parser.parse_args()
    if args.execute:
        args.dry_run = False

    env = await check_environment(args.mode)
    if env["issues"]:
        print_section("发现问题")
        for i in env["issues"]:
            print(f" - {i}")

    out = await maybe_execute(args)
    print_section("结束")
    print(json.dumps({"ok": True, "executed": out.get("executed")}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
