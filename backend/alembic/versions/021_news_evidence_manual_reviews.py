"""Add append-only manual reviews for observed news evidence.

Revision ID: 021
Revises: 020
"""

from alembic import op


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.research_news_evidence_reviews (
            review_id UUID PRIMARY KEY,
            evidence_id UUID NOT NULL
                REFERENCES market.research_evidence(evidence_id) ON DELETE RESTRICT,
            reviewer_label VARCHAR(128) NOT NULL
                CHECK (char_length(btrim(reviewer_label)) BETWEEN 1 AND 128),
            conclusion VARCHAR(32) NOT NULL
                CHECK (conclusion IN (
                    'title_link_relevant',
                    'title_link_irrelevant',
                    'needs_more_evidence'
                )),
            reason TEXT NOT NULL
                CHECK (char_length(btrim(reason)) BETWEEN 1 AND 2000),
            reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_research_news_evidence_reviews_latest
        ON market.research_news_evidence_reviews (
            evidence_id, reviewed_at DESC, review_id DESC
        );
        ALTER TABLE market.research_news_evidence_reviews OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.research_news_evidence_reviews;")
