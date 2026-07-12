"""Harden Sprint13 run binding and checkpoint audit fields.

Revision ID: 014
Revises: 013
"""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.dataset_expansion_runs
          ADD COLUMN period VARCHAR(10),
          ADD COLUMN adjustment VARCHAR(10),
          ADD COLUMN importer_version VARCHAR(64),
          ADD COLUMN normalizer_version VARCHAR(64),
          ADD COLUMN schema_version VARCHAR(32);
        UPDATE market.dataset_expansion_runs SET
          period='1d', adjustment='raw',
          importer_version='sprint07-sohu-certified-store-v1',
          normalizer_version='sprint07-kline-contract-v1',
          schema_version='certified-kline-v1';
        ALTER TABLE market.dataset_expansion_runs
          ALTER COLUMN period SET NOT NULL,
          ALTER COLUMN adjustment SET NOT NULL,
          ALTER COLUMN importer_version SET NOT NULL,
          ALTER COLUMN normalizer_version SET NOT NULL,
          ALTER COLUMN schema_version SET NOT NULL;

        ALTER TABLE market.dataset_import_checkpoints
          DROP CONSTRAINT dataset_import_checkpoints_status_check,
          ADD COLUMN last_attempt_at TIMESTAMPTZ,
          ADD COLUMN error_type VARCHAR(80),
          ADD COLUMN content_validation_hash CHAR(64),
          ADD CONSTRAINT dataset_import_checkpoints_status_check CHECK(status IN
            ('pending','running','certified','rejected','fetch_failed','validation_failed','review_required','write_failed'));
        UPDATE market.dataset_import_checkpoints SET last_attempt_at=updated_at;

        UPDATE market.security_status_reviews
           SET status='unresolved',
               evidence_source=evidence_source || '; ordinary identity does not prove daily status',
               evidence_version='sprint13.1-neutral-security-status-v1',
               reviewed_at=NOW()
         WHERE run_id='sprint13-controlled-certified-v1-run1' AND status='normal_trade';

        CREATE FUNCTION market.reject_dataset_run_binding_change() RETURNS trigger AS $$
        BEGIN
          IF ROW(NEW.dataset_id,NEW.manifest_hash,NEW.primary_provider,NEW.secondary_provider,
                 NEW.date_from,NEW.date_to,NEW.period,NEW.adjustment,NEW.importer_version,
                 NEW.normalizer_version,NEW.schema_version)
             IS DISTINCT FROM
             ROW(OLD.dataset_id,OLD.manifest_hash,OLD.primary_provider,OLD.secondary_provider,
                 OLD.date_from,OLD.date_to,OLD.period,OLD.adjustment,OLD.importer_version,
                 OLD.normalizer_version,OLD.schema_version) THEN
            RAISE EXCEPTION 'dataset expansion run binding is immutable; create a new run_id and dataset_id';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_dataset_run_binding_immutable
          BEFORE UPDATE ON market.dataset_expansion_runs
          FOR EACH ROW EXECUTE FUNCTION market.reject_dataset_run_binding_change();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER trg_dataset_run_binding_immutable ON market.dataset_expansion_runs;
        DROP FUNCTION market.reject_dataset_run_binding_change();
        ALTER TABLE market.dataset_import_checkpoints
          DROP CONSTRAINT dataset_import_checkpoints_status_check,
          DROP COLUMN last_attempt_at,
          DROP COLUMN error_type,
          DROP COLUMN content_validation_hash,
          ADD CONSTRAINT dataset_import_checkpoints_status_check CHECK(status IN
            ('pending','running','certified','rejected','fetch_failed','validation_failed','review_required'));
        ALTER TABLE market.dataset_expansion_runs
          DROP COLUMN period, DROP COLUMN adjustment, DROP COLUMN importer_version,
          DROP COLUMN normalizer_version, DROP COLUMN schema_version;
        """
    )
