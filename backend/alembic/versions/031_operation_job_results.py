"""Persist operation Job results separately from status records.

Revision ID: 031
Revises: 030
"""

from alembic import op


revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit.async_job_results (
            job_id UUID PRIMARY KEY
                REFERENCES audit.async_jobs(job_id) ON DELETE RESTRICT,
            result_hash CHAR(64) NOT NULL
                CHECK (result_hash ~ '^[0-9a-f]{64}$'),
            result_payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE audit.async_job_results OWNER TO quant_admin;
        REVOKE UPDATE, DELETE ON audit.async_job_results FROM PUBLIC;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "031 preserves operation Job results and cannot be downgraded destructively"
    )
