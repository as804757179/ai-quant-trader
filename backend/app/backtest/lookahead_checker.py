from __future__ import annotations

import ast
import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)


@dataclass
class LookaheadIssue:
    severity: str  # ERROR | WARNING
    location: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "location": self.location,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class LookaheadCheckResult:
    passed: bool
    issues: list[dict[str, str]] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0

    @classmethod
    def from_issues(cls, issues: list[LookaheadIssue]) -> LookaheadCheckResult:
        errors = [i for i in issues if i.severity == "ERROR"]
        warnings = [i for i in issues if i.severity == "WARNING"]
        return cls(
            passed=len(errors) == 0,
            issues=[i.to_dict() for i in issues],
            error_count=len(errors),
            warning_count=len(warnings),
        )


class LookaheadError(Exception):
    """存在 ERROR 级别未来函数问题时抛出，阻断回测。"""

    def __init__(self, result: LookaheadCheckResult) -> None:
        self.result = result
        super().__init__(
            f"Lookahead check failed: {result.error_count} error(s), "
            f"{result.warning_count} warning(s)"
        )


# 源码字符串级危险模式（补充 AST 未覆盖的 SQL/文本）
_CODE_PATTERNS: list[tuple[str, str, str, str]] = [
    (
        r"report_date\s*<=",
        "ERROR",
        "财务数据查询使用 report_date 过滤",
        "改用 publish_date <= :date，确保只用已发布财报",
    ),
    (
        r"ORDER\s+BY\s+report_date",
        "ERROR",
        "财务数据按 report_date 排序",
        "改用 ORDER BY publish_date DESC",
    ),
    (
        r"\.shift\s*\(\s*-",
        "ERROR",
        "使用负向 shift() 引入未来标签/数据",
        "仅使用 shift(正数) 或 shift(1) 获取历史数据",
    ),
    (
        r"fit_transform\s*\([^)]*\)",
        "WARNING",
        "在全量数据上 fit_transform 可能导致归一化泄露",
        "先在训练集 fit，再在测试集 transform",
    ),
]


class _AstLookaheadVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.issues: list[LookaheadIssue] = []

    def visit_Call(self, node: ast.Call) -> None:
        self._check_negative_shift(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._check_iloc_negative_index(node)
        self.generic_visit(node)

    def _check_negative_shift(self, node: ast.Call) -> None:
        func_name = self._call_name(node)
        if func_name != "shift" or not node.args:
            return
        if self._is_negative(node.args[0]):
            self.issues.append(
                LookaheadIssue(
                    severity="ERROR",
                    location=f"Line {node.lineno}",
                    message="检测到 shift(负数) — 引入未来数据",
                    suggestion="使用 shift(1) 等正向偏移获取历史数据",
                )
            )

    def _check_iloc_negative_index(self, node: ast.Subscript) -> None:
        if not isinstance(node.value, ast.Attribute):
            return
        if node.value.attr != "iloc":
            return
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
            if node.slice.value < 0:
                self.issues.append(
                    LookaheadIssue(
                        severity="WARNING",
                        location=f"Line {node.lineno}",
                        message="检测到 iloc 负索引 — 可能使用当日/未来 bar",
                        suggestion="信号生成应基于昨日及之前数据，避免 iloc[-1] 含当日收盘",
                    )
                )
        elif isinstance(node.slice, ast.UnaryOp) and isinstance(node.slice.op, ast.USub):
            self.issues.append(
                LookaheadIssue(
                    severity="WARNING",
                    location=f"Line {node.lineno}",
                    message="检测到 iloc 负索引 — 可能使用当日/未来 bar",
                    suggestion="信号生成应基于昨日及之前数据",
                )
            )

    @staticmethod
    def _call_name(node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        if isinstance(node.func, ast.Name):
            return node.func.id
        return None

    @staticmethod
    def _is_negative(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value < 0
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return True
        return False


class LookaheadChecker:
    """回测启动前自动检测未来函数问题。"""

    def check(
        self,
        strategy_code: str,
        *,
        financial_data_used: bool = True,
    ) -> LookaheadCheckResult:
        issues: list[LookaheadIssue] = []

        if strategy_code and strategy_code.strip():
            issues.extend(self._check_ast(strategy_code))
            issues.extend(self._check_code_patterns(strategy_code))
            if financial_data_used:
                issues.extend(self._check_financial_code_usage(strategy_code))

        if financial_data_used:
            try:
                issues.extend(asyncio.run(self._check_financial_data_db()))
            except Exception as exc:
                logger.warning("lookahead_db_check_skipped", error=str(exc))

        return LookaheadCheckResult.from_issues(self._dedupe_issues(issues))

    def _check_ast(self, strategy_code: str) -> list[LookaheadIssue]:
        try:
            tree = ast.parse(strategy_code)
        except SyntaxError as exc:
            return [
                LookaheadIssue(
                    severity="ERROR",
                    location=f"Line {exc.lineno or 0}",
                    message=f"策略代码语法错误: {exc.msg}",
                    suggestion="修复语法错误后重新提交回测",
                )
            ]

        visitor = _AstLookaheadVisitor()
        visitor.visit(tree)
        return visitor.issues

    def _check_code_patterns(self, strategy_code: str) -> list[LookaheadIssue]:
        issues: list[LookaheadIssue] = []
        for pattern, severity, message, suggestion in _CODE_PATTERNS:
            for match in re.finditer(pattern, strategy_code, re.IGNORECASE):
                line_no = strategy_code[: match.start()].count("\n") + 1
                issues.append(
                    LookaheadIssue(
                        severity=severity,
                        location=f"Line {line_no}",
                        message=message,
                        suggestion=suggestion,
                    )
                )
        return issues

    def _check_financial_code_usage(self, strategy_code: str) -> list[LookaheadIssue]:
        issues: list[LookaheadIssue] = []
        uses_report = bool(re.search(r"report_date", strategy_code, re.IGNORECASE))
        uses_publish = bool(re.search(r"publish_date", strategy_code, re.IGNORECASE))

        if uses_report and not uses_publish:
            issues.append(
                LookaheadIssue(
                    severity="ERROR",
                    location="financial_query",
                    message="策略引用 report_date 但未使用 publish_date",
                    suggestion="财务数据必须按 publish_date（公告发布日）过滤，不可用 report_date",
                )
            )
        return issues

    async def _check_financial_data_db(self) -> list[LookaheadIssue]:
        from app.db import get_db

        issues: list[LookaheadIssue] = []
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT stock_code, report_date, publish_date
                    FROM fundamental.financial_reports
                    WHERE publish_date IS NULL
                       OR publish_date < report_date
                    LIMIT 50
                    """
                )
            )
            rows = result.mappings().all()

        for row in rows:
            issues.append(
                LookaheadIssue(
                    severity="ERROR",
                    location=f"financial_reports:{row['stock_code']}:{row['report_date']}",
                    message="财务记录 publish_date 缺失或早于 report_date",
                    suggestion="补齐 publish_date 为实际公告发布日，回测查询使用 publish_date",
                )
            )
        return issues

    @staticmethod
    def _dedupe_issues(issues: list[LookaheadIssue]) -> list[LookaheadIssue]:
        seen: set[tuple[str, str, str]] = set()
        unique: list[LookaheadIssue] = []
        for issue in issues:
            key = (issue.severity, issue.location, issue.message)
            if key in seen:
                continue
            seen.add(key)
            unique.append(issue)
        return unique