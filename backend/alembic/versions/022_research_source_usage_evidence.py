"""Add immutable source terms evidence and usage pre-reviews.

Revision ID: 022
Revises: 021
"""

from alembic import op


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


CNINFO_SOURCE_SCOPE = (
    "cninfo:hisAnnouncement/query+static.cninfo.com.cn/finalpage"
)
GDELT_SOURCE_SCOPE = (
    "gdelt:storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss:metadata-only"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE market.research_source_terms_evidence (
            terms_evidence_id UUID PRIMARY KEY,
            provider VARCHAR(64) NOT NULL,
            source VARCHAR(128) NOT NULL,
            source_scope TEXT NOT NULL,
            document_kind VARCHAR(32) NOT NULL CHECK (
                document_kind IN (
                    'terms_of_use', 'license', 'data_policy', 'robots', 'other_official'
                )
            ),
            terms_url TEXT NOT NULL,
            retrieved_at TIMESTAMPTZ,
            source_effective_at TIMESTAMPTZ,
            source_time_precision VARCHAR(16) NOT NULL CHECK (
                source_time_precision IN ('exact', 'date', 'unresolved')
            ),
            raw_hash VARCHAR(64),
            document_bytes INTEGER,
            content_type VARCHAR(128),
            status VARCHAR(32) NOT NULL CHECK (
                status IN (
                    'observed', 'discovery_unresolved', 'fetch_failed', 'validation_failed'
                )
            ),
            failure_reason TEXT,
            collector_version VARCHAR(64) NOT NULL CHECK (
                char_length(btrim(collector_version)) BETWEEN 1 AND 64
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_research_source_terms_known_source CHECK (
                (provider = 'cninfo'
                 AND source = 'cninfo_listed_company_disclosure'
                 AND source_scope = '{CNINFO_SOURCE_SCOPE}'
                 AND document_kind = 'other_official'
                 AND terms_url IN (
                    'https://www.cninfo.com.cn/new/index.htm',
                    'https://www.cninfo.com.cn/new/commonUrl?url=disclosure%2Flist%2Fnotice'
                 ))
                OR
                (provider = 'gdelt'
                 AND source = 'gdelt_article_list_rss'
                 AND source_scope = '{GDELT_SOURCE_SCOPE}'
                 AND (
                    (document_kind = 'terms_of_use'
                     AND terms_url = 'https://www.gdeltproject.org/about.html')
                    OR
                    (document_kind = 'other_official'
                     AND terms_url = 'https://blog.gdeltproject.org/announcing-the-gdelt-article-list-rss-feed/')
                 ))
            ),
            CONSTRAINT ck_research_source_terms_hash CHECK (
                raw_hash IS NULL OR raw_hash ~ '^[0-9a-f]{{64}}$'
            ),
            CONSTRAINT ck_research_source_terms_bytes CHECK (
                document_bytes IS NULL OR document_bytes >= 0
            ),
            CONSTRAINT ck_research_source_terms_effective_time CHECK (
                (source_time_precision = 'unresolved' AND source_effective_at IS NULL)
                OR
                (source_time_precision IN ('exact', 'date') AND source_effective_at IS NOT NULL)
            ),
            CONSTRAINT ck_research_source_terms_status_fields CHECK (
                (status = 'observed'
                 AND retrieved_at IS NOT NULL
                 AND raw_hash IS NOT NULL
                 AND document_bytes IS NOT NULL
                 AND content_type IS NOT NULL
                 AND char_length(btrim(content_type)) BETWEEN 1 AND 128
                 AND failure_reason IS NULL)
                OR
                (status <> 'observed'
                 AND retrieved_at IS NULL
                 AND raw_hash IS NULL
                 AND document_bytes IS NULL
                 AND content_type IS NULL
                 AND failure_reason IS NOT NULL
                 AND char_length(btrim(failure_reason)) BETWEEN 1 AND 2000)
            ),
            UNIQUE (provider, source, source_scope, terms_url, raw_hash)
        );
        CREATE INDEX idx_research_source_terms_lookup
        ON market.research_source_terms_evidence (
            provider, source, created_at DESC, terms_evidence_id DESC
        );

        CREATE TABLE market.research_source_usage_reviews (
            review_id UUID PRIMARY KEY,
            terms_evidence_id UUID NOT NULL
                REFERENCES market.research_source_terms_evidence(terms_evidence_id)
                ON DELETE RESTRICT,
            usage_scope VARCHAR(32) NOT NULL CHECK (
                usage_scope IN (
                    'manual_observation', 'automated_fetch', 'local_storage',
                    'derived_research', 'redistribution'
                )
            ),
            decision_status VARCHAR(32) NOT NULL CHECK (
                decision_status IN ('review_required', 'rejected')
            ),
            reason TEXT NOT NULL CHECK (
                char_length(btrim(reason)) BETWEEN 1 AND 2000
            ),
            reviewer_label VARCHAR(128) NOT NULL CHECK (
                char_length(btrim(reviewer_label)) BETWEEN 1 AND 128
            ),
            identity_assurance VARCHAR(32) NOT NULL DEFAULT 'unverified' CHECK (
                identity_assurance = 'unverified'
            ),
            policy_version VARCHAR(64) NOT NULL CHECK (
                char_length(btrim(policy_version)) BETWEEN 1 AND 64
            ),
            reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_research_source_usage_reviews_latest
        ON market.research_source_usage_reviews (
            terms_evidence_id, usage_scope, reviewed_at DESC, review_id DESC
        );

        CREATE FUNCTION market.reject_research_source_usage_evidence_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'research source terms evidence and usage reviews are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_research_source_terms_evidence_immutable
        BEFORE UPDATE OR DELETE ON market.research_source_terms_evidence
        FOR EACH ROW EXECUTE FUNCTION market.reject_research_source_usage_evidence_mutation();
        CREATE TRIGGER trg_research_source_usage_reviews_immutable
        BEFORE UPDATE OR DELETE ON market.research_source_usage_reviews
        FOR EACH ROW EXECUTE FUNCTION market.reject_research_source_usage_evidence_mutation();

        ALTER TABLE market.research_source_terms_evidence OWNER TO quant_admin;
        ALTER TABLE market.research_source_usage_reviews OWNER TO quant_admin;
        ALTER FUNCTION market.reject_research_source_usage_evidence_mutation() OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_research_source_usage_reviews_immutable
        ON market.research_source_usage_reviews;
        DROP TRIGGER IF EXISTS trg_research_source_terms_evidence_immutable
        ON market.research_source_terms_evidence;
        DROP TABLE IF EXISTS market.research_source_usage_reviews;
        DROP TABLE IF EXISTS market.research_source_terms_evidence;
        DROP FUNCTION IF EXISTS market.reject_research_source_usage_evidence_mutation();
        """
    )
