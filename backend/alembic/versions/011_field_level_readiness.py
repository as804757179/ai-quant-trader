"""Add field-level requirement profiles and scoped reviews.

Revision ID: 011
Revises: 010
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


OHLCV = """'["trading_date","open","high","low","close","volume","adjustment","trading_calendar","corporate_action_status"]'::jsonb"""
AMOUNT = """'["trading_date","open","high","low","close","volume","adjustment","trading_calendar","corporate_action_status","amount","amount_unit","amount_provider_validation"]'::jsonb"""
EXECUTION = """'["quote_time","price_applicability","explicit_authorization","execution_gate"]'::jsonb"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.research_requirement_profiles (
            requirement_profile VARCHAR(40) PRIMARY KEY,
            required_fields JSONB NOT NULL,
            allowed_scopes JSONB NOT NULL,
            policy_version VARCHAR(64) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        f"""
        INSERT INTO market.research_requirement_profiles
            (requirement_profile, required_fields, allowed_scopes, policy_version)
        VALUES
        ('OHLCV_RETURN_V1',{OHLCV},'["raw_price_analysis","return_backtest"]'::jsonb,'field-readiness-v1'),
        ('AMOUNT_FACTOR_V1',{AMOUNT},'["return_backtest"]'::jsonb,'field-readiness-v1'),
        ('EXECUTION_REFERENCE_V1',{EXECUTION},'["execution_reference"]'::jsonb,'field-readiness-v1')
        """
    )
    op.execute(
        """
        ALTER TABLE market.research_readiness_reviews
          ADD COLUMN requirement_profile VARCHAR(40),
          ADD COLUMN required_fields JSONB,
          ADD COLUMN validated_fields JSONB,
          ADD COLUMN unresolved_fields JSONB,
          ADD COLUMN rejected_fields JSONB,
          ADD COLUMN policy_version VARCHAR(64)
        """
    )
    op.execute(
        f"""
        UPDATE market.research_readiness_reviews
        SET requirement_profile = CASE WHEN research_use_scope='execution_reference'
                                       THEN 'EXECUTION_REFERENCE_V1' ELSE 'OHLCV_RETURN_V1' END,
            required_fields = CASE WHEN research_use_scope='execution_reference'
                                   THEN {EXECUTION} ELSE {OHLCV} END,
            validated_fields = CASE WHEN research_use_scope='execution_reference'
                                    THEN '["execution_gate"]'::jsonb ELSE {OHLCV} END,
            unresolved_fields = CASE WHEN research_use_scope='execution_reference'
                                     THEN '[]'::jsonb ELSE '["amount"]'::jsonb END,
            rejected_fields = CASE WHEN research_use_scope='execution_reference'
                                   THEN '["quote_time","price_applicability","explicit_authorization"]'::jsonb
                                   WHEN stock_code='300502.SZ' AND research_use_scope='return_backtest'
                                   THEN '["corporate_action_status"]'::jsonb ELSE '[]'::jsonb END,
            policy_version = 'field-readiness-v1',
            readiness_status = CASE
              WHEN research_use_scope='execution_reference' THEN 'rejected'
              WHEN stock_code='300502.SZ' AND research_use_scope='return_backtest' THEN 'rejected'
              ELSE 'ready' END,
            provider_validation_status = CASE WHEN research_use_scope='execution_reference'
                                              THEN 'rejected' ELSE 'pass' END,
            review_reason = CASE
              WHEN research_use_scope='execution_reference'
                THEN 'EXECUTION_REFERENCE_V1 lacks freshness, price applicability and explicit authorization.'
              WHEN stock_code='300502.SZ' AND research_use_scope='return_backtest'
                THEN 'OHLCV is validated, but the in-range dividend and capital increase are not handled for returns.'
              ELSE 'All OHLCV_RETURN_V1 required fields are validated; unresolved amount is non-required for this profile.' END
        """
    )
    op.execute(
        """
        ALTER TABLE market.research_readiness_reviews
          ALTER COLUMN requirement_profile SET NOT NULL,
          ALTER COLUMN required_fields SET NOT NULL,
          ALTER COLUMN validated_fields SET NOT NULL,
          ALTER COLUMN unresolved_fields SET NOT NULL,
          ALTER COLUMN rejected_fields SET NOT NULL,
          ALTER COLUMN policy_version SET NOT NULL,
          ADD CONSTRAINT fk_readiness_requirement_profile
            FOREIGN KEY (requirement_profile)
            REFERENCES market.research_requirement_profiles(requirement_profile)
        """
    )
    op.execute(
        """
        ALTER TABLE market.research_readiness_reviews
          DROP CONSTRAINT research_readiness_reviews_stock_code_period_date_from_date_key,
          ADD CONSTRAINT uq_research_readiness_profile
            UNIQUE (stock_code, period, date_from, date_to, adjustment,
                    research_use_scope, requirement_profile)
        """
    )
    op.execute(
        f"""
        INSERT INTO market.research_readiness_reviews
            (review_id, stock_code, period, date_from, date_to, adjustment,
             readiness_status, research_use_scope, corporate_action_status,
             missingness_status, provider_validation_status, review_reason,
             evidence, reviewer_version, reviewed_at, requirement_profile,
             required_fields, validated_fields, unresolved_fields, rejected_fields,
             policy_version)
        SELECT 's09-' || replace(stock_code,'.','') || '-amount', stock_code,
               '1d', DATE '2026-06-01', DATE '2026-06-30', 'raw',
               CASE WHEN stock_code='300502.SZ' THEN 'rejected' ELSE 'review_required' END,
               'return_backtest',
               CASE WHEN stock_code='300502.SZ' THEN 'event_verified_handling_required'
                    ELSE 'verified_no_event' END,
               'complete', 'partial_pass',
               CASE WHEN stock_code='300502.SZ'
                    THEN 'AMOUNT_FACTOR_V1 is blocked by unresolved amount validation and an unhandled corporate action.'
                    ELSE 'AMOUNT_FACTOR_V1 requires independently validated amount; 2026-06-30 remains unresolved.' END,
               jsonb_build_object('amount_20260630','unresolved','ohlcv','validated'),
               'sprint09-field-readiness-v1', NOW(), 'AMOUNT_FACTOR_V1',
               {AMOUNT}, {OHLCV} || '["amount_unit"]'::jsonb,
               '["amount","amount_provider_validation"]'::jsonb,
               CASE WHEN stock_code='300502.SZ' THEN '["corporate_action_status"]'::jsonb ELSE '[]'::jsonb END,
               'field-readiness-v1'
        FROM (VALUES ('300308.SZ'),('603986.SH'),('300502.SZ')) s(stock_code)
        """
    )
    op.execute(
        """
        UPDATE market.research_readiness_reviews
        SET evidence = evidence || jsonb_build_object(
          'field_level_review',true,
          'amount_is_required',requirement_profile='AMOUNT_FACTOR_V1',
          'store_row_global_ready',false,
          'price_jump_review',CASE
            WHEN stock_code='300308.SZ' THEN 'max_close_jump_8.3551pct_explained_as_normal_market_move'
            WHEN stock_code='603986.SH' THEN 'max_close_jump_10.0008pct_within_board_limit'
            ELSE '2026-06-11_jump_explained_by_verified_corporate_action' END
        )
        """
    )
    op.execute("ALTER TABLE market.research_requirement_profiles OWNER TO quant_admin")


def downgrade() -> None:
    op.execute("DELETE FROM market.research_readiness_reviews WHERE reviewer_version='sprint09-field-readiness-v1'")
    op.execute(
        """
        ALTER TABLE market.research_readiness_reviews
          DROP CONSTRAINT uq_research_readiness_profile,
          ADD CONSTRAINT research_readiness_reviews_stock_code_period_date_from_date_key
            UNIQUE (stock_code, period, date_from, date_to, adjustment, research_use_scope),
          DROP CONSTRAINT fk_readiness_requirement_profile,
          DROP COLUMN requirement_profile,
          DROP COLUMN required_fields,
          DROP COLUMN validated_fields,
          DROP COLUMN unresolved_fields,
          DROP COLUMN rejected_fields,
          DROP COLUMN policy_version
        """
    )
    op.execute("DROP TABLE market.research_requirement_profiles")
