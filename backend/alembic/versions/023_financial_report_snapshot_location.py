"""Add immutable financial report snapshots and page locations.

Revision ID: 023
Revises: 022
"""

from alembic import op


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.research_financial_report_snapshots (
            snapshot_id UUID PRIMARY KEY,
            evidence_id UUID NOT NULL
                REFERENCES market.research_evidence(evidence_id) ON DELETE RESTRICT,
            source_usage_review_id UUID NOT NULL
                REFERENCES market.research_source_usage_reviews(review_id) ON DELETE RESTRICT,
            expected_raw_hash VARCHAR(64) NOT NULL
                CHECK (expected_raw_hash ~ '^[0-9a-f]{64}$'),
            observed_raw_hash VARCHAR(64)
                CHECK (observed_raw_hash IS NULL OR observed_raw_hash ~ '^[0-9a-f]{64}$'),
            expected_bytes INTEGER NOT NULL CHECK (expected_bytes > 0),
            observed_bytes INTEGER CHECK (observed_bytes IS NULL OR observed_bytes > 0),
            content_type VARCHAR(128),
            acquisition_method VARCHAR(32) NOT NULL
                CHECK (acquisition_method = 'explicit_refetch'),
            storage_key TEXT,
            status VARCHAR(32) NOT NULL CHECK (
                status IN (
                    'observed', 'hash_mismatch', 'fetch_failed',
                    'validation_failed', 'write_failed'
                )
            ),
            failure_reason TEXT,
            fetched_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ NOT NULL,
            stored_at TIMESTAMPTZ,
            collector_version VARCHAR(64) NOT NULL
                CHECK (char_length(btrim(collector_version)) BETWEEN 1 AND 64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_financial_snapshot_status_fields CHECK (
                (status = 'observed'
                 AND observed_raw_hash IS NOT NULL
                 AND observed_raw_hash = expected_raw_hash
                 AND observed_bytes IS NOT NULL
                 AND observed_bytes = expected_bytes
                 AND content_type = 'application/pdf'
                 AND storage_key IS NOT NULL
                 AND char_length(btrim(storage_key)) BETWEEN 1 AND 500
                 AND fetched_at IS NOT NULL
                 AND stored_at IS NOT NULL
                 AND failure_reason IS NULL)
                OR
                (status <> 'observed'
                 AND storage_key IS NULL
                 AND stored_at IS NULL
                 AND failure_reason IS NOT NULL
                 AND char_length(btrim(failure_reason)) BETWEEN 1 AND 2000)
            )
        );
        CREATE UNIQUE INDEX uq_financial_report_snapshot_observed
        ON market.research_financial_report_snapshots (evidence_id, expected_raw_hash)
        WHERE status = 'observed';
        CREATE INDEX idx_financial_report_snapshots_evidence
        ON market.research_financial_report_snapshots (
            evidence_id, created_at DESC, snapshot_id DESC
        );

        CREATE TABLE market.research_financial_report_parse_runs (
            parse_run_id UUID PRIMARY KEY,
            snapshot_id UUID NOT NULL
                REFERENCES market.research_financial_report_snapshots(snapshot_id)
                ON DELETE RESTRICT,
            source_usage_review_id UUID NOT NULL
                REFERENCES market.research_source_usage_reviews(review_id) ON DELETE RESTRICT,
            parser_name VARCHAR(32) NOT NULL CHECK (parser_name = 'pypdf'),
            parser_version VARCHAR(32) NOT NULL CHECK (parser_version = '3.17.4'),
            normalization_version VARCHAR(64) NOT NULL
                CHECK (char_length(btrim(normalization_version)) BETWEEN 1 AND 64),
            status VARCHAR(32) NOT NULL CHECK (
                status IN (
                    'success', 'partial', 'text_unavailable', 'parse_failed',
                    'validation_failed', 'write_failed'
                )
            ),
            page_count INTEGER CHECK (page_count IS NULL OR page_count > 0),
            text_page_count INTEGER CHECK (text_page_count IS NULL OR text_page_count >= 0),
            failure_reason TEXT,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_financial_parse_run_counts CHECK (
                text_page_count IS NULL OR page_count IS NOT NULL
            ),
            CONSTRAINT ck_financial_parse_run_text_pages CHECK (
                text_page_count IS NULL OR text_page_count <= page_count
            ),
            CONSTRAINT ck_financial_parse_run_status_fields CHECK (
                (status = 'success'
                 AND page_count IS NOT NULL
                 AND text_page_count IS NOT NULL
                 AND text_page_count = page_count
                 AND failure_reason IS NULL)
                OR
                (status = 'partial'
                 AND page_count IS NOT NULL
                 AND text_page_count IS NOT NULL
                 AND text_page_count > 0
                 AND text_page_count < page_count
                 AND failure_reason IS NOT NULL
                 AND char_length(btrim(failure_reason)) BETWEEN 1 AND 2000)
                OR
                (status NOT IN ('success', 'partial')
                 AND failure_reason IS NOT NULL
                 AND char_length(btrim(failure_reason)) BETWEEN 1 AND 2000)
            ),
            CHECK (completed_at >= started_at)
        );
        CREATE UNIQUE INDEX uq_financial_report_parse_accepted
        ON market.research_financial_report_parse_runs (
            snapshot_id, parser_name, parser_version, normalization_version
        ) WHERE status IN ('success', 'partial');
        CREATE INDEX idx_financial_report_parse_runs_snapshot
        ON market.research_financial_report_parse_runs (
            snapshot_id, completed_at DESC, parse_run_id DESC
        );

        CREATE TABLE market.research_financial_report_page_evidence (
            page_evidence_id UUID PRIMARY KEY,
            parse_run_id UUID NOT NULL
                REFERENCES market.research_financial_report_parse_runs(parse_run_id)
                ON DELETE RESTRICT,
            page_number INTEGER NOT NULL CHECK (page_number > 0),
            extraction_status VARCHAR(32) NOT NULL CHECK (
                extraction_status IN ('text_observed', 'empty', 'failed')
            ),
            text_hash VARCHAR(64)
                CHECK (text_hash IS NULL OR text_hash ~ '^[0-9a-f]{64}$'),
            character_count INTEGER CHECK (
                character_count IS NULL OR character_count >= 0
            ),
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_financial_report_page_number UNIQUE (parse_run_id, page_number),
            CONSTRAINT uq_financial_report_page_binding UNIQUE (parse_run_id, page_evidence_id),
            CONSTRAINT ck_financial_report_page_status_fields CHECK (
                (extraction_status = 'text_observed'
                 AND text_hash IS NOT NULL
                 AND character_count IS NOT NULL
                 AND character_count > 0
                 AND failure_reason IS NULL)
                OR
                (extraction_status <> 'text_observed'
                 AND text_hash IS NULL
                 AND (character_count IS NULL OR character_count = 0)
                 AND failure_reason IS NOT NULL
                 AND char_length(btrim(failure_reason)) BETWEEN 1 AND 2000)
            )
        );

        CREATE TABLE market.research_financial_metadata_locations (
            location_id UUID PRIMARY KEY,
            parse_run_id UUID NOT NULL
                REFERENCES market.research_financial_report_parse_runs(parse_run_id)
                ON DELETE RESTRICT,
            page_evidence_id UUID,
            field_name VARCHAR(64) NOT NULL CHECK (
                field_name IN (
                    'report_period_end', 'statement_currency_unit',
                    'audit_opinion_section', 'statement_scope_heading'
                )
            ),
            raw_value TEXT CHECK (
                raw_value IS NULL OR char_length(raw_value) BETWEEN 1 AND 500
            ),
            normalized_value VARCHAR(128),
            match_start INTEGER CHECK (match_start IS NULL OR match_start >= 0),
            match_end INTEGER CHECK (match_end IS NULL OR match_end > 0),
            anchor_hash VARCHAR(64)
                CHECK (anchor_hash IS NULL OR anchor_hash ~ '^[0-9a-f]{64}$'),
            statement_scope VARCHAR(32) NOT NULL CHECK (
                statement_scope IN ('unresolved', 'consolidated', 'parent_company')
            ),
            status VARCHAR(32) NOT NULL CHECK (
                status IN ('located', 'ambiguous', 'unresolved', 'rejected')
            ),
            reason TEXT,
            locator_version VARCHAR(64) NOT NULL
                CHECK (char_length(btrim(locator_version)) BETWEEN 1 AND 64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_financial_metadata_location_page
                FOREIGN KEY (parse_run_id, page_evidence_id)
                REFERENCES market.research_financial_report_page_evidence(
                    parse_run_id, page_evidence_id
                ) ON DELETE RESTRICT,
            CONSTRAINT ck_financial_metadata_location_range CHECK (
                match_start IS NULL OR match_end > match_start
            ),
            CONSTRAINT ck_financial_metadata_location_status_fields CHECK (
                (status = 'located'
                 AND page_evidence_id IS NOT NULL
                 AND raw_value IS NOT NULL
                 AND normalized_value IS NOT NULL
                 AND char_length(btrim(normalized_value)) BETWEEN 1 AND 128
                 AND match_start IS NOT NULL
                 AND match_end IS NOT NULL
                 AND anchor_hash IS NOT NULL
                 AND reason IS NULL)
                OR
                (status IN ('ambiguous', 'rejected')
                 AND reason IS NOT NULL
                 AND char_length(btrim(reason)) BETWEEN 1 AND 2000)
                OR
                (status = 'unresolved'
                 AND page_evidence_id IS NULL
                 AND raw_value IS NULL
                 AND normalized_value IS NULL
                 AND match_start IS NULL
                 AND match_end IS NULL
                 AND anchor_hash IS NULL
                 AND statement_scope = 'unresolved'
                 AND reason IS NOT NULL
                 AND char_length(btrim(reason)) BETWEEN 1 AND 2000)
            )
        );
        CREATE INDEX idx_financial_metadata_locations_run
        ON market.research_financial_metadata_locations (
            parse_run_id, field_name, created_at, location_id
        );

        CREATE FUNCTION market.validate_financial_snapshot_insert()
        RETURNS trigger AS $$
        DECLARE
            evidence_hash VARCHAR(64);
            evidence_bytes INTEGER;
            review_scope VARCHAR(32);
            review_status VARCHAR(32);
            review_identity VARCHAR(32);
        BEGIN
            IF NEW.evidence_id NOT IN (
                'cef779d8-96d7-4a01-8ae3-2b9a023447e0'::uuid,
                '522d97a3-ff33-4001-81da-6575cd4ad8e3'::uuid
            ) THEN
                RAISE EXCEPTION 'financial snapshot evidence_id is outside the fixed Sprint14.9 scope';
            END IF;
            SELECT raw_hash, document_bytes
              INTO evidence_hash, evidence_bytes
              FROM market.research_evidence
             WHERE evidence_id = NEW.evidence_id
               AND evidence_type = 'financial_report'
               AND quality_status = 'observed'
               AND provider = 'cninfo'
               AND source = 'cninfo_listed_company_disclosure';
            IF NOT FOUND OR evidence_hash IS DISTINCT FROM NEW.expected_raw_hash
               OR evidence_bytes IS DISTINCT FROM NEW.expected_bytes THEN
                RAISE EXCEPTION 'financial snapshot expected hash or bytes do not match observed evidence';
            END IF;
            SELECT review.usage_scope, review.decision_status, review.identity_assurance
              INTO review_scope, review_status, review_identity
              FROM market.research_source_usage_reviews AS review
              JOIN market.research_source_terms_evidence AS terms
                ON terms.terms_evidence_id = review.terms_evidence_id
             WHERE review.review_id = NEW.source_usage_review_id
               AND terms.provider = 'cninfo'
               AND terms.source = 'cninfo_listed_company_disclosure';
            IF NOT FOUND OR review_scope IS DISTINCT FROM 'local_storage'
               OR review_status IS DISTINCT FROM 'review_required'
               OR review_identity IS DISTINCT FROM 'unverified' THEN
                RAISE EXCEPTION 'financial snapshot must reference an unverified review_required local_storage review';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_financial_snapshot_validate_insert
        BEFORE INSERT ON market.research_financial_report_snapshots
        FOR EACH ROW EXECUTE FUNCTION market.validate_financial_snapshot_insert();

        CREATE FUNCTION market.validate_financial_parse_run_insert()
        RETURNS trigger AS $$
        DECLARE
            snapshot_status VARCHAR(32);
            review_scope VARCHAR(32);
            review_status VARCHAR(32);
            review_identity VARCHAR(32);
        BEGIN
            SELECT status INTO snapshot_status
              FROM market.research_financial_report_snapshots
             WHERE snapshot_id = NEW.snapshot_id;
            IF NOT FOUND OR snapshot_status IS DISTINCT FROM 'observed' THEN
                RAISE EXCEPTION 'financial parse run requires an observed snapshot';
            END IF;
            SELECT review.usage_scope, review.decision_status, review.identity_assurance
              INTO review_scope, review_status, review_identity
              FROM market.research_source_usage_reviews AS review
              JOIN market.research_source_terms_evidence AS terms
                ON terms.terms_evidence_id = review.terms_evidence_id
             WHERE review.review_id = NEW.source_usage_review_id
               AND terms.provider = 'cninfo'
               AND terms.source = 'cninfo_listed_company_disclosure';
            IF NOT FOUND OR review_scope IS DISTINCT FROM 'derived_research'
               OR review_status IS DISTINCT FROM 'review_required'
               OR review_identity IS DISTINCT FROM 'unverified' THEN
                RAISE EXCEPTION 'financial parse run must reference an unverified review_required derived_research review';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_financial_parse_run_validate_insert
        BEFORE INSERT ON market.research_financial_report_parse_runs
        FOR EACH ROW EXECUTE FUNCTION market.validate_financial_parse_run_insert();

        CREATE FUNCTION market.validate_financial_page_insert()
        RETURNS trigger AS $$
        DECLARE run_status VARCHAR(32);
        BEGIN
            SELECT status INTO run_status
              FROM market.research_financial_report_parse_runs
             WHERE parse_run_id = NEW.parse_run_id;
            IF NOT FOUND OR run_status NOT IN ('success', 'partial') THEN
                RAISE EXCEPTION 'financial page evidence requires an accepted parse run';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_financial_page_validate_insert
        BEFORE INSERT ON market.research_financial_report_page_evidence
        FOR EACH ROW EXECUTE FUNCTION market.validate_financial_page_insert();

        CREATE FUNCTION market.validate_financial_location_insert()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.page_evidence_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                  FROM market.research_financial_report_page_evidence
                 WHERE parse_run_id = NEW.parse_run_id
                   AND page_evidence_id = NEW.page_evidence_id
                   AND extraction_status = 'text_observed'
            ) THEN
                RAISE EXCEPTION 'financial metadata location requires text-observed page evidence from the same parse run';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_financial_location_validate_insert
        BEFORE INSERT ON market.research_financial_metadata_locations
        FOR EACH ROW EXECUTE FUNCTION market.validate_financial_location_insert();

        CREATE FUNCTION market.reject_financial_snapshot_location_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'financial snapshot, parse and location evidence is append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_financial_snapshots_immutable
        BEFORE UPDATE OR DELETE ON market.research_financial_report_snapshots
        FOR EACH ROW EXECUTE FUNCTION market.reject_financial_snapshot_location_mutation();
        CREATE TRIGGER trg_financial_parse_runs_immutable
        BEFORE UPDATE OR DELETE ON market.research_financial_report_parse_runs
        FOR EACH ROW EXECUTE FUNCTION market.reject_financial_snapshot_location_mutation();
        CREATE TRIGGER trg_financial_page_evidence_immutable
        BEFORE UPDATE OR DELETE ON market.research_financial_report_page_evidence
        FOR EACH ROW EXECUTE FUNCTION market.reject_financial_snapshot_location_mutation();
        CREATE TRIGGER trg_financial_metadata_locations_immutable
        BEFORE UPDATE OR DELETE ON market.research_financial_metadata_locations
        FOR EACH ROW EXECUTE FUNCTION market.reject_financial_snapshot_location_mutation();

        ALTER TABLE market.research_financial_report_snapshots OWNER TO quant_admin;
        ALTER TABLE market.research_financial_report_parse_runs OWNER TO quant_admin;
        ALTER TABLE market.research_financial_report_page_evidence OWNER TO quant_admin;
        ALTER TABLE market.research_financial_metadata_locations OWNER TO quant_admin;
        ALTER FUNCTION market.validate_financial_snapshot_insert() OWNER TO quant_admin;
        ALTER FUNCTION market.validate_financial_parse_run_insert() OWNER TO quant_admin;
        ALTER FUNCTION market.validate_financial_page_insert() OWNER TO quant_admin;
        ALTER FUNCTION market.validate_financial_location_insert() OWNER TO quant_admin;
        ALTER FUNCTION market.reject_financial_snapshot_location_mutation() OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS market.research_financial_metadata_locations;
        DROP TABLE IF EXISTS market.research_financial_report_page_evidence;
        DROP TABLE IF EXISTS market.research_financial_report_parse_runs;
        DROP TABLE IF EXISTS market.research_financial_report_snapshots;
        DROP FUNCTION IF EXISTS market.validate_financial_location_insert();
        DROP FUNCTION IF EXISTS market.validate_financial_page_insert();
        DROP FUNCTION IF EXISTS market.validate_financial_parse_run_insert();
        DROP FUNCTION IF EXISTS market.validate_financial_snapshot_insert();
        DROP FUNCTION IF EXISTS market.reject_financial_snapshot_location_mutation();
        """
    )
