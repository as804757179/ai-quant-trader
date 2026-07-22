"""Add append-only strategy admission lifecycle governance.

Revision ID: 043
Revises: 042
"""

from alembic import op


revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE strategy.strategy_version_validity_events (
            event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            strategy_id INTEGER NOT NULL
                REFERENCES strategy.strategies(id) ON DELETE RESTRICT,
            version_id BIGINT NOT NULL
                REFERENCES strategy.strategy_versions(version_id) ON DELETE RESTRICT,
            event_type VARCHAR(16) NOT NULL
                CHECK (event_type IN ('activated', 'revoked', 'expired')),
            effective_at TIMESTAMPTZ NOT NULL,
            valid_until TIMESTAMPTZ,
            reason TEXT NOT NULL,
            actor_principal_id UUID NOT NULL
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            idempotency_key VARCHAR(128) NOT NULL,
            request_hash CHAR(64) NOT NULL
                CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (event_type = 'activated' AND valid_until IS NOT NULL)
                OR (event_type IN ('revoked', 'expired') AND valid_until IS NULL)
            ),
            CHECK (valid_until IS NULL OR valid_until > effective_at),
            UNIQUE (actor_principal_id, idempotency_key),
            UNIQUE (version_id, event_type, effective_at)
        );

        CREATE INDEX idx_strategy_validity_events_version_effective
            ON strategy.strategy_version_validity_events
                (version_id, effective_at DESC, event_id);
        CREATE INDEX idx_strategy_validity_events_strategy_effective
            ON strategy.strategy_version_validity_events
                (strategy_id, effective_at DESC, event_id);
        CREATE UNIQUE INDEX uq_strategy_active_subject_type
            ON strategy.strategies (strategy_type)
            WHERE is_active IS TRUE;

        CREATE OR REPLACE FUNCTION strategy.verify_validity_event_version_owner()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM strategy.strategy_versions
                WHERE version_id = NEW.version_id AND strategy_id = NEW.strategy_id
            ) THEN
                RAISE EXCEPTION 'validity event strategy_id must own version_id';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER strategy_validity_events_version_owner
            BEFORE INSERT ON strategy.strategy_version_validity_events
            FOR EACH ROW EXECUTE FUNCTION strategy.verify_validity_event_version_owner();
        CREATE TRIGGER strategy_validity_events_append_only
            BEFORE UPDATE OR DELETE ON strategy.strategy_version_validity_events
            FOR EACH ROW EXECUTE FUNCTION strategy.reject_strategy_version_mutation();

        ALTER TABLE strategy.strategy_version_validity_events OWNER TO quant_admin;
        REVOKE UPDATE, DELETE ON strategy.strategy_version_validity_events FROM PUBLIC;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS strategy.uq_strategy_active_subject_type;
        DROP TABLE IF EXISTS strategy.strategy_version_validity_events;
        DROP FUNCTION IF EXISTS strategy.verify_validity_event_version_owner();
        """
    )
