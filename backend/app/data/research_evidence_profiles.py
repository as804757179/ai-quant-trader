from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchEvidenceRequirementProfile:
    name: str
    evidence_type: str
    required_fields: tuple[str, ...]
    allowed_scopes: tuple[str, ...]
    policy_version: str = "multidimensional-evidence-readiness-audit-v1"

    @classmethod
    def get(cls, name: str | None) -> "ResearchEvidenceRequirementProfile":
        if not name:
            raise ValueError("requirement_profile must be explicitly declared")
        profiles = {
            "ANNOUNCEMENT_EVENT_RESEARCH_V1": cls(
                "ANNOUNCEMENT_EVENT_RESEARCH_V1",
                "announcement",
                (
                    "evidence_quality",
                    "original_document_hash",
                    "available_at",
                    "source_publication_time",
                    "security_association",
                    "event_content_validation",
                    "revision_lineage",
                    "provider_usage_permission",
                ),
                ("announcement_event_research",),
            ),
            "FINANCIAL_REPORT_FUNDAMENTAL_RESEARCH_V1": cls(
                "FINANCIAL_REPORT_FUNDAMENTAL_RESEARCH_V1",
                "financial_report",
                (
                    "evidence_quality",
                    "original_document_hash",
                    "available_at",
                    "security_association",
                    "report_period_end",
                    "consolidation_scope",
                    "currency_code",
                    "currency_unit",
                    "audit_opinion",
                    "financial_fact_provenance",
                    "revision_lineage",
                    "provider_usage_permission",
                ),
                ("financial_report_research",),
            ),
            "NEWS_EVENT_RESEARCH_V1": cls(
                "NEWS_EVENT_RESEARCH_V1",
                "news",
                (
                    "evidence_quality",
                    "article_body_hash",
                    "available_at",
                    "source_publication_time",
                    "security_association",
                    "content_validation",
                    "coverage_scope",
                    "reviewer_identity",
                    "provider_usage_permission",
                ),
                ("news_event_research",),
            ),
        }
        profile = profiles.get(name)
        if not profile:
            raise ValueError(f"unknown evidence requirement profile: {name}")
        return profile

    def validate_declaration(
        self,
        *,
        research_use_scope: str,
        required_fields: list[str] | tuple[str, ...] | None,
    ) -> tuple[str, ...]:
        if research_use_scope not in self.allowed_scopes:
            raise ValueError("requirement profile does not allow the requested use scope")
        if not required_fields:
            raise ValueError("required_fields must be explicitly declared")
        if any(not isinstance(field, str) or not field.strip() for field in required_fields):
            raise ValueError("required_fields must not contain empty values")
        declared = tuple(field.strip() for field in required_fields)
        if len(set(declared)) != len(declared):
            raise ValueError("required_fields must not contain duplicates")
        if set(declared) != set(self.required_fields):
            raise ValueError("required_fields do not match evidence requirement profile")
        return declared
