"""Add append-only reviews for financial metadata locations."""

from alembic import op


revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.research_financial_metadata_location_reviews (
            review_id UUID PRIMARY KEY,
            evidence_id UUID NOT NULL
                REFERENCES market.research_evidence(evidence_id) ON DELETE RESTRICT,
            location_id UUID NOT NULL
                REFERENCES market.research_financial_metadata_locations(location_id)
                ON DELETE RESTRICT,
            snapshot_id UUID NOT NULL
                REFERENCES market.research_financial_report_snapshots(snapshot_id)
                ON DELETE RESTRICT,
            parse_run_id UUID NOT NULL
                REFERENCES market.research_financial_report_parse_runs(parse_run_id)
                ON DELETE RESTRICT,
            page_evidence_id UUID NOT NULL,
            raw_hash CHAR(64) NOT NULL
                CHECK (raw_hash ~ '^[0-9a-f]{64}$'),
            locator_version VARCHAR(64) NOT NULL
                CHECK (char_length(btrim(locator_version)) BETWEEN 1 AND 64),
            reviewer_label VARCHAR(128) NOT NULL
                CHECK (char_length(btrim(reviewer_label)) BETWEEN 1 AND 128),
            reviewer_principal_id UUID NOT NULL
                REFERENCES auth.principals(principal_id) ON DELETE RESTRICT,
            idempotency_key VARCHAR(128) NOT NULL
                CHECK (char_length(btrim(idempotency_key)) BETWEEN 8 AND 128),
            request_hash CHAR(64) NOT NULL
                CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            conclusion VARCHAR(32) NOT NULL
                CHECK (conclusion IN (
                    'confirmed', 'rejected', 'ambiguous', 'needs_more_evidence'
                )),
            reason TEXT NOT NULL
                CHECK (char_length(btrim(reason)) BETWEEN 1 AND 2000),
            reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_financial_location_review_page
                FOREIGN KEY (parse_run_id, page_evidence_id)
                REFERENCES market.research_financial_report_page_evidence(
                    parse_run_id, page_evidence_id
                ) ON DELETE RESTRICT
        );
        CREATE INDEX idx_financial_location_reviews_evidence_latest
        ON market.research_financial_metadata_location_reviews (
            evidence_id, reviewed_at DESC, review_id DESC
        );
        CREATE INDEX idx_financial_location_reviews_location_latest
        ON market.research_financial_metadata_location_reviews (
            location_id, reviewed_at DESC, review_id DESC
        );
        CREATE UNIQUE INDEX uq_financial_location_review_principal_idempotency
        ON market.research_financial_metadata_location_reviews (
            reviewer_principal_id, idempotency_key
        );

        CREATE FUNCTION market.validate_financial_location_review_insert()
        RETURNS trigger AS $$
        DECLARE
            location_evidence_id UUID;
            location_snapshot_id UUID;
            location_parse_run_id UUID;
            location_page_evidence_id UUID;
            location_raw_hash CHAR(64);
            location_locator_version VARCHAR(64);
            page_status VARCHAR(32);
        BEGIN
            SELECT snapshot.evidence_id, snapshot.snapshot_id, location.parse_run_id,
                   location.page_evidence_id, snapshot.observed_raw_hash,
                   location.locator_version, page.extraction_status
              INTO location_evidence_id, location_snapshot_id, location_parse_run_id,
                   location_page_evidence_id, location_raw_hash,
                   location_locator_version, page_status
              FROM market.research_financial_metadata_locations AS location
              INNER JOIN market.research_financial_report_parse_runs AS run
                ON run.parse_run_id = location.parse_run_id
              INNER JOIN market.research_financial_report_snapshots AS snapshot
                ON snapshot.snapshot_id = run.snapshot_id
              LEFT JOIN market.research_financial_report_page_evidence AS page
                ON page.parse_run_id = location.parse_run_id
               AND page.page_evidence_id = location.page_evidence_id
             WHERE location.location_id = NEW.location_id;

            IF NOT FOUND
               OR location_evidence_id IS DISTINCT FROM NEW.evidence_id
               OR location_snapshot_id IS DISTINCT FROM NEW.snapshot_id
               OR location_parse_run_id IS DISTINCT FROM NEW.parse_run_id
               OR location_page_evidence_id IS DISTINCT FROM NEW.page_evidence_id
               OR location_raw_hash IS DISTINCT FROM NEW.raw_hash
               OR location_locator_version IS DISTINCT FROM NEW.locator_version
               OR page_status IS DISTINCT FROM 'text_observed' THEN
                RAISE EXCEPTION 'financial location review binding is invalid or stale';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_financial_location_review_validate_insert
        BEFORE INSERT ON market.research_financial_metadata_location_reviews
        FOR EACH ROW EXECUTE FUNCTION market.validate_financial_location_review_insert();

        CREATE FUNCTION market.reject_financial_location_review_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'financial location reviews are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_financial_location_reviews_immutable
        BEFORE UPDATE OR DELETE ON market.research_financial_metadata_location_reviews
        FOR EACH ROW EXECUTE FUNCTION market.reject_financial_location_review_mutation();

        ALTER TABLE market.research_financial_metadata_location_reviews OWNER TO quant_admin;
        ALTER FUNCTION market.validate_financial_location_review_insert() OWNER TO quant_admin;
        ALTER FUNCTION market.reject_financial_location_review_mutation() OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    raise RuntimeError("039 preserves financial location review audit records and must not be downgraded")
