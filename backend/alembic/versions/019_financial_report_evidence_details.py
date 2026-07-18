"""Add observed annual-report evidence details.

Revision ID: 019
Revises: 018
"""

from alembic import op


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.research_financial_report_details (
            evidence_id UUID PRIMARY KEY
                REFERENCES market.research_evidence(evidence_id) ON DELETE RESTRICT,
            provider_category VARCHAR(64) NOT NULL
                CHECK (provider_category = 'category_ndbg_szsh'),
            provider_category_version VARCHAR(64) NOT NULL,
            source_title_raw TEXT NOT NULL,
            report_kind VARCHAR(16) NOT NULL CHECK (report_kind = 'annual'),
            report_period_label TEXT NOT NULL,
            report_period_end DATE,
            period_precision VARCHAR(32) NOT NULL
                CHECK (period_precision IN ('title_label', 'exact')),
            document_role VARCHAR(32) NOT NULL CHECK (document_role = 'full_report'),
            consolidation_scope VARCHAR(32) NOT NULL
                CHECK (consolidation_scope IN ('unresolved', 'consolidated', 'parent_company')),
            currency_code VARCHAR(16) NOT NULL CHECK (currency_code IN ('unresolved', 'CNY')),
            currency_unit VARCHAR(32) NOT NULL
                CHECK (currency_unit IN ('unresolved', 'yuan', 'thousand_yuan', 'ten_thousand_yuan', 'million_yuan')),
            audit_opinion VARCHAR(32) NOT NULL
                CHECK (audit_opinion IN ('unresolved', 'unqualified', 'qualified', 'adverse', 'disclaimer')),
            revision_status VARCHAR(32) NOT NULL CHECK (revision_status IN ('none', 'linked')),
            supersedes_evidence_id UUID
                REFERENCES market.research_evidence(evidence_id) ON DELETE RESTRICT,
            detail_parse_status VARCHAR(32) NOT NULL
                CHECK (detail_parse_status IN ('metadata_observed', 'parsed', 'reviewed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (revision_status = 'none' AND supersedes_evidence_id IS NULL)
                OR (revision_status = 'linked' AND supersedes_evidence_id IS NOT NULL)
            )
        );
        ALTER TABLE market.research_financial_report_details OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.research_financial_report_details;")
