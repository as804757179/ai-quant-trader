import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import research
from app.core.response import APIProblem
from app.data.research_evidence_profiles import ResearchEvidenceRequirementProfile
from app.data.research_evidence_readiness import ResearchEvidenceReadinessService

VALID_HASH = "a" * 64


def evaluate(evidence, profile_name, scope):
    profile = ResearchEvidenceRequirementProfile.get(profile_name)
    return ResearchEvidenceReadinessService.evaluate(
        evidence,
        research_use_scope=scope,
        requirement_profile=profile.name,
        required_fields=list(profile.required_fields),
    )


def announcement_evidence():
    return {
        "evidence_id": "11111111-1111-1111-1111-111111111111",
        "evidence_type": "announcement",
        "stock_code": "000001.SZ",
        "source_document_id": "cninfo-announcement-1",
        "source_published_at": None,
        "publication_time_precision": "date",
        "available_at": "2026-07-15T08:00:00+08:00",
        "raw_hash": VALID_HASH,
        "quality_status": "observed",
        "usage_status": "review_required",
    }


def financial_report_evidence():
    return {
        "evidence_id": "22222222-2222-2222-2222-222222222222",
        "evidence_type": "financial_report",
        "stock_code": "600000.SH",
        "source_document_id": "cninfo-report-1",
        "available_at": "2026-07-15T08:00:00+08:00",
        "raw_hash": VALID_HASH,
        "quality_status": "observed",
        "usage_status": "review_required",
        "financial_report_period_end": None,
        "financial_consolidation_scope": "unresolved",
        "financial_currency_code": "unresolved",
        "financial_currency_unit": "unresolved",
        "financial_audit_opinion": "unresolved",
        "financial_revision_status": "none",
        "financial_supersedes_evidence_id": None,
        "financial_detail_parse_status": "metadata_observed",
    }


def news_evidence(conclusion="title_link_relevant"):
    return {
        "evidence_id": "33333333-3333-3333-3333-333333333333",
        "evidence_type": "news",
        "stock_code": "300750.SZ",
        "source_document_id": "gdelt-news-1",
        "source_published_at": None,
        "publication_time_precision": "unresolved",
        "available_at": "2026-07-15T08:00:00+08:00",
        "raw_hash": VALID_HASH,
        "quality_status": "observed",
        "usage_status": "review_required",
        "news_raw_representation": "rss_item_xml_reserialized",
        "latest_news_review_conclusion": conclusion,
    }


class _Result:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def mappings(self):
        return self

    def one(self):
        return self._one

    def all(self):
        return self._rows


class _AuditDb:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return self._results.pop(0)


class _DbContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class ResearchEvidenceReadinessAuditTests(unittest.TestCase):
    def test_profiles_require_explicit_exact_fields_and_matching_scope(self):
        profile = ResearchEvidenceRequirementProfile.get(
            "ANNOUNCEMENT_EVENT_RESEARCH_V1"
        )
        with self.assertRaises(ValueError):
            profile.validate_declaration(
                research_use_scope="announcement_event_research",
                required_fields=None,
            )
        with self.assertRaises(ValueError):
            profile.validate_declaration(
                research_use_scope="financial_report_research",
                required_fields=profile.required_fields,
            )
        with self.assertRaises(ValueError):
            profile.validate_declaration(
                research_use_scope="announcement_event_research",
                required_fields=profile.required_fields[:-1],
            )
        with self.assertRaises(ValueError):
            profile.validate_declaration(
                research_use_scope="announcement_event_research",
                required_fields=profile.required_fields + (profile.required_fields[0],),
            )

    def test_announcement_date_precision_and_unparsed_content_remain_review_required(self):
        decision = evaluate(
            announcement_evidence(),
            "ANNOUNCEMENT_EVENT_RESEARCH_V1",
            "announcement_event_research",
        )
        self.assertEqual(decision.status, "review_required")
        self.assertIn("original_document_hash", decision.validated_fields)
        self.assertIn("available_at", decision.validated_fields)
        self.assertIn("ANNOUNCEMENT_PUBLICATION_TIME_DATE_ONLY", decision.blocking_codes)
        self.assertIn("ANNOUNCEMENT_EVENT_CONTENT_UNPARSED", decision.blocking_codes)
        self.assertIn("ANNOUNCEMENT_REVISION_LINEAGE_UNVERIFIED", decision.blocking_codes)
        self.assertIn("PROVIDER_USAGE_PERMISSION_UNAPPROVED", decision.blocking_codes)
        self.assertIn("READINESS_GRANT_NOT_IMPLEMENTED", decision.blocking_codes)

    def test_financial_report_unresolved_metadata_and_facts_remain_review_required(self):
        decision = evaluate(
            financial_report_evidence(),
            "FINANCIAL_REPORT_FUNDAMENTAL_RESEARCH_V1",
            "financial_report_research",
        )
        self.assertEqual(decision.status, "review_required")
        self.assertIn("report_period_end", decision.unresolved_fields)
        self.assertIn("consolidation_scope", decision.unresolved_fields)
        self.assertIn("currency_code", decision.unresolved_fields)
        self.assertIn("currency_unit", decision.unresolved_fields)
        self.assertIn("audit_opinion", decision.unresolved_fields)
        self.assertIn("financial_fact_provenance", decision.unresolved_fields)
        self.assertIn("REPORT_PERIOD_END_UNRESOLVED", decision.blocking_codes)
        self.assertIn("CURRENCY_OR_UNIT_UNRESOLVED", decision.blocking_codes)
        self.assertIn("FINANCIAL_FACTS_UNPARSED", decision.blocking_codes)
        self.assertIn("READINESS_GRANT_NOT_IMPLEMENTED", decision.blocking_codes)

    def test_news_title_link_review_cannot_grant_body_or_identity_evidence(self):
        decision = evaluate(
            news_evidence(),
            "NEWS_EVENT_RESEARCH_V1",
            "news_event_research",
        )
        self.assertEqual(decision.status, "review_required")
        self.assertIn("NEWS_ARTICLE_BODY_HASH_MISSING", decision.blocking_codes)
        self.assertIn("HASH_SCOPE_INSUFFICIENT", decision.blocking_codes)
        self.assertIn("NEWS_SOURCE_PUBLICATION_TIME_UNRESOLVED", decision.blocking_codes)
        self.assertIn("NEWS_ASSOCIATION_REVIEW_REQUIRED", decision.blocking_codes)
        self.assertIn("NEWS_REVIEWER_IDENTITY_UNVERIFIED", decision.blocking_codes)
        self.assertIn("NEWS_ROLLING_WINDOW_COVERAGE_LIMITED", decision.blocking_codes)
        self.assertIn("READINESS_GRANT_NOT_IMPLEMENTED", decision.blocking_codes)

    def test_irrelevant_manual_news_review_is_rejected_and_cannot_be_upgraded(self):
        decision = evaluate(
            news_evidence("title_link_irrelevant"),
            "NEWS_EVENT_RESEARCH_V1",
            "news_event_research",
        )
        self.assertEqual(decision.status, "rejected")
        self.assertIn("security_association", decision.rejected_fields)
        self.assertIn("NEWS_ASSOCIATION_REJECTED", decision.blocking_codes)
        self.assertIn("READINESS_GRANT_NOT_IMPLEMENTED", decision.blocking_codes)

    def test_rejected_evidence_stays_rejected(self):
        evidence = announcement_evidence()
        evidence["quality_status"] = "rejected"
        evidence["usage_status"] = "approved"
        decision = evaluate(
            evidence,
            "ANNOUNCEMENT_EVENT_RESEARCH_V1",
            "announcement_event_research",
        )
        self.assertEqual(decision.status, "rejected")
        self.assertIn("evidence_quality", decision.rejected_fields)
        self.assertIn("EVIDENCE_QUALITY_NOT_OBSERVED", decision.blocking_codes)
        self.assertIn("READINESS_GRANT_NOT_IMPLEMENTED", decision.blocking_codes)

    def test_profile_cannot_assess_a_different_evidence_type(self):
        profile = ResearchEvidenceRequirementProfile.get(
            "NEWS_EVENT_RESEARCH_V1"
        )
        with self.assertRaises(ValueError):
            ResearchEvidenceReadinessService.evaluate(
                announcement_evidence(),
                research_use_scope="news_event_research",
                requirement_profile=profile.name,
                required_fields=list(profile.required_fields),
            )

    def test_input_fingerprint_is_stable_and_changes_with_authorization_input(self):
        first = evaluate(
            announcement_evidence(),
            "ANNOUNCEMENT_EVENT_RESEARCH_V1",
            "announcement_event_research",
        )
        second = evaluate(
            announcement_evidence(),
            "ANNOUNCEMENT_EVENT_RESEARCH_V1",
            "announcement_event_research",
        )
        changed = announcement_evidence()
        changed["raw_hash"] = "b" * 64
        third = evaluate(
            changed,
            "ANNOUNCEMENT_EVENT_RESEARCH_V1",
            "announcement_event_research",
        )
        self.assertEqual(first.input_fingerprint, second.input_fingerprint)
        self.assertNotEqual(first.input_fingerprint, third.input_fingerprint)

    def test_audit_route_is_get_only_and_keeps_research_and_trading_locked(self):
        route = next(
            item
            for item in research.router.routes
            if item.path == "/evidence/readiness-audit"
        )
        self.assertEqual(route.methods, {"GET"})
        source = (ROOT / "backend/app/api/research.py").read_text(encoding="utf-8")
        start = source.index('@router.get("/evidence/readiness-audit")')
        end = source.index('@router.get("/evidence/batches")', start)
        audit_source = source[start:end]
        self.assertIn('"research_readiness": "not_granted"', audit_source)
        self.assertIn('"observed_only": True', audit_source)
        self.assertIn('"tradable": False', audit_source)
        self.assertIn('"order_created": False', audit_source)
        self.assertNotIn("INSERT INTO", audit_source)
        self.assertNotIn("UPDATE market", audit_source)
        self.assertNotIn("DELETE FROM", audit_source)

    def test_missing_required_fields_is_fail_closed_before_database_access(self):
        with self.assertRaises(APIProblem) as raised:
            asyncio.run(
                research.list_research_evidence_readiness_audit(
                    research_use_scope="announcement_event_research",
                    requirement_profile="ANNOUNCEMENT_EVENT_RESEARCH_V1",
                    required_fields=None,
                    stock_code=None,
                    evidence_type=None,
                    evidence_id=None,
                    page=1,
                    page_size=50,
                )
            )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(
            raised.exception.code,
            "INVALID_EVIDENCE_READINESS_DECLARATION",
        )

    def test_profile_type_mismatch_is_fail_closed_before_database_access(self):
        profile = ResearchEvidenceRequirementProfile.get(
            "ANNOUNCEMENT_EVENT_RESEARCH_V1"
        )
        with self.assertRaises(APIProblem) as raised:
            asyncio.run(
                research.list_research_evidence_readiness_audit(
                    research_use_scope="announcement_event_research",
                    requirement_profile=profile.name,
                    required_fields=list(profile.required_fields),
                    stock_code=None,
                    evidence_type="news",
                    evidence_id=None,
                    page=1,
                    page_size=50,
                )
            )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(
            raised.exception.code,
            "EVIDENCE_PROFILE_TYPE_MISMATCH",
        )

    def test_audit_uses_current_news_review_and_rejects_irrelevant_status(self):
        profile = ResearchEvidenceRequirementProfile.get("NEWS_EVENT_RESEARCH_V1")
        evidence = {
            "evidence_id": "33333333-3333-3333-3333-333333333333",
            "evidence_type": "news",
            "stock_code": "300750.SZ",
            "provider": "gdelt",
            "source": "gdelt_article_list_rss",
            "source_document_id": "gdelt-news-1",
            "source_published_at": None,
            "publication_time_precision": "unresolved",
            "available_at": "2026-07-15T08:00:00+08:00",
            "raw_hash": VALID_HASH,
            "quality_status": "observed",
            "usage_status": "review_required",
            "financial_report_period_end": None,
            "financial_consolidation_scope": None,
            "financial_currency_code": None,
            "financial_currency_unit": None,
            "financial_audit_opinion": None,
            "financial_revision_status": None,
            "financial_supersedes_evidence_id": None,
            "financial_detail_parse_status": None,
            "news_raw_representation": "rss_item_xml_reserialized",
            "latest_news_review_id": "latest-review",
            "latest_news_review_conclusion": "title_link_irrelevant",
        }
        db = _AuditDb([_Result(one={"total": 1}), _Result(rows=[evidence])])

        async def run():
            with (
                patch.object(research, "get_db", return_value=_DbContext(db)),
                patch.object(
                    research,
                    "_load_source_usage_context",
                    new_callable=AsyncMock,
                    return_value={},
                ),
            ):
                return await research.list_research_evidence_readiness_audit(
                    research_use_scope="news_event_research",
                    requirement_profile=profile.name,
                    required_fields=list(profile.required_fields),
                    stock_code=None,
                    evidence_type="news",
                    evidence_id=None,
                    page=1,
                    page_size=50,
                )

        response = asyncio.run(run())
        payload = response.data
        item = payload["items"][0]
        self.assertEqual(item["precheck_status"], "rejected")
        self.assertIn("NEWS_ASSOCIATION_REJECTED", item["blocking_codes"])
        self.assertNotIn("NEWS_ASSOCIATION_REVIEW_REQUIRED", item["blocking_codes"])
        self.assertEqual(item["authorization_key"]["evidence_id"], evidence["evidence_id"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])
        self.assertIn(
            "ORDER BY news_review.reviewed_at DESC, news_review.review_id DESC",
            db.calls[1][0],
        )
        self.assertEqual(db.calls[1][1]["profile_evidence_type"], "news")


if __name__ == "__main__":
    unittest.main()
