"""Add principal, credential, and browser-session governance.

Revision ID: 024
Revises: 023
"""

from alembic import op


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS auth;

        CREATE TABLE auth.principals (
            principal_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            display_name VARCHAR(100) NOT NULL UNIQUE,
            principal_type VARCHAR(16) NOT NULL
                CHECK (principal_type IN ('human', 'service')),
            role VARCHAR(32) NOT NULL CHECK (
                role IN (
                    'viewer', 'data_operator', 'research_reviewer',
                    'strategy_admin', 'risk_admin', 'trader', 'auditor',
                    'service_worker', 'admin'
                )
            ),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            disabled_at TIMESTAMPTZ,
            CHECK (
                (is_active IS TRUE AND disabled_at IS NULL)
                OR (is_active IS FALSE AND disabled_at IS NOT NULL)
            )
        );

        CREATE TABLE auth.api_credentials (
            credential_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            principal_id UUID NOT NULL
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            token_prefix VARCHAR(16) NOT NULL
                CHECK (char_length(btrim(token_prefix)) BETWEEN 8 AND 16),
            token_digest CHAR(64) NOT NULL UNIQUE
                CHECK (token_digest ~ '^[0-9a-f]{64}$'),
            scopes TEXT[] NOT NULL CHECK (cardinality(scopes) > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            revoked_reason VARCHAR(500),
            CHECK (expires_at IS NULL OR expires_at > created_at),
            CHECK (
                (revoked_at IS NULL AND revoked_reason IS NULL)
                OR (revoked_at IS NOT NULL AND revoked_reason IS NOT NULL)
            )
        );
        CREATE INDEX idx_api_credentials_principal_active
            ON auth.api_credentials (principal_id, created_at DESC)
            WHERE revoked_at IS NULL;

        CREATE TABLE auth.api_sessions (
            session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            principal_id UUID NOT NULL
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            credential_id UUID NOT NULL
                REFERENCES auth.api_credentials(credential_id) ON DELETE RESTRICT,
            session_digest CHAR(64) NOT NULL UNIQUE
                CHECK (session_digest ~ '^[0-9a-f]{64}$'),
            csrf_digest CHAR(64) NOT NULL
                CHECK (csrf_digest ~ '^[0-9a-f]{64}$'),
            scopes TEXT[] NOT NULL CHECK (cardinality(scopes) > 0),
            created_ip INET,
            user_agent VARCHAR(512) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            CHECK (expires_at > created_at),
            CHECK (revoked_at IS NULL OR revoked_at >= created_at)
        );
        CREATE INDEX idx_api_sessions_digest_active
            ON auth.api_sessions (session_digest)
            WHERE revoked_at IS NULL;
        CREATE INDEX idx_api_sessions_principal_active
            ON auth.api_sessions (principal_id, expires_at DESC)
            WHERE revoked_at IS NULL;

        ALTER SCHEMA auth OWNER TO quant_admin;
        ALTER TABLE auth.principals OWNER TO quant_admin;
        ALTER TABLE auth.api_credentials OWNER TO quant_admin;
        ALTER TABLE auth.api_sessions OWNER TO quant_admin;
        REVOKE UPDATE, DELETE ON auth.api_credentials FROM PUBLIC;
        REVOKE DELETE ON auth.api_sessions FROM PUBLIC;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "024 contains security audit state and cannot be downgraded destructively; "
        "revoke credentials and sessions instead."
    )
