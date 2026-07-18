"""Add durable async jobs for governed long-running operations.

Revision ID: 027
Revises: 026
"""

from alembic import op


revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit.async_jobs (
            job_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            job_type VARCHAR(64) NOT NULL,
            requester_principal_id UUID NOT NULL
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            idempotency_key VARCHAR(128) NOT NULL
                CHECK (char_length(btrim(idempotency_key)) BETWEEN 8 AND 128),
            input_hash CHAR(64) NOT NULL
                CHECK (input_hash ~ '^[0-9a-f]{64}$'),
            input_payload JSONB NOT NULL,
            status VARCHAR(24) NOT NULL CHECK (status IN (
                'queued', 'running', 'retry_wait', 'succeeded', 'failed',
                'cancel_requested', 'cancelled', 'blocked'
            )),
            progress SMALLINT NOT NULL DEFAULT 0
                CHECK (progress BETWEEN 0 AND 100),
            result_ref VARCHAR(256),
            error_code VARCHAR(96),
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            max_retries INTEGER NOT NULL DEFAULT 2 CHECK (max_retries BETWEEN 0 AND 10),
            next_retry_at TIMESTAMPTZ,
            worker_principal_id UUID REFERENCES auth.principals(principal_id)
                ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            cancel_requested_at TIMESTAMPTZ,
            UNIQUE (requester_principal_id, idempotency_key)
        );
        CREATE INDEX idx_async_jobs_runnable
            ON audit.async_jobs (job_type, status, next_retry_at, created_at)
            WHERE status IN ('queued', 'retry_wait');
        CREATE INDEX idx_async_jobs_requester_created
            ON audit.async_jobs (requester_principal_id, created_at DESC);

        CREATE TABLE audit.async_job_attempts (
            attempt_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            job_id UUID NOT NULL REFERENCES audit.async_jobs(job_id) ON DELETE RESTRICT,
            attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
            worker_principal_id UUID REFERENCES auth.principals(principal_id)
                ON DELETE RESTRICT,
            status VARCHAR(24) NOT NULL CHECK (status IN (
                'running', 'retry_wait', 'succeeded', 'failed', 'cancelled', 'blocked'
            )),
            error_code VARCHAR(96),
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            UNIQUE (job_id, attempt_number)
        );
        CREATE INDEX idx_async_job_attempts_job ON audit.async_job_attempts (job_id, attempt_number DESC);

        ALTER TABLE audit.async_jobs OWNER TO quant_admin;
        ALTER TABLE audit.async_job_attempts OWNER TO quant_admin;
        REVOKE UPDATE, DELETE ON audit.async_jobs, audit.async_job_attempts FROM PUBLIC;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "027 contains async job audit state and cannot be downgraded destructively"
    )
