"""Add observed GDELT RSS news-evidence details.

Revision ID: 020
Revises: 019
"""

from alembic import op


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.research_news_details (
            evidence_id UUID PRIMARY KEY
                REFERENCES market.research_evidence(evidence_id) ON DELETE RESTRICT,
            provider_feed_url TEXT NOT NULL
                CHECK (provider_feed_url = 'https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss'),
            source_title_raw TEXT NOT NULL,
            publisher_domain TEXT NOT NULL,
            provider_reported_at TIMESTAMPTZ NOT NULL,
            provider_time_semantics VARCHAR(32) NOT NULL
                CHECK (provider_time_semantics = 'publication_or_first_seen'),
            association_method VARCHAR(32) NOT NULL
                CHECK (association_method = 'title_alias_match'),
            association_alias TEXT NOT NULL,
            association_status VARCHAR(32) NOT NULL
                CHECK (association_status = 'review_required'),
            content_scope VARCHAR(32) NOT NULL
                CHECK (content_scope = 'title_link_only'),
            feed_window_minutes SMALLINT NOT NULL CHECK (feed_window_minutes = 15),
            raw_representation VARCHAR(64) NOT NULL
                CHECK (raw_representation = 'rss_item_xml_reserialized'),
            detail_parse_status VARCHAR(32) NOT NULL
                CHECK (detail_parse_status = 'metadata_observed'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE market.research_news_details OWNER TO quant_admin;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.research_news_details;")
