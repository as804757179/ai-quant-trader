"""Add append-only execution approvals, order intents, and broker outbox."""

from alembic import op


revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE trade.execution_approvals (
            approval_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            action_type VARCHAR(64) NOT NULL,
            mode VARCHAR(16) NOT NULL CHECK (mode IN ('simulation', 'paper', 'live')),
            payload_hash CHAR(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            requester_principal_id UUID NOT NULL REFERENCES auth.principals(principal_id),
            approver_principal_id UUID REFERENCES auth.principals(principal_id),
            data_authorization_ref VARCHAR(200),
            status VARCHAR(16) NOT NULL CHECK (status IN ('requested', 'approved', 'consumed', 'expired', 'rejected')),
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            approved_at TIMESTAMPTZ,
            CHECK (approver_principal_id IS NULL OR approver_principal_id <> requester_principal_id),
            CHECK ((status = 'approved' AND approver_principal_id IS NOT NULL AND approved_at IS NOT NULL)
                OR status <> 'approved'),
            CHECK ((status = 'consumed' AND consumed_at IS NOT NULL) OR status <> 'consumed')
        );
        CREATE INDEX idx_execution_approvals_active ON trade.execution_approvals
            (payload_hash, action_type, expires_at DESC)
            WHERE status IN ('requested', 'approved');

        CREATE TABLE trade.execution_approval_events (
            event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            approval_id UUID NOT NULL REFERENCES trade.execution_approvals(approval_id),
            event_type VARCHAR(32) NOT NULL,
            actor_principal_id UUID NOT NULL REFERENCES auth.principals(principal_id),
            event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE FUNCTION trade.reject_execution_approval_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'execution approval events are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_execution_approval_events_immutable
        BEFORE UPDATE OR DELETE ON trade.execution_approval_events
        FOR EACH ROW EXECUTE FUNCTION trade.reject_execution_approval_event_mutation();

        CREATE TABLE trade.order_intents (
            intent_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            principal_id UUID NOT NULL REFERENCES auth.principals(principal_id),
            client_intent_key VARCHAR(128) NOT NULL,
            payload_hash CHAR(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            mode VARCHAR(16) NOT NULL CHECK (mode IN ('simulation', 'paper', 'live')),
            status VARCHAR(24) NOT NULL CHECK (status IN ('pending', 'submitted', 'uncertain', 'reconciled', 'rejected')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            UNIQUE (principal_id, client_intent_key)
        );

        CREATE TABLE trade.broker_outbox (
            outbox_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            intent_id UUID NOT NULL REFERENCES trade.order_intents(intent_id),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            status VARCHAR(16) NOT NULL CHECK (status IN ('pending', 'sent', 'uncertain', 'reconciled')),
            request_payload JSONB NOT NULL,
            response_payload JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE trade.execution_approvals OWNER TO quant_admin;
        ALTER TABLE trade.execution_approval_events OWNER TO quant_admin;
        ALTER TABLE trade.order_intents OWNER TO quant_admin;
        ALTER TABLE trade.broker_outbox OWNER TO quant_admin;
        ALTER FUNCTION trade.reject_execution_approval_event_mutation() OWNER TO quant_admin;
        REVOKE UPDATE, DELETE ON trade.execution_approvals, trade.execution_approval_events FROM PUBLIC;
        """
    )


def downgrade() -> None:
    raise RuntimeError("025 is append-only governance data and must not be downgraded")
