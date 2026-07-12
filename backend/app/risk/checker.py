from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = structlog.get_logger()


@dataclass
class CheckResult:
    rule_code: str
    passed: bool
    severity: str
    message: str
    actual_value: float
    threshold: float


@dataclass
class RiskCheckReport:
    passed: bool
    blocked_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)


class PreTradeRiskChecker:
    def __init__(self, db: AsyncSession, monitor: Any) -> None:
        self.db = db
        self.monitor = monitor
        self._rules_loaded = False
        self.thresholds: dict[str, float] = {}

    async def _ensure_thresholds(self) -> None:
        if self._rules_loaded:
            return
        # 默认来自 settings
        self.thresholds = {
            "MAX_SINGLE_POSITION": float(settings.MAX_SINGLE_POSITION_RATIO),
            "WARN_SINGLE_POSITION": float(settings.WARN_SINGLE_POSITION_RATIO),
            "MAX_TOTAL_POSITION": float(settings.MAX_TOTAL_POSITION_RATIO),
            "MAX_DAILY_LOSS": float(settings.MAX_DAILY_LOSS_RATIO),
            "MAX_DRAWDOWN": float(settings.MAX_DRAWDOWN_RATIO),
            "MAX_ORDER_FREQ": float(settings.MAX_DAILY_ORDER_COUNT),
            "MIN_DAILY_AMOUNT": float(settings.MIN_DAILY_AMOUNT),
            "MAX_SECTOR_CONCENTRATION": float(settings.MAX_SECTOR_CONCENTRATION_RATIO),
        }
        # 若 DB 有规则表则覆盖
        try:
            result = await self.db.execute(
                text(
                    """
                    SELECT rule_code, threshold
                    FROM risk.risk_rules
                    WHERE is_enabled = TRUE
                    """
                )
            )
            for row in result.mappings().all():
                code = row["rule_code"]
                if code in self.thresholds and row["threshold"] is not None:
                    self.thresholds[code] = float(row["threshold"])
        except Exception as exc:
            logger.warning("risk_rules_load_failed", error=str(exc))
        self._rules_loaded = True

    async def check(self, order_request: dict, mode: str) -> RiskCheckReport:
        await self._ensure_thresholds()
        checks: list[CheckResult] = []
        stock = await self._get_stock(order_request["stock_code"])
        if stock is None:
            return RiskCheckReport(
                passed=False,
                blocked_by=["STOCK_NOT_FOUND"],
                checks=[
                    CheckResult(
                        "STOCK_NOT_FOUND",
                        False,
                        "BLOCK",
                        "股票代码不存在",
                        0,
                        0,
                    )
                ],
            )

        portfolio = await self.monitor.get_portfolio_snapshot(mode)
        price = order_request.get("limit_price")
        if price is None:
            price = await self._get_current_price(order_request["stock_code"])
        try:
            price_f = float(price) if price is not None else 0.0
        except (TypeError, ValueError):
            price_f = 0.0

        # 无有效价格：禁止放行（避免 order_value=0 绕过仓位检查）
        if price_f <= 0:
            invalid = CheckResult(
                rule_code="INVALID_PRICE",
                passed=False,
                severity="BLOCK",
                message="无法获取有效价格，禁止下单",
                actual_value=price_f,
                threshold=0,
            )
            await self._log_risk_event(invalid, order_request, mode)
            return RiskCheckReport(
                passed=False,
                blocked_by=["INVALID_PRICE"],
                checks=[invalid],
            )

        order_value = price_f * int(order_request["quantity"])

        if order_request["side"] == "BUY":
            checks.append(self._check_st(stock))
            checks.append(self._check_new_stock(stock))
            checks.append(
                await self._check_single_position(
                    order_request["stock_code"], order_value, portfolio
                )
            )
            checks.append(await self._check_total_position(order_value, portfolio))
            checks.extend(
                await self._check_liquidity(order_request["stock_code"], order_value)
            )
            checks.append(
                await self._check_sector_concentration(stock, order_value, portfolio)
            )

        checks.append(await self._check_daily_loss(portfolio))
        checks.append(await self._check_drawdown(portfolio))
        checks.append(await self._check_order_frequency(mode))

        blocked = [c.rule_code for c in checks if not c.passed and c.severity == "BLOCK"]
        warnings = [c.rule_code for c in checks if not c.passed and c.severity == "WARN"]

        for check in checks:
            if not check.passed:
                await self._log_risk_event(check, order_request, mode)

        return RiskCheckReport(
            passed=len(blocked) == 0,
            blocked_by=blocked,
            warnings=warnings,
            checks=checks,
        )

    def _check_st(self, stock: dict) -> CheckResult:
        is_st = stock.get("is_st", False)
        return CheckResult(
            rule_code="BLOCK_ST",
            passed=not is_st,
            severity="BLOCK",
            message="ST股票，禁止买入" if is_st else "ST检查通过",
            actual_value=1 if is_st else 0,
            threshold=0,
        )

    def _check_new_stock(self, stock: dict) -> CheckResult:
        list_date = stock.get("list_date")
        if list_date is None:
            return CheckResult(
                "BLOCK_NEW_STOCK", True, "PASS", "上市日期未知，允许", 0, 60
            )
        if isinstance(list_date, str):
            list_date = date.fromisoformat(list_date)
        days_listed = (date.today() - list_date).days
        passed = days_listed >= 60
        return CheckResult(
            rule_code="BLOCK_NEW_STOCK",
            passed=passed,
            severity="BLOCK" if not passed else "PASS",
            message=f"上市{days_listed}日，{'不足60日禁止买入' if not passed else '通过'}",
            actual_value=float(days_listed),
            threshold=60,
        )

    async def _check_single_position(
        self, stock_code: str, order_value: float, portfolio: dict
    ) -> CheckResult:
        block_threshold = self.thresholds["MAX_SINGLE_POSITION"]
        warn_threshold = self.thresholds["WARN_SINGLE_POSITION"]
        total_assets = portfolio["total_assets"]
        current_position_value = portfolio["positions"].get(stock_code, {}).get(
            "market_value", 0
        )
        new_ratio = (
            (float(current_position_value) + order_value) / total_assets
            if total_assets > 0
            else 1.0  # 无资产时视为超限
        )

        if new_ratio > block_threshold:
            return CheckResult(
                rule_code="MAX_SINGLE_POSITION",
                passed=False,
                severity="BLOCK",
                message=f"买入后{stock_code}仓位将达{new_ratio:.1%}，超过{block_threshold:.0%}",
                actual_value=new_ratio,
                threshold=block_threshold,
            )
        if new_ratio > warn_threshold:
            return CheckResult(
                rule_code="WARN_SINGLE_POSITION",
                passed=False,
                severity="WARN",
                message=f"买入后{stock_code}仓位将达{new_ratio:.1%}，接近上限",
                actual_value=new_ratio,
                threshold=warn_threshold,
            )
        return CheckResult(
            rule_code="MAX_SINGLE_POSITION",
            passed=True,
            severity="PASS",
            message=f"买入后{stock_code}仓位将达{new_ratio:.1%}",
            actual_value=new_ratio,
            threshold=block_threshold,
        )

    async def _check_total_position(self, order_value: float, portfolio: dict) -> CheckResult:
        threshold = self.thresholds["MAX_TOTAL_POSITION"]
        total_assets = portfolio["total_assets"]
        new_ratio = (
            (portfolio["total_market_value"] + order_value) / total_assets
            if total_assets > 0
            else 1.0
        )
        passed = new_ratio <= threshold
        return CheckResult(
            rule_code="MAX_TOTAL_POSITION",
            passed=passed,
            severity="BLOCK" if not passed else "PASS",
            message=f"买入后总仓位将达{new_ratio:.1%}",
            actual_value=new_ratio,
            threshold=threshold,
        )

    async def _check_daily_loss(self, portfolio: dict) -> CheckResult:
        threshold = self.thresholds["MAX_DAILY_LOSS"]
        daily_pnl_pct = portfolio.get("daily_pnl_pct", 0)
        actual_loss = abs(min(daily_pnl_pct, 0))
        passed = actual_loss <= threshold
        return CheckResult(
            rule_code="MAX_DAILY_LOSS",
            passed=passed,
            severity="BLOCK" if not passed else "PASS",
            message=f"今日已亏损{actual_loss:.2%}",
            actual_value=actual_loss,
            threshold=threshold,
        )

    async def _check_drawdown(self, portfolio: dict) -> CheckResult:
        threshold = self.thresholds["MAX_DRAWDOWN"]
        drawdown = abs(min(portfolio.get("drawdown_from_peak", 0), 0))
        passed = drawdown <= threshold
        return CheckResult(
            rule_code="MAX_DRAWDOWN",
            passed=passed,
            severity="BLOCK" if not passed else "PASS",
            message=f"当前回撤{drawdown:.2%}",
            actual_value=drawdown,
            threshold=threshold,
        )

    async def _check_order_frequency(self, mode: str) -> CheckResult:
        threshold = self.thresholds["MAX_ORDER_FREQ"]
        today_count = await self._get_today_order_count(mode)
        passed = today_count < threshold
        return CheckResult(
            rule_code="MAX_ORDER_FREQ",
            passed=passed,
            severity="BLOCK" if not passed else "PASS",
            message=f"今日已下单{today_count}次",
            actual_value=float(today_count),
            threshold=threshold,
        )

    async def _check_liquidity(self, stock_code: str, order_value: float) -> list[CheckResult]:
        quote = await self._get_today_quote(stock_code)
        results: list[CheckResult] = []
        threshold = self.thresholds["MIN_DAILY_AMOUNT"]
        daily_amount = float(quote.get("amount", 0) if quote else 0)
        passed = daily_amount >= threshold
        results.append(
            CheckResult(
                rule_code="MIN_DAILY_AMOUNT",
                passed=passed,
                severity="BLOCK" if not passed else "PASS",
                message=f"日成交额{daily_amount:,.0f}元",
                actual_value=daily_amount,
                threshold=threshold,
            )
        )
        return results

    async def _check_sector_concentration(
        self, stock: dict, order_value: float, portfolio: dict
    ) -> CheckResult:
        threshold = self.thresholds["MAX_SECTOR_CONCENTRATION"]
        sector = stock.get("sector") or "未知"
        total_assets = portfolio["total_assets"]
        sector_value = order_value
        for pos in portfolio["positions"].values():
            if pos.get("sector") == sector:
                sector_value += float(pos.get("market_value", 0))
        ratio = sector_value / total_assets if total_assets > 0 else 1.0
        passed = ratio <= threshold
        return CheckResult(
            rule_code="MAX_SECTOR_CONCENTRATION",
            passed=passed,
            severity="BLOCK" if not passed else "PASS",
            message=f"{sector}行业集中度{ratio:.1%}",
            actual_value=ratio,
            threshold=threshold,
        )

    async def _get_stock(self, code: str) -> dict | None:
        result = await self.db.execute(
            text("SELECT * FROM fundamental.stocks WHERE code = :code"),
            {"code": code},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def _get_current_price(self, code: str) -> float:
        quote = await self._get_today_quote(code)
        return float(quote.get("price", 0)) if quote else 0.0

    async def _get_today_quote(self, code: str) -> dict | None:
        from app.data.service import DataService

        svc = DataService()
        try:
            return await svc.get_quote(code)
        finally:
            await svc.close()

    async def _get_today_order_count(self, mode: str) -> int:
        result = await self.db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt FROM trade.orders
                WHERE mode = :mode AND created_at::date = CURRENT_DATE
                """
            ),
            {"mode": mode},
        )
        row = result.mappings().first()
        return int(row["cnt"]) if row else 0

    async def _log_risk_event(self, check: CheckResult, order_request: dict, mode: str) -> None:
        import json

        await self.db.execute(
            text(
                """
                INSERT INTO risk.risk_events
                (rule_code, trigger_value, threshold, action_taken, detail)
                VALUES (:rule_code, :trigger_value, :threshold, :action_taken, CAST(:detail AS jsonb))
                """
            ),
            {
                "rule_code": check.rule_code,
                "trigger_value": check.actual_value,
                "threshold": check.threshold,
                "action_taken": check.severity.lower(),
                "detail": json.dumps(
                    {
                        "message": check.message,
                        "stock_code": order_request.get("stock_code"),
                        "mode": mode,
                    }
                ),
            },
        )
