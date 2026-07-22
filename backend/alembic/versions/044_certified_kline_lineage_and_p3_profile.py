"""Add certified K-line lineage sidecar and P3 draft profile.

Revision ID: 044
Revises: 043
"""

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE market.certified_kline_lineage (
            lineage_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            stock_code VARCHAR(12) NOT NULL,
            period VARCHAR(10) NOT NULL,
            trading_date DATE NOT NULL,
            adjustment VARCHAR(10) NOT NULL,
            batch_id VARCHAR(64) NOT NULL REFERENCES market.data_batches(batch_id) ON DELETE RESTRICT,
            provider_time TIMESTAMPTZ,
            fetched_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ,
            available_at TIMESTAMPTZ,
            availability_basis VARCHAR(32) NOT NULL CHECK (availability_basis IN ('observed_evidence', 'unavailable', 'conflicting')),
            row_hash CHAR(64) NOT NULL CHECK (row_hash ~ '^[0-9a-f]{64}$'),
            hash_algorithm VARCHAR(16) NOT NULL CHECK (hash_algorithm = 'sha256'),
            hash_policy_version VARCHAR(64) NOT NULL,
            evidence_ref TEXT,
            verification_status VARCHAR(16) NOT NULL CHECK (verification_status IN ('verified', 'unverified', 'blocked')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            FOREIGN KEY (stock_code, period, trading_date, adjustment)
                REFERENCES market.certified_klines(stock_code, period, trading_date, adjustment) ON DELETE RESTRICT,
            CHECK ((verification_status = 'verified' AND available_at IS NOT NULL AND evidence_ref IS NOT NULL AND availability_basis = 'observed_evidence') OR verification_status <> 'verified'),
            UNIQUE (stock_code, period, trading_date, adjustment, evidence_ref, row_hash)
        );
        CREATE INDEX idx_certified_kline_lineage_lookup ON market.certified_kline_lineage (stock_code, period, trading_date, adjustment, created_at DESC);
        CREATE TRIGGER certified_kline_lineage_append_only BEFORE UPDATE OR DELETE ON market.certified_kline_lineage FOR EACH ROW EXECUTE FUNCTION strategy.reject_strategy_version_mutation();
        ALTER TABLE market.certified_kline_lineage OWNER TO quant_admin;
        REVOKE UPDATE, DELETE ON market.certified_kline_lineage FROM PUBLIC;
        ALTER TABLE market.research_requirement_profiles ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'approved' CHECK (status IN ('draft', 'approved'));
        ALTER TABLE market.research_requirement_profiles ADD COLUMN contract JSONB NOT NULL DEFAULT '{}'::jsonb;
        INSERT INTO market.research_requirement_profiles (requirement_profile, required_fields, allowed_scopes, policy_version, enabled, status, contract)
        VALUES ('P3_REPLAY_DUAL_MA_RAW_OHLCV_V1', '["trading_date","open","high","low","close","volume","amount","adjustment","trading_calendar","corporate_action_status","available_at","dataset_hash","batch_hash","row_hash","input_snapshot_hash"]'::jsonb, '["p3_shadow_replay"]'::jsonb, 'p3-replay-dual-ma-input-v1', FALSE, 'draft', '{"raw_only":true,"pit":"available_at <= information_cutoff","fail_closed":true,"forbidden_fields":["qfq","hfq","estimated_available_at"]}'::jsonb);
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM market.research_requirement_profiles WHERE requirement_profile = 'P3_REPLAY_DUAL_MA_RAW_OHLCV_V1';
        ALTER TABLE market.research_requirement_profiles DROP COLUMN contract;
        ALTER TABLE market.research_requirement_profiles DROP COLUMN status;
        DROP TABLE IF EXISTS market.certified_kline_lineage;
    """)
