"""Add immutable strategy versions and independent approvals.

Revision ID: 028
Revises: 027
"""

from alembic import op


revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS strategy;

        CREATE TABLE IF NOT EXISTS strategy.strategies (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            strategy_type VARCHAR(64) NOT NULL,
            trade_mode VARCHAR(16) NOT NULL DEFAULT 'simulation'
                CHECK (trade_mode IN ('simulation', 'paper', 'live')),
            universe VARCHAR(64) NOT NULL DEFAULT 'watchlist',
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE strategy.strategies
            ADD COLUMN IF NOT EXISTS name VARCHAR(200);
        ALTER TABLE strategy.strategies
            ADD COLUMN IF NOT EXISTS strategy_type VARCHAR(64);
        ALTER TABLE strategy.strategies
            ADD COLUMN IF NOT EXISTS trade_mode VARCHAR(16) DEFAULT 'simulation';
        ALTER TABLE strategy.strategies
            ADD COLUMN IF NOT EXISTS universe VARCHAR(64) DEFAULT 'watchlist';
        ALTER TABLE strategy.strategies
            ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE strategy.strategies
            ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE strategy.strategies
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        CREATE INDEX IF NOT EXISTS idx_strategy_strategies_type_id
            ON strategy.strategies (strategy_type, id);

        CREATE TABLE strategy.strategy_version_heads (
            strategy_id INTEGER PRIMARY KEY
                REFERENCES strategy.strategies(id) ON DELETE RESTRICT,
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            active_version_id BIGINT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE strategy.strategy_versions (
            version_id BIGSERIAL PRIMARY KEY,
            strategy_id INTEGER NOT NULL
                REFERENCES strategy.strategies(id) ON DELETE RESTRICT,
            version_number INTEGER NOT NULL CHECK (version_number >= 1),
            enabled BOOLEAN NOT NULL,
            params JSONB NOT NULL,
            catalog_hash CHAR(64) NOT NULL
                CHECK (catalog_hash ~ '^[0-9a-f]{64}$'),
            config_hash CHAR(64) NOT NULL
                CHECK (config_hash ~ '^[0-9a-f]{64}$'),
            requester_principal_id UUID NOT NULL
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (strategy_id, version_number)
        );
        ALTER TABLE strategy.strategy_version_heads
            ADD CONSTRAINT fk_strategy_version_heads_active_version
            FOREIGN KEY (active_version_id)
            REFERENCES strategy.strategy_versions(version_id) ON DELETE RESTRICT;
        CREATE INDEX idx_strategy_versions_subject_version
            ON strategy.strategy_versions (strategy_id, version_number DESC);

        CREATE TABLE strategy.strategy_version_approvals (
            version_id BIGINT PRIMARY KEY
                REFERENCES strategy.strategy_versions(version_id) ON DELETE RESTRICT,
            status VARCHAR(16) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            approver_principal_id UUID
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (status = 'pending' AND approver_principal_id IS NULL AND approved_at IS NULL)
                OR (status = 'approved' AND approver_principal_id IS NOT NULL AND approved_at IS NOT NULL)
                OR (status = 'rejected' AND approver_principal_id IS NOT NULL AND approved_at IS NOT NULL)
            )
        );

        CREATE TABLE strategy.strategy_version_events (
            event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            version_id BIGINT NOT NULL
                REFERENCES strategy.strategy_versions(version_id) ON DELETE RESTRICT,
            event_type VARCHAR(32) NOT NULL
                CHECK (event_type IN ('submitted', 'approved')),
            actor_principal_id UUID NOT NULL
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_strategy_version_events_version_created
            ON strategy.strategy_version_events (version_id, created_at);

        CREATE OR REPLACE FUNCTION strategy.reject_strategy_version_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'strategy version and event rows are append-only';
        END;
        $$;
        DROP TRIGGER IF EXISTS strategy_versions_append_only
            ON strategy.strategy_versions;
        CREATE TRIGGER strategy_versions_append_only
            BEFORE UPDATE OR DELETE ON strategy.strategy_versions
            FOR EACH ROW EXECUTE FUNCTION strategy.reject_strategy_version_mutation();
        DROP TRIGGER IF EXISTS strategy_version_events_append_only
            ON strategy.strategy_version_events;
        CREATE TRIGGER strategy_version_events_append_only
            BEFORE UPDATE OR DELETE ON strategy.strategy_version_events
            FOR EACH ROW EXECUTE FUNCTION strategy.reject_strategy_version_mutation();

        ALTER TABLE strategy.strategies OWNER TO quant_admin;
        ALTER TABLE strategy.strategy_version_heads OWNER TO quant_admin;
        ALTER TABLE strategy.strategy_versions OWNER TO quant_admin;
        ALTER TABLE strategy.strategy_version_approvals OWNER TO quant_admin;
        ALTER TABLE strategy.strategy_version_events OWNER TO quant_admin;
        REVOKE UPDATE, DELETE ON strategy.strategy_versions,
            strategy.strategy_version_events FROM PUBLIC;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "028 contains immutable strategy governance records and cannot be downgraded destructively"
    )
