from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


class MarketRuleError(ValueError):
    pass


@dataclass(frozen=True)
class MarketRule:
    rule_type: str
    exchange: str
    board: str
    security_status: str
    effective_from: date
    effective_to: date | None
    value: Any
    source_name: str
    source_reference: str
    rule_version: str

    def applies(self, trade_date: date) -> bool:
        return self.effective_from <= trade_date and (
            self.effective_to is None or trade_date <= self.effective_to
        )


@dataclass(frozen=True)
class SecurityStatusSnapshot:
    stock_code: str
    exchange: str
    board: str
    security_status: str
    effective_from: date
    effective_to: date
    suspended: bool
    price_limit_exempt: bool
    previous_close_valid: bool
    source_name: str
    source_reference: str
    status_version: str

    def applies(self, trade_date: date) -> bool:
        return self.effective_from <= trade_date <= self.effective_to


@dataclass(frozen=True)
class ResolvedMarketRules:
    buy_lot_size: int
    sell_lot_size: int
    odd_lot_sell_policy: str
    price_tick: Decimal
    price_rounding_mode: str
    price_limit_formula_version: str
    t_plus_one: bool
    commission_rate: float
    minimum_commission: float
    stamp_duty_rate: float
    transfer_fee_rate: float
    slippage_rate: float
    price_limit_rate: float | None
    rule_versions: tuple[str, ...]


class AshareMarketRuleRegistry:
    VERSION = "ashare-market-rules-v1"
    SSE_FEES = "https://one.sse.com.cn/onething/gptz/"
    STAMP_DUTY = "https://shanxi.chinatax.gov.cn/web/detail/sx-11400-545-1780448"
    TRANSFER_FEE = "https://www.chinaclear.cn/zdjs/editor_file/20220701154723234.pdf"
    SZSE_RULES = "https://docs.static.szse.cn/www/lawrules/rule/trade/W020230217564423808793.pdf"
    SSE_RULES_2023 = "https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20250519_10779396.shtml"
    SSE_RULES_2026 = "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml"

    def __init__(self, *, slippage_rate: float = 0.002) -> None:
        self.slippage_rate = slippage_rate
        self._rules = self._build_rules()

    def _build_rules(self) -> list[MarketRule]:
        rules: list[MarketRule] = []
        for exchange in ("SH", "SZ"):
            rules.extend(
                [
                    MarketRule("buy_lot_size", exchange, "*", "NORMAL", date(2023, 4, 10), None, 100, "SSE/SZSE trading rules", self.SZSE_RULES if exchange == "SZ" else self.SSE_RULES_2023, f"{exchange}-buy-lot-2023-v1"),
                    MarketRule("sell_lot_size", exchange, "*", "NORMAL", date(2023, 4, 10), None, 100, "SSE/SZSE trading rules", self.SZSE_RULES if exchange == "SZ" else self.SSE_RULES_2023, f"{exchange}-sell-lot-2023-v1"),
                    MarketRule("odd_lot_sell_policy", exchange, "*", "NORMAL", date(2023, 4, 10), None, "FULL_ODD_LOT_ONLY", "SSE/SZSE trading rules", self.SZSE_RULES if exchange == "SZ" else self.SSE_RULES_2023, f"{exchange}-odd-lot-full-balance-v1"),
                    MarketRule("minimum_price_tick", exchange, "*", "NORMAL", date(2023, 4, 10), None, "0.01", "SSE/SZSE trading rules", self.SZSE_RULES if exchange == "SZ" else self.SSE_RULES_2023, f"{exchange}-A-share-price-tick-001-v1"),
                    MarketRule("price_rounding_mode", exchange, "*", "NORMAL", date(2023, 4, 10), None, "ROUND_HALF_UP", "SSE/SZSE trading rules", self.SZSE_RULES if exchange == "SZ" else self.SSE_RULES_2023, f"{exchange}-price-round-half-up-v1"),
                    MarketRule("price_limit_formula_version", exchange, "*", "NORMAL", date(2023, 4, 10), None, "PREV_CLOSE_RATE_TICK_V1", "SSE/SZSE trading rules", self.SZSE_RULES if exchange == "SZ" else self.SSE_RULES_2023, f"{exchange}-price-limit-formula-tick-v1"),
                    MarketRule("t_plus_one", exchange, "*", "NORMAL", date(2023, 4, 10), None, True, "SSE/SZSE trading rules", self.SZSE_RULES if exchange == "SZ" else self.SSE_RULES_2023, f"{exchange}-t1-2023-v1"),
                    MarketRule("commission_rate", exchange, "*", "NORMAL", date(2023, 8, 28), None, 0.003, "SSE investor fee disclosure (official ceiling)", self.SSE_FEES, f"{exchange}-commission-ceiling-v1"),
                    MarketRule("minimum_commission", exchange, "*", "NORMAL", date(2023, 8, 28), None, 5.0, "SSE investor fee disclosure", self.SSE_FEES, f"{exchange}-minimum-commission-v1"),
                    MarketRule("stamp_duty_sell", exchange, "*", "NORMAL", date(2023, 8, 28), None, 0.0005, "Ministry of Finance and State Taxation Administration Announcement No.39 (2023)", self.STAMP_DUTY, f"{exchange}-stamp-duty-20230828-v1"),
                    MarketRule("transfer_fee", exchange, "*", "NORMAL", date(2022, 4, 29), None, 0.00001, "China Securities Depository and Clearing Corporation", self.TRANSFER_FEE, f"{exchange}-transfer-fee-20220429-v1"),
                ]
            )
        rules.extend(
            [
                MarketRule("price_limit", "SZ", "GEM", "NORMAL", date(2020, 8, 24), None, 0.20, "Shenzhen Stock Exchange Trading Rules", self.SZSE_RULES, "SZ-GEM-limit-20200824-v1"),
                MarketRule("price_limit", "SZ", "MAIN", "NORMAL", date(2023, 4, 10), None, 0.10, "Shenzhen Stock Exchange Trading Rules", self.SZSE_RULES, "SZ-MAIN-limit-2023-v1"),
                MarketRule("price_limit", "SZ", "MAIN", "ST", date(2023, 4, 10), date(2026, 7, 5), 0.05, "Shenzhen Stock Exchange Trading Rules", self.SZSE_RULES, "SZ-MAIN-ST-limit-pre-20260706-v1"),
                MarketRule("price_limit", "SH", "MAIN", "NORMAL", date(2023, 4, 10), None, 0.10, "Shanghai Stock Exchange Trading Rules", self.SSE_RULES_2023, "SH-MAIN-limit-2023-v1"),
                MarketRule("price_limit", "SH", "STAR", "NORMAL", date(2019, 7, 22), None, 0.20, "Shanghai Stock Exchange Trading Rules", self.SSE_RULES_2023, "SH-STAR-limit-2019-v1"),
                MarketRule("price_limit", "SH", "MAIN", "ST", date(2023, 4, 10), date(2026, 7, 5), 0.05, "Shanghai Stock Exchange Trading Rules", self.SSE_RULES_2023, "SH-MAIN-ST-limit-pre-20260706-v1"),
                MarketRule("price_limit", "SH", "MAIN", "ST", date(2026, 7, 6), None, 0.10, "Shanghai Stock Exchange Trading Rules (2026)", self.SSE_RULES_2026, "SH-MAIN-ST-limit-20260706-v1"),
            ]
        )
        return rules

    def resolve(
        self, trade_date: date, status: SecurityStatusSnapshot
    ) -> ResolvedMarketRules:
        if not status.applies(trade_date):
            raise MarketRuleError(f"security status has no coverage for {status.stock_code} on {trade_date}")
        if status.security_status not in {"NORMAL", "ST"}:
            raise MarketRuleError(f"unsupported security status: {status.security_status}")
        selected = [
            self._find(name, trade_date, status)
            for name in (
                "buy_lot_size",
                "sell_lot_size",
                "odd_lot_sell_policy",
                "minimum_price_tick",
                "price_rounding_mode",
                "price_limit_formula_version",
                "t_plus_one",
                "commission_rate",
                "minimum_commission",
                "stamp_duty_sell",
                "transfer_fee",
            )
        ]
        price_rule = None
        if not status.price_limit_exempt:
            if not status.previous_close_valid:
                raise MarketRuleError("previous close is not authoritative")
            price_rule = self._find("price_limit", trade_date, status)
            selected.append(price_rule)
        values = {rule.rule_type: rule.value for rule in selected}
        return ResolvedMarketRules(
            buy_lot_size=int(values["buy_lot_size"]),
            sell_lot_size=int(values["sell_lot_size"]),
            odd_lot_sell_policy=str(values["odd_lot_sell_policy"]),
            price_tick=Decimal(str(values["minimum_price_tick"])),
            price_rounding_mode=str(values["price_rounding_mode"]),
            price_limit_formula_version=str(values["price_limit_formula_version"]),
            t_plus_one=bool(values["t_plus_one"]),
            commission_rate=float(values["commission_rate"]),
            minimum_commission=float(values["minimum_commission"]),
            stamp_duty_rate=float(values["stamp_duty_sell"]),
            transfer_fee_rate=float(values["transfer_fee"]),
            slippage_rate=self.slippage_rate,
            price_limit_rate=float(price_rule.value) if price_rule else None,
            rule_versions=tuple(sorted(rule.rule_version for rule in selected))
            + (f"slippage-model-{self.slippage_rate:.6f}-v1",),
        )

    @staticmethod
    def price_limits(
        previous_close: float | Decimal,
        limit_rate: float,
        rules: ResolvedMarketRules,
    ) -> tuple[Decimal, Decimal]:
        if rules.price_rounding_mode != "ROUND_HALF_UP":
            raise MarketRuleError(
                f"unsupported price rounding mode: {rules.price_rounding_mode}"
            )
        previous = Decimal(str(previous_close))
        rate = Decimal(str(limit_rate))
        tick = rules.price_tick
        if previous <= 0 or tick <= 0:
            raise MarketRuleError("previous close and price tick must be positive")
        up = (previous * (Decimal("1") + rate)).quantize(
            tick, rounding=ROUND_HALF_UP
        )
        down = (previous * (Decimal("1") - rate)).quantize(
            tick, rounding=ROUND_HALF_UP
        )
        return up, down

    def _find(
        self, rule_type: str, trade_date: date, status: SecurityStatusSnapshot
    ) -> MarketRule:
        matches = [
            rule
            for rule in self._rules
            if rule.rule_type == rule_type
            and rule.exchange == status.exchange
            and rule.applies(trade_date)
            and rule.board in {"*", status.board}
            and rule.security_status in {"NORMAL", status.security_status}
        ]
        exact = [rule for rule in matches if rule.security_status == status.security_status]
        matches = exact or matches
        if len(matches) != 1:
            raise MarketRuleError(
                f"market rule is missing or ambiguous: {rule_type}/{status.exchange}/{status.board}/{status.security_status}/{trade_date}"
            )
        return matches[0]

    def resolve_rule(
        self,
        rule_type: str,
        trade_date: date,
        status: SecurityStatusSnapshot,
    ) -> MarketRule:
        return self._find(rule_type, trade_date, status)

    def lineage(self, trade_date: date, statuses: list[SecurityStatusSnapshot]) -> list[dict[str, Any]]:
        versions: dict[str, dict[str, Any]] = {}
        for status in statuses:
            resolved = self.resolve(trade_date, status)
            for version in resolved.rule_versions:
                versions[version] = {"rule_version": version}
        return [versions[key] for key in sorted(versions)]

    def records(self) -> list[dict[str, Any]]:
        return [asdict(rule) for rule in sorted(self._rules, key=lambda item: item.rule_version)]
