"""Add append-only rule-level quality result records."""

from alembic import op


revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.data_quality_results (
            quality_result_id VARCHAR(64) PRIMARY KEY,
            batch_id VARCHAR(64) NOT NULL
                REFERENCES market.data_batches(batch_id) ON DELETE RESTRICT,
            rule_code VARCHAR(64) NOT NULL,
            rule_version VARCHAR(64) NOT NULL,
            audit_scope VARCHAR(20) NOT NULL CHECK (audit_scope = 'batch'),
            result VARCHAR(20) NOT NULL CHECK (result IN ('pass', 'fail', 'not_evaluated')),
            reject_reason TEXT,
            input_hash VARCHAR(128) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (batch_id, rule_code, rule_version)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_data_quality_results_query
        ON market.data_quality_results(batch_id, created_at DESC, quality_result_id DESC)
        """
    )
    op.execute(
        """
        CREATE FUNCTION market.reject_data_quality_result_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'data quality results are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_data_quality_results_immutable
        BEFORE UPDATE OR DELETE ON market.data_quality_results
        FOR EACH ROW EXECUTE FUNCTION market.reject_data_quality_result_mutation();
        """
    )
    op.execute("ALTER TABLE market.data_quality_results OWNER TO quant_admin")
    op.execute("ALTER FUNCTION market.reject_data_quality_result_mutation() OWNER TO quant_admin")


def downgrade() -> None:
    raise RuntimeError("040 preserves data quality audit records and must not be downgraded")
