"""Reserve independent P2-2 market observation models without backfilling legacy snapshots."""

from alembic import op


revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.industry_classification_observations (
            observation_id UUID PRIMARY KEY,
            stock_code VARCHAR(10) NOT NULL REFERENCES fundamental.stocks(code),
            classification_code VARCHAR(64),
            classification_name VARCHAR(128) NOT NULL,
            provider VARCHAR(64) NOT NULL,
            source VARCHAR(128) NOT NULL,
            dataset_version VARCHAR(128),
            fetched_at TIMESTAMPTZ NOT NULL,
            effective_from DATE,
            effective_to DATE,
            quality_status VARCHAR(24) NOT NULL,
            pit_capable BOOLEAN NOT NULL DEFAULT FALSE,
            raw_hash VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE market.concept_board_memberships (
            membership_id UUID PRIMARY KEY,
            stock_code VARCHAR(10) NOT NULL REFERENCES fundamental.stocks(code),
            concept_code VARCHAR(64) NOT NULL,
            concept_name VARCHAR(128) NOT NULL,
            provider VARCHAR(64) NOT NULL,
            source VARCHAR(128) NOT NULL,
            dataset_version VARCHAR(128),
            fetched_at TIMESTAMPTZ NOT NULL,
            effective_from DATE,
            effective_to DATE,
            quality_status VARCHAR(24) NOT NULL,
            pit_capable BOOLEAN NOT NULL DEFAULT FALSE,
            raw_hash VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE market.exchange_board_observations (
            observation_id UUID PRIMARY KEY,
            stock_code VARCHAR(10) NOT NULL REFERENCES fundamental.stocks(code),
            board_code VARCHAR(64),
            board_name VARCHAR(128) NOT NULL,
            provider VARCHAR(64) NOT NULL,
            source VARCHAR(128) NOT NULL,
            dataset_version VARCHAR(128),
            fetched_at TIMESTAMPTZ NOT NULL,
            effective_from DATE,
            effective_to DATE,
            quality_status VARCHAR(24) NOT NULL,
            pit_capable BOOLEAN NOT NULL DEFAULT FALSE,
            raw_hash VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE market.sentiment_derivations (
            derivation_id UUID PRIMARY KEY,
            stock_code VARCHAR(10) REFERENCES fundamental.stocks(code),
            score NUMERIC(8, 4),
            semantic_kind VARCHAR(32) NOT NULL
                CHECK (semantic_kind IN ('derived', 'derived_from_observed')),
            evidence_refs JSONB NOT NULL,
            provider VARCHAR(64) NOT NULL,
            source VARCHAR(128) NOT NULL,
            source_published_at TIMESTAMPTZ,
            fetched_at TIMESTAMPTZ NOT NULL,
            algorithm_version VARCHAR(128) NOT NULL,
            calculation_rule VARCHAR(128) NOT NULL,
            quality_status VARCHAR(24) NOT NULL,
            raw_hash VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX idx_industry_classification_observations_stock_time ON market.industry_classification_observations(stock_code, effective_from DESC, fetched_at DESC)")
    op.execute("CREATE INDEX idx_concept_board_memberships_stock_time ON market.concept_board_memberships(stock_code, effective_from DESC, fetched_at DESC)")
    op.execute("CREATE INDEX idx_exchange_board_observations_stock_time ON market.exchange_board_observations(stock_code, effective_from DESC, fetched_at DESC)")
    op.execute("CREATE INDEX idx_sentiment_derivations_stock_time ON market.sentiment_derivations(stock_code, source_published_at DESC, fetched_at DESC)")


def downgrade() -> None:
    raise RuntimeError("041 preserves future market-observation lineage and must not be downgraded")
