"""Add P3-0 shadow-only storage contracts.

Revision ID: 042
Revises: 041
"""

from alembic import op


revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS shadow;

        CREATE TABLE shadow.runs (
            run_id UUID PRIMARY KEY,
            idempotency_key VARCHAR(128) NOT NULL UNIQUE,
            request_hash CHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL
                CHECK (status IN ('created', 'running', 'blocked', 'succeeded', 'failed')),
            block_code VARCHAR(96),
            data_mode VARCHAR(16) NOT NULL
                CHECK (data_mode IN ('test', 'replay', 'realtime')),
            not_realtime BOOLEAN NOT NULL,
            realtime_data_approved BOOLEAN NOT NULL DEFAULT FALSE,
            provider VARCHAR(64),
            source VARCHAR(128),
            dataset_version VARCHAR(128),
            license_evidence_ref VARCHAR(256),
            sample_reference_id VARCHAR(256),
            sample_hash CHAR(64),
            strategy_reference_id VARCHAR(256),
            strategy_hash CHAR(64),
            input_profile_reference_id VARCHAR(256),
            input_profile_hash CHAR(64),
            information_cutoff TIMESTAMPTZ,
            input_snapshot_hash CHAR(64),
            result_hash CHAR(64),
            tradable BOOLEAN NOT NULL DEFAULT FALSE CHECK (tradable = FALSE),
            order_created BOOLEAN NOT NULL DEFAULT FALSE CHECK (order_created = FALSE),
            order_count INTEGER NOT NULL DEFAULT 0 CHECK (order_count = 0),
            order_service_calls INTEGER NOT NULL DEFAULT 0 CHECK (order_service_calls = 0),
            execution_service_calls INTEGER NOT NULL DEFAULT 0 CHECK (execution_service_calls = 0),
            capital_write_count INTEGER NOT NULL DEFAULT 0 CHECK (capital_write_count = 0),
            position_write_count INTEGER NOT NULL DEFAULT 0 CHECK (position_write_count = 0),
            release_locks_before JSONB NOT NULL DEFAULT '{}'::jsonb,
            release_locks_after JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            CHECK (
                (data_mode IN ('test', 'replay') AND not_realtime = TRUE)
                OR (data_mode = 'realtime' AND not_realtime = FALSE AND realtime_data_approved = TRUE)
            )
        );

        CREATE TABLE shadow.run_input_batches (
            input_batch_id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES shadow.runs(run_id) ON DELETE RESTRICT,
            batch_id VARCHAR(256) NOT NULL,
            raw_hash CHAR(64) NOT NULL,
            provider_time TIMESTAMPTZ,
            fetched_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            data_as_of TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (fetched_at <= received_at),
            UNIQUE (run_id, batch_id, raw_hash)
        );

        CREATE TABLE shadow.decisions (
            decision_id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES shadow.runs(run_id) ON DELETE RESTRICT,
            stock_code VARCHAR(32) NOT NULL,
            information_cutoff TIMESTAMPTZ NOT NULL,
            decision_state VARCHAR(24) NOT NULL
                CHECK (decision_state IN ('recorded', 'blocked', 'unavailable', 'degraded')),
            would_action VARCHAR(16),
            reason_code VARCHAR(96) NOT NULL,
            decision_rule_hash CHAR(64) NOT NULL,
            decision_dedup_key CHAR(64) NOT NULL UNIQUE,
            evidence_hash CHAR(64) NOT NULL,
            tradable BOOLEAN NOT NULL DEFAULT FALSE CHECK (tradable = FALSE),
            order_created BOOLEAN NOT NULL DEFAULT FALSE CHECK (order_created = FALSE),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE shadow.decision_evidence (
            decision_evidence_id UUID PRIMARY KEY,
            decision_id UUID NOT NULL REFERENCES shadow.decisions(decision_id) ON DELETE RESTRICT,
            input_batch_id UUID REFERENCES shadow.run_input_batches(input_batch_id) ON DELETE RESTRICT,
            evidence_reference_id VARCHAR(256) NOT NULL,
            evidence_hash CHAR(64) NOT NULL,
            evidence_type VARCHAR(64) NOT NULL,
            available_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (decision_id, evidence_reference_id, evidence_hash)
        );

        CREATE INDEX idx_shadow_runs_created_at ON shadow.runs (created_at DESC, run_id);
        CREATE INDEX idx_shadow_runs_status_created_at ON shadow.runs (status, created_at DESC, run_id);
        CREATE INDEX idx_shadow_input_batches_run ON shadow.run_input_batches (run_id, created_at, input_batch_id);
        CREATE INDEX idx_shadow_decisions_run ON shadow.decisions (run_id, created_at, decision_id);
        CREATE INDEX idx_shadow_decisions_stock_cutoff ON shadow.decisions (stock_code, information_cutoff DESC, decision_id);
        CREATE INDEX idx_shadow_decision_evidence_decision ON shadow.decision_evidence (decision_id, created_at, decision_evidence_id);

        ALTER TABLE shadow.runs OWNER TO quant_admin;
        ALTER TABLE shadow.run_input_batches OWNER TO quant_admin;
        ALTER TABLE shadow.decisions OWNER TO quant_admin;
        ALTER TABLE shadow.decision_evidence OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    raise RuntimeError("042 preserves P3-0 shadow audit records and cannot be downgraded destructively")
