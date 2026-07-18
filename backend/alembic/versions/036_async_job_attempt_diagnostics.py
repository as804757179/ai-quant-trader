"""Persist safe operation-job execution diagnostics."""

from alembic import op


revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE audit.async_jobs
            ADD COLUMN IF NOT EXISTS last_stage VARCHAR(64);
        ALTER TABLE audit.async_job_attempts
            ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(64),
            ADD COLUMN IF NOT EXISTS last_stage VARCHAR(64),
            ADD COLUMN IF NOT EXISTS error_type VARCHAR(128),
            ADD COLUMN IF NOT EXISTS error_message VARCHAR(512),
            ADD COLUMN IF NOT EXISTS error_stage VARCHAR(64),
            ADD COLUMN IF NOT EXISTS http_status INTEGER,
            ADD COLUMN IF NOT EXISTS response_summary VARCHAR(512),
            ADD COLUMN IF NOT EXISTS traceback_summary TEXT;
        """
    )


def downgrade() -> None:
    raise RuntimeError("036 preserves operation-job diagnostics and must not be downgraded")
