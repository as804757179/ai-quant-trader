"""Bind news evidence reviews to principals and idempotency keys."""

from alembic import op


revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.research_news_evidence_reviews
            ADD COLUMN reviewer_principal_id UUID
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            ADD COLUMN idempotency_key VARCHAR(128),
            ADD COLUMN request_hash CHAR(64)
                CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$');
        ALTER TABLE market.research_news_evidence_reviews
            ADD CONSTRAINT ck_news_review_authenticated_request CHECK (
                (reviewer_principal_id IS NULL
                 AND idempotency_key IS NULL
                 AND request_hash IS NULL)
                OR
                (reviewer_principal_id IS NOT NULL
                 AND char_length(btrim(idempotency_key)) BETWEEN 8 AND 128
                 AND request_hash IS NOT NULL)
            );
        CREATE UNIQUE INDEX uq_news_review_principal_idempotency
        ON market.research_news_evidence_reviews (reviewer_principal_id, idempotency_key)
        WHERE reviewer_principal_id IS NOT NULL;
        ALTER TABLE market.research_news_evidence_reviews OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    raise RuntimeError("026 retains authenticated review audit records and must not be downgraded")
