from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping
from uuid import UUID

from app.data.research_evidence_profiles import ResearchEvidenceRequirementProfile


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EvidenceReadinessDecision:
    status: str
    quality_status: str | None
    usage_status: str | None
    authorization_key: dict[str, str | None]
    policy_version: str
    required_fields: tuple[str, ...]
    validated_fields: tuple[str, ...]
    unresolved_fields: tuple[str, ...]
    rejected_fields: tuple[str, ...]
    blocking_codes: tuple[str, ...]
    blocking_details: tuple[dict[str, Any], ...]
    source_usage_evidence: dict[str, Any]
    input_fingerprint: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.authorization_key["evidence_id"],
            "stock_code": self.authorization_key["stock_code"],
            "evidence_type": self.authorization_key["evidence_type"],
            "precheck_status": self.status,
            "quality_status": self.quality_status,
            "usage_status": self.usage_status,
            "authorization_key": self.authorization_key,
            "policy_version": self.policy_version,
            "required_fields": list(self.required_fields),
            "validated_fields": list(self.validated_fields),
            "unresolved_fields": list(self.unresolved_fields),
            "rejected_fields": list(self.rejected_fields),
            "blocking_codes": list(self.blocking_codes),
            "blocking_details": list(self.blocking_details),
            "source_usage_evidence": self.source_usage_evidence,
            "input_fingerprint": self.input_fingerprint,
        }


class ResearchEvidenceReadinessService:
    @classmethod
    def evaluate(
        cls,
        evidence: Mapping[str, Any],
        *,
        research_use_scope: str,
        requirement_profile: str | None,
        required_fields: list[str] | tuple[str, ...] | None,
    ) -> EvidenceReadinessDecision:
        profile = ResearchEvidenceRequirementProfile.get(requirement_profile)
        declared = profile.validate_declaration(
            research_use_scope=research_use_scope,
            required_fields=required_fields,
        )
        if evidence.get("evidence_type") != profile.evidence_type:
            raise ValueError("evidence type does not match requirement profile")

        states = {field: "unresolved" for field in declared}
        blocking_details: list[dict[str, Any]] = []
        seen_codes: set[str] = set()

        def add_blocker(code: str, fields: tuple[str, ...], reason: str) -> None:
            if code in seen_codes:
                return
            seen_codes.add(code)
            blocking_details.append(
                {
                    "code": code,
                    "fields": list(fields),
                    "reason": reason,
                }
            )

        def mark_validated(field: str) -> None:
            if field in states and states[field] != "rejected":
                states[field] = "validated"

        def mark_unresolved(
            fields: tuple[str, ...], code: str, reason: str
        ) -> None:
            active_fields = tuple(field for field in fields if field in states)
            for field in active_fields:
                if states[field] != "rejected":
                    states[field] = "unresolved"
            add_blocker(code, active_fields, reason)

        def mark_rejected(fields: tuple[str, ...], code: str, reason: str) -> None:
            active_fields = tuple(field for field in fields if field in states)
            for field in active_fields:
                states[field] = "rejected"
            add_blocker(code, active_fields, reason)

        quality_status = evidence.get("quality_status")
        if quality_status == "observed":
            mark_validated("evidence_quality")
        else:
            mark_rejected(
                ("evidence_quality",),
                "EVIDENCE_QUALITY_NOT_OBSERVED",
                "原始证据不是已观察状态，不能进入资格预审。",
            )

        if evidence.get("available_at"):
            mark_validated("available_at")
        else:
            mark_unresolved(
                ("available_at",),
                "AVAILABLE_AT_UNRESOLVED",
                "证据缺少可证明的最早可得时间。",
            )

        source_usage_evidence = dict(evidence.get("source_usage_evidence") or {})
        if (
            evidence.get("usage_status") == "approved"
            and source_usage_evidence.get("authorization_granted") is True
        ):
            mark_validated("provider_usage_permission")
        else:
            mark_unresolved(
                ("provider_usage_permission",),
                "PROVIDER_USAGE_PERMISSION_UNAPPROVED",
                "来源自动化使用权限尚未获批。",
            )

        evidence_type = profile.evidence_type
        if evidence_type in {"announcement", "financial_report"}:
            raw_hash = evidence.get("raw_hash")
            if isinstance(raw_hash, str) and _SHA256_RE.fullmatch(raw_hash):
                mark_validated("original_document_hash")
            else:
                mark_unresolved(
                    ("original_document_hash",),
                    "HASH_SCOPE_INSUFFICIENT",
                    "证据缺少可验证的原文级 SHA-256 Hash。",
                )
            if evidence.get("stock_code") and evidence.get("source_document_id"):
                mark_validated("security_association")
            else:
                mark_unresolved(
                    ("security_association",),
                    "SECURITY_ASSOCIATION_UNVERIFIED",
                    "证据缺少可验证的证券关联。",
                )

        if evidence_type == "announcement":
            cls._evaluate_announcement(evidence, mark_validated, mark_unresolved)
        elif evidence_type == "financial_report":
            cls._evaluate_financial_report(evidence, mark_validated, mark_unresolved)
        elif evidence_type == "news":
            cls._evaluate_news(evidence, mark_validated, mark_unresolved, mark_rejected)

        add_blocker(
            "READINESS_GRANT_NOT_IMPLEMENTED",
            (),
            "本阶段只做资格预审，不授予 Research Readiness。",
        )
        status = "rejected" if any(state == "rejected" for state in states.values()) else "review_required"
        authorization_key = {
            "stock_code": cls._string_value(evidence.get("stock_code")),
            "evidence_type": profile.evidence_type,
            "evidence_id": cls._string_value(evidence.get("evidence_id")),
            "raw_hash": cls._string_value(evidence.get("raw_hash")),
            "available_at": cls._string_value(evidence.get("available_at")),
            "research_use_scope": research_use_scope,
            "requirement_profile": profile.name,
            "policy_version": profile.policy_version,
        }
        input_fingerprint = cls._fingerprint(
            {
                "authorization_key": authorization_key,
                "evidence": dict(evidence),
                "field_states": states,
                "policy_version": profile.policy_version,
            }
        )
        return EvidenceReadinessDecision(
            status=status,
            quality_status=cls._string_value(evidence.get("quality_status")),
            usage_status=cls._string_value(evidence.get("usage_status")),
            authorization_key=authorization_key,
            policy_version=profile.policy_version,
            required_fields=declared,
            validated_fields=tuple(
                field for field in declared if states[field] == "validated"
            ),
            unresolved_fields=tuple(
                field for field in declared if states[field] == "unresolved"
            ),
            rejected_fields=tuple(
                field for field in declared if states[field] == "rejected"
            ),
            blocking_codes=tuple(detail["code"] for detail in blocking_details),
            blocking_details=tuple(blocking_details),
            source_usage_evidence=source_usage_evidence,
            input_fingerprint=input_fingerprint,
        )

    @staticmethod
    def _evaluate_announcement(
        evidence: Mapping[str, Any],
        mark_validated: Any,
        mark_unresolved: Any,
    ) -> None:
        if (
            evidence.get("source_published_at")
            and evidence.get("publication_time_precision") == "exact"
        ):
            mark_validated("source_publication_time")
        else:
            mark_unresolved(
                ("source_publication_time",),
                "ANNOUNCEMENT_PUBLICATION_TIME_DATE_ONLY",
                "公告来源只记录日期精度，不能证明精确公开时点。",
            )
        mark_unresolved(
            ("event_content_validation",),
            "ANNOUNCEMENT_EVENT_CONTENT_UNPARSED",
            "公告正文事件尚未解析或人工验证。",
        )
        mark_unresolved(
            ("revision_lineage",),
            "ANNOUNCEMENT_REVISION_LINEAGE_UNVERIFIED",
            "公告修订关系尚未形成可审计链路。",
        )
        mark_unresolved(
            ("event_content_validation",),
            "RESEARCH_CONTENT_NOT_VALIDATED",
            "研究所需的公告事件内容尚未验证。",
        )

    @staticmethod
    def _evaluate_financial_report(
        evidence: Mapping[str, Any],
        mark_validated: Any,
        mark_unresolved: Any,
    ) -> None:
        if evidence.get("financial_report_period_end"):
            mark_validated("report_period_end")
        else:
            mark_unresolved(
                ("report_period_end",),
                "REPORT_PERIOD_END_UNRESOLVED",
                "财报报告期截止日尚未从原文确认。",
            )

        if evidence.get("financial_consolidation_scope") in {
            "consolidated",
            "parent_company",
        }:
            mark_validated("consolidation_scope")
        else:
            mark_unresolved(
                ("consolidation_scope",),
                "CONSOLIDATION_SCOPE_UNRESOLVED",
                "财报合并口径尚未确认。",
            )

        currency_fields = ("currency_code", "currency_unit")
        if (
            evidence.get("financial_currency_code") not in {None, "unresolved"}
            and evidence.get("financial_currency_unit") not in {None, "unresolved"}
        ):
            mark_validated("currency_code")
            mark_validated("currency_unit")
        else:
            mark_unresolved(
                currency_fields,
                "CURRENCY_OR_UNIT_UNRESOLVED",
                "财报币种或单位尚未确认。",
            )

        if evidence.get("financial_audit_opinion") not in {None, "unresolved"}:
            mark_validated("audit_opinion")
        else:
            mark_unresolved(
                ("audit_opinion",),
                "AUDIT_OPINION_UNRESOLVED",
                "财报审计意见尚未确认。",
            )

        revision_status = evidence.get("financial_revision_status")
        if revision_status == "none" or (
            revision_status == "linked"
            and evidence.get("financial_supersedes_evidence_id")
        ):
            mark_validated("revision_lineage")
        else:
            mark_unresolved(
                ("revision_lineage",),
                "FINANCIAL_REPORT_REVISION_RELATION_UNRESOLVED",
                "财报修订关系尚未确认。",
            )

        mark_unresolved(
            ("financial_fact_provenance",),
            "FINANCIAL_FACTS_UNPARSED",
            "财报财务事实尚未从原文定位、解析或人工复核。",
        )
        mark_unresolved(
            ("financial_fact_provenance",),
            "RESEARCH_CONTENT_NOT_VALIDATED",
            "研究所需的财报内容尚未验证。",
        )

    @staticmethod
    def _evaluate_news(
        evidence: Mapping[str, Any],
        mark_validated: Any,
        mark_unresolved: Any,
        mark_rejected: Any,
    ) -> None:
        raw_hash = evidence.get("raw_hash")
        if (
            evidence.get("news_raw_representation") == "article_body"
            and isinstance(raw_hash, str)
            and _SHA256_RE.fullmatch(raw_hash)
        ):
            mark_validated("article_body_hash")
        else:
            mark_unresolved(
                ("article_body_hash",),
                "NEWS_ARTICLE_BODY_HASH_MISSING",
                "当前仅存 RSS 条目 Hash，缺少新闻正文 Hash。",
            )
            mark_unresolved(
                ("article_body_hash",),
                "HASH_SCOPE_INSUFFICIENT",
                "RSS 条目 Hash 不能表示新闻正文 Hash。",
            )

        if (
            evidence.get("source_published_at")
            and evidence.get("publication_time_precision") == "exact"
        ):
            mark_validated("source_publication_time")
        else:
            mark_unresolved(
                ("source_publication_time",),
                "NEWS_SOURCE_PUBLICATION_TIME_UNRESOLVED",
                "新闻来源公开时点尚未确认。",
            )

        if evidence.get("latest_news_review_conclusion") == "title_link_irrelevant":
            mark_rejected(
                ("security_association",),
                "NEWS_ASSOCIATION_REJECTED",
                "最新人工复核明确认为标题/链接与证券不相关。",
            )
        else:
            mark_unresolved(
                ("security_association",),
                "NEWS_ASSOCIATION_REVIEW_REQUIRED",
                "新闻证券关联仍仅是标题别名匹配，未获验证。",
            )

        mark_unresolved(
            ("content_validation",),
            "NEWS_CONTENT_SCOPE_TITLE_LINK_ONLY",
            "当前新闻证据只包含标题和链接，不包含正文。",
        )
        mark_unresolved(
            ("content_validation",),
            "RESEARCH_CONTENT_NOT_VALIDATED",
            "研究所需的新闻正文事实尚未验证。",
        )
        mark_unresolved(
            ("coverage_scope",),
            "NEWS_ROLLING_WINDOW_COVERAGE_LIMITED",
            "GDELT RSS 为 15 分钟滚动窗口，不代表完整新闻覆盖。",
        )
        mark_unresolved(
            ("reviewer_identity",),
            "NEWS_REVIEWER_IDENTITY_UNVERIFIED",
            "人工复核人标识为未认证自填值。",
        )

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        return str(value)

    @classmethod
    def _fingerprint(cls, value: Any) -> str:
        canonical = cls._canonicalize(value)
        payload = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _canonicalize(cls, value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(key): cls._canonicalize(item)
                for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
            }
        if isinstance(value, (list, tuple)):
            return [cls._canonicalize(item) for item in value]
        return value
