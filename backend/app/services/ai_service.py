from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text

from app.ai.orchestrator import AgentOrchestrator
from app.ai.schemas import AgentResult
from app.core.config import settings
from app.data.service import DataService
from app.db import get_db
from app.schemas.ai import (
    AgentResultSummary,
    AnalyzeResponseData,
    SignalHistoryItem,
    SignalHistoryResponse,
    SignalListItem,
    SignalListResponse,
    SignalPayload,
)

logger = structlog.get_logger(__name__)


class AnalysisError(Exception):
    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AIService:
    ORCHESTRATOR_TIMEOUT = 45

    def __init__(
        self,
        data_service: DataService | None = None,
        orchestrator: AgentOrchestrator | None = None,
    ) -> None:
        self.data_service = data_service or DataService()
        self.orchestrator = orchestrator or AgentOrchestrator()

    async def close(self) -> None:
        await self.data_service.close()

    async def analyze(
        self,
        code: str,
        *,
        force_refresh: bool = False,
        strategy_id: int | None = None,
    ) -> AnalyzeResponseData:
        code = code.strip()
        if not self._is_valid_code_format(code):
            raise AnalysisError(f"无效的股票代码格式: {code}", 400)

        if not await self._stock_exists(code):
            raise AnalysisError(f"股票代码 {code} 不存在", 404)

        logger.info(
            "ai_analyze_start",
            stock_code=code,
            force_refresh=force_refresh,
            strategy_id=strategy_id,
        )

        if not force_refresh:
            cached = await self.get_valid_signal(code)
            if cached:
                logger.info("ai_analyze_cache_hit", stock_code=code, signal_id=cached.signal_id)
                return cached

        try:
            context = await self.data_service.get_full_context(code)
        except Exception as exc:
            logger.error("ai_context_failed", stock_code=code, error=str(exc), exc_info=True)
            raise AnalysisError("数据上下文构建失败", 503) from exc

        if not context.get("price"):
            raise AnalysisError(f"无法获取股票 {code} 的有效行情数据", 503)

        try:
            result = await asyncio.wait_for(
                self.orchestrator.run(code, context),
                timeout=self.ORCHESTRATOR_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            logger.error("ai_orchestrator_timeout", stock_code=code)
            raise AnalysisError("AI 分析超时，请稍后重试", 503) from exc
        except Exception as exc:
            logger.error(
                "ai_orchestrator_failed",
                stock_code=code,
                error=str(exc),
                exc_info=True,
            )
            raise AnalysisError(f"AI 分析失败: {exc}", 503) from exc

        signal_id = await self._save_signal(
            code=code,
            result=result,
            strategy_id=strategy_id,
            data_quality_score=context.get("data_quality_score"),
        )

        response = self._build_response(
            code=code,
            result=result,
            signal_id=signal_id,
            data_quality_score=context.get("data_quality_score"),
        )
        logger.info(
            "ai_analyze_done",
            stock_code=code,
            signal_id=signal_id,
            action=response.signal.action,
            confidence=response.signal.confidence,
            latency_ms=response.latency_ms,
        )
        await self._maybe_publish_signal(code, response)
        return response

    async def get_valid_signal(self, code: str) -> AnalyzeResponseData | None:
        async with get_db() as db:
            row = await db.execute(
                text(
                    """
                    SELECT id, stock_code, action, confidence, risk_level, price_at,
                           reason, agent_votes, raw_agent_output, signal_time, valid_until
                    FROM ai.signals
                    WHERE stock_code = :code
                      AND status = 'active'
                      AND (valid_until IS NULL OR valid_until > NOW())
                    ORDER BY signal_time DESC
                    LIMIT 1
                    """
                ),
                {"code": code},
            )
            record = row.mappings().first()
            if not record:
                return None

        raw_output = record.get("raw_agent_output") or {}
        if isinstance(raw_output, str):
            raw_output = json.loads(raw_output)

        agent_votes = record.get("agent_votes") or {}
        if isinstance(agent_votes, str):
            agent_votes = json.loads(agent_votes)

        scores = raw_output.get("scores") or {}
        agent_results = self._agent_votes_to_summaries(agent_votes)
        signal = SignalPayload(
            id=str(record["id"]),
            action=record["action"],
            confidence=float(record["confidence"]),
            raw_confidence=raw_output.get("raw_confidence"),
            risk_level=record["risk_level"],
            price_at=float(record["price_at"]) if record.get("price_at") else None,
            reason=record["reason"],
            scores=scores,
            degraded_agents=raw_output.get("degraded_agents") or [],
            signal_time=record["signal_time"].isoformat()
            if record.get("signal_time")
            else None,
            valid_until=record["valid_until"].isoformat()
            if record.get("valid_until")
            else None,
        )
        return AnalyzeResponseData(
            code=code,
            signal=signal,
            scores=scores,
            reason=record["reason"],
            agent_results=agent_results,
            agent_statuses=raw_output.get("agent_statuses") or {},
            latency_ms=raw_output.get("latency_ms", 0),
            from_cache=True,
            signal_id=str(record["id"]),
            data_quality_score=raw_output.get("data_quality_score"),
        )

    async def _save_signal(
        self,
        code: str,
        result: dict[str, Any],
        strategy_id: int | None,
        data_quality_score: float | None,
    ) -> str:
        signal = result["signal"]
        agent_results: dict[str, AgentResult] = result.get("agent_results", {})
        agent_votes = {
            name: ar.output for name, ar in agent_results.items() if isinstance(ar, AgentResult)
        }
        raw_agent_output = {
            "scores": signal.get("scores", {}),
            "raw_confidence": signal.get("raw_confidence"),
            "degraded_agents": signal.get("degraded_agents", []),
            "agent_statuses": result.get("agent_statuses", {}),
            "latency_ms": result.get("latency_ms", 0),
            "data_quality_score": data_quality_score,
        }

        signal_id = signal.get("id")
        valid_until = signal.get("valid_until")
        signal_time = signal.get("signal_time") or datetime.utcnow().isoformat()

        async with get_db() as db:
            insert = await db.execute(
                text(
                    """
                    INSERT INTO ai.signals (
                        id, stock_code, strategy_id, action, confidence, risk_level,
                        price_at, reason, agent_votes, raw_agent_output,
                        signal_time, valid_until, status
                    ) VALUES (
                        COALESCE(:id::uuid, uuid_generate_v4()),
                        :stock_code, :strategy_id, :action, :confidence, :risk_level,
                        :price_at, :reason, :agent_votes::jsonb, :raw_agent_output::jsonb,
                        :signal_time::timestamptz, :valid_until::timestamptz, 'active'
                    )
                    RETURNING id
                    """
                ),
                {
                    "id": signal_id,
                    "stock_code": code,
                    "strategy_id": strategy_id,
                    "action": signal.get("action", "HOLD"),
                    "confidence": signal.get("confidence", 0),
                    "risk_level": signal.get("risk_level", "MEDIUM"),
                    "price_at": signal.get("price_at") or 0,
                    "reason": signal.get("reason", ""),
                    "agent_votes": json.dumps(agent_votes, ensure_ascii=False, default=str),
                    "raw_agent_output": json.dumps(
                        raw_agent_output, ensure_ascii=False, default=str
                    ),
                    "signal_time": signal_time,
                    "valid_until": valid_until,
                },
            )
            saved_id = str(insert.scalar_one())

            for name, agent_result in agent_results.items():
                if not isinstance(agent_result, AgentResult):
                    continue
                await db.execute(
                    text(
                        """
                        INSERT INTO ai.agent_logs (
                            signal_id, stock_code, agent_name, model_used,
                            input_tokens, output_tokens, latency_ms,
                            status, error_msg, output
                        ) VALUES (
                            :signal_id::uuid, :stock_code, :agent_name, :model_used,
                            :input_tokens, :output_tokens, :latency_ms,
                            :status, :error_msg, :output::jsonb
                        )
                        """
                    ),
                    {
                        "signal_id": saved_id,
                        "stock_code": code,
                        "agent_name": agent_result.agent_name,
                        "model_used": agent_result.model,
                        "input_tokens": agent_result.input_tokens,
                        "output_tokens": agent_result.output_tokens,
                        "latency_ms": agent_result.latency_ms,
                        "status": agent_result.status,
                        "error_msg": agent_result.error_msg,
                        "output": json.dumps(
                            agent_result.output, ensure_ascii=False, default=str
                        ),
                    },
                )

        logger.info("ai_signal_saved", stock_code=code, signal_id=saved_id)
        return saved_id

    def _build_response(
        self,
        code: str,
        result: dict[str, Any],
        signal_id: str,
        data_quality_score: float | None,
    ) -> AnalyzeResponseData:
        signal_data = result["signal"]
        agent_results_raw: dict[str, AgentResult] = result.get("agent_results", {})
        summaries = {
            name: AgentResultSummary(
                agent_name=ar.agent_name,
                model=ar.model,
                status=ar.status,
                latency_ms=ar.latency_ms,
                output=ar.output,
                degraded=bool(ar.output.get("_degraded")),
                error_msg=ar.error_msg,
            )
            for name, ar in agent_results_raw.items()
            if isinstance(ar, AgentResult)
        }
        signal = SignalPayload(
            id=signal_id,
            action=signal_data.get("action", "HOLD"),
            confidence=float(signal_data.get("confidence", 0)),
            raw_confidence=signal_data.get("raw_confidence"),
            risk_level=signal_data.get("risk_level", "MEDIUM"),
            price_at=signal_data.get("price_at"),
            reason=signal_data.get("reason", ""),
            scores=signal_data.get("scores", {}),
            degraded_agents=signal_data.get("degraded_agents", []),
            signal_time=signal_data.get("signal_time"),
            valid_until=signal_data.get("valid_until"),
        )
        return AnalyzeResponseData(
            code=code,
            signal=signal,
            scores=signal_data.get("scores", {}),
            reason=signal_data.get("reason", ""),
            agent_results=summaries,
            agent_statuses=result.get("agent_statuses", {}),
            latency_ms=result.get("latency_ms", 0),
            from_cache=False,
            signal_id=signal_id,
            data_quality_score=data_quality_score,
        )

    @staticmethod
    def _agent_votes_to_summaries(
        agent_votes: dict[str, Any],
    ) -> dict[str, AgentResultSummary]:
        summaries: dict[str, AgentResultSummary] = {}
        for name, output in agent_votes.items():
            if not isinstance(output, dict):
                continue
            summaries[name] = AgentResultSummary(
                agent_name=name,
                model="cached",
                status="success" if not output.get("_degraded") else "degraded",
                latency_ms=0,
                output=output,
                degraded=bool(output.get("_degraded")),
            )
        return summaries

    async def list_signals(
        self,
        *,
        action: str | None = None,
        min_confidence: float = 0.0,
        risk_level: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> SignalListResponse:
        page_size = min(page_size, 200)
        offset = (page - 1) * page_size
        filters = ["1=1"]
        params: dict[str, Any] = {
            "min_confidence": min_confidence,
            "limit": page_size,
            "offset": offset,
        }
        if action:
            filters.append("action = :action")
            params["action"] = action.upper()
        if risk_level:
            filters.append("risk_level = :risk_level")
            params["risk_level"] = risk_level.upper()

        where_clause = " AND ".join(filters)
        async with get_db() as db:
            count_row = await db.execute(
                text(
                    f"""
                    SELECT COUNT(*) AS cnt FROM ai.signals
                    WHERE {where_clause} AND confidence >= :min_confidence
                    """
                ),
                params,
            )
            total = int(count_row.scalar() or 0)
            rows = await db.execute(
                text(
                    f"""
                    SELECT id, stock_code, action, confidence, risk_level, price_at,
                           reason, signal_time, valid_until, status, raw_agent_output
                    FROM ai.signals
                    WHERE {where_clause} AND confidence >= :min_confidence
                    ORDER BY signal_time DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            records = rows.mappings().all()

        items = [self._row_to_list_item(dict(r)) for r in records]
        return SignalListResponse(
            items=items, total=total, page=page, page_size=page_size
        )

    async def get_signal_history(
        self, code: str, *, days: int = 30
    ) -> SignalHistoryResponse:
        code = code.strip()
        if not self._is_valid_code_format(code):
            raise AnalysisError(f"无效的股票代码格式: {code}", 400)

        days = min(max(days, 1), 365)
        async with get_db() as db:
            count_row = await db.execute(
                text(
                    """
                    SELECT COUNT(*) AS cnt FROM ai.signals
                    WHERE stock_code = :code
                      AND signal_time >= NOW() - (:days || ' days')::interval
                    """
                ),
                {"code": code, "days": days},
            )
            total = int(count_row.scalar() or 0)
            rows = await db.execute(
                text(
                    """
                    SELECT id, stock_code, action, confidence, risk_level, price_at,
                           reason, signal_time, valid_until, status,
                           executed_at, executed_price, pnl, pnl_pct, raw_agent_output
                    FROM ai.signals
                    WHERE stock_code = :code
                      AND signal_time >= NOW() - (:days || ' days')::interval
                    ORDER BY signal_time DESC
                    """
                ),
                {"code": code, "days": days},
            )
            records = rows.mappings().all()

        items = [self._row_to_history_item(dict(r)) for r in records]
        return SignalHistoryResponse(stock_code=code, items=items, total=total, days=days)

    async def _maybe_publish_signal(self, code: str, response: AnalyzeResponseData) -> None:
        action = response.signal.action
        confidence = response.signal.confidence
        if action == "HOLD" and confidence < settings.SIGNAL_MIN_CONFIDENCE:
            return
        from app.ws.publisher import publish_signal

        await publish_signal(
            {
                "type": "signal",
                "stock_code": code,
                "action": action,
                "confidence": confidence,
                "risk_level": response.signal.risk_level,
                "price_at": response.signal.price_at,
                "reason": response.reason,
                "signal_id": response.signal_id,
                "signal_time": response.signal.signal_time,
            }
        )

    @staticmethod
    def _is_valid_code_format(code: str) -> bool:
        return len(code) == 6 and code.isdigit()

    async def _stock_exists(self, code: str) -> bool:
        async with get_db() as db:
            row = await db.execute(
                text(
                    "SELECT 1 FROM fundamental.stocks WHERE code = :code AND is_active = TRUE"
                ),
                {"code": code},
            )
            return row.scalar() is not None

    @staticmethod
    def _parse_raw_output(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        if isinstance(raw, str):
            return json.loads(raw)
        return raw if isinstance(raw, dict) else {}

    def _row_to_list_item(self, row: dict[str, Any]) -> SignalListItem:
        raw = self._parse_raw_output(row.get("raw_agent_output"))
        return SignalListItem(
            id=str(row["id"]),
            stock_code=row["stock_code"],
            action=row["action"],
            confidence=float(row["confidence"]),
            risk_level=row["risk_level"],
            price_at=float(row["price_at"]) if row.get("price_at") else None,
            reason=row["reason"],
            signal_time=row["signal_time"].isoformat()
            if row.get("signal_time")
            else None,
            valid_until=row["valid_until"].isoformat()
            if row.get("valid_until")
            else None,
            status=row.get("status", "active"),
            data_quality_score=raw.get("data_quality_score"),
        )

    def _row_to_history_item(self, row: dict[str, Any]) -> SignalHistoryItem:
        raw = self._parse_raw_output(row.get("raw_agent_output"))
        return SignalHistoryItem(
            id=str(row["id"]),
            stock_code=row["stock_code"],
            action=row["action"],
            confidence=float(row["confidence"]),
            risk_level=row["risk_level"],
            price_at=float(row["price_at"]) if row.get("price_at") else None,
            reason=row["reason"],
            signal_time=row["signal_time"].isoformat()
            if row.get("signal_time")
            else None,
            valid_until=row["valid_until"].isoformat()
            if row.get("valid_until")
            else None,
            status=row.get("status", "active"),
            executed_at=row["executed_at"].isoformat()
            if row.get("executed_at")
            else None,
            executed_price=float(row["executed_price"])
            if row.get("executed_price")
            else None,
            pnl=float(row["pnl"]) if row.get("pnl") is not None else None,
            pnl_pct=float(row["pnl_pct"]) if row.get("pnl_pct") is not None else None,
            data_quality_score=raw.get("data_quality_score"),
        )