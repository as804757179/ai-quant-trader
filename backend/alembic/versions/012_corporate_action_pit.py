"""Add immutable point-in-time corporate actions.

Revision ID: 012
Revises: 011
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


GROSS_FIELDS = """'["trading_date","open","high","low","close","volume","adjustment","trading_calendar","corporate_action_status","verified_corporate_action_event","record_date","ex_date","cash_payment_date","share_credit_date","corporate_action_processor_version","gross_total_return_policy"]'::jsonb"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market.corporate_actions (
            action_id VARCHAR(80) PRIMARY KEY,
            stock_code VARCHAR(16) NOT NULL,
            event_type VARCHAR(48) NOT NULL,
            announcement_date DATE NOT NULL,
            record_date DATE NOT NULL,
            ex_date DATE NOT NULL,
            cash_payment_date DATE NOT NULL,
            share_credit_date DATE NOT NULL,
            cash_dividend_per_10 NUMERIC(20,8) NOT NULL,
            share_increase_per_10 NUMERIC(20,8) NOT NULL,
            source_name VARCHAR(80) NOT NULL,
            source_reference TEXT NOT NULL,
            evidence_hash CHAR(64) NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            event_version VARCHAR(64) NOT NULL,
            verification_status VARCHAR(24) NOT NULL,
            supersedes_action_id VARCHAR(80),
            CONSTRAINT uq_corporate_action_version UNIQUE(stock_code, event_version),
            CONSTRAINT ck_corporate_action_source CHECK(source_name <> 'unknown'),
            CONSTRAINT ck_corporate_action_verified CHECK(verification_status IN ('verified','rejected')),
            CONSTRAINT fk_corporate_action_supersedes FOREIGN KEY(supersedes_action_id)
                REFERENCES market.corporate_actions(action_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_corporate_actions_pit ON market.corporate_actions(stock_code, announcement_date)")
    op.execute(
        """
        CREATE FUNCTION market.reject_corporate_action_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'corporate action events are immutable; create a new event_version';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_corporate_actions_immutable
        BEFORE UPDATE OR DELETE ON market.corporate_actions
        FOR EACH ROW EXECUTE FUNCTION market.reject_corporate_action_mutation()
        """
    )
    op.execute(
        """
        INSERT INTO market.corporate_actions (
            action_id, stock_code, event_type, announcement_date, record_date, ex_date,
            cash_payment_date, share_credit_date, cash_dividend_per_10,
            share_increase_per_10, source_name, source_reference, evidence_hash,
            captured_at, event_version, verification_status
        ) VALUES (
            'cninfo-1225351859-v1', '300502.SZ', 'cash_dividend_and_capital_increase',
            DATE '2026-06-04', DATE '2026-06-10', DATE '2026-06-11',
            DATE '2026-06-11', DATE '2026-06-11', 10, 4,
            'cninfo', 'https://static.cninfo.com.cn/finalpage/2026-06-04/1225351859.PDF',
            'bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d',
            TIMESTAMPTZ '2026-07-12 00:00:00+08', 'cninfo-1225351859-v1', 'verified'
        )
        """
    )
    op.execute(
        f"""
        INSERT INTO market.research_requirement_profiles
            (requirement_profile, required_fields, allowed_scopes, policy_version)
        VALUES ('OHLCV_TOTAL_RETURN_GROSS_V1', {GROSS_FIELDS},
                '["return_backtest"]'::jsonb, 'corporate-action-pit-v1')
        """
    )
    op.execute(
        f"""
        INSERT INTO market.research_readiness_reviews (
            review_id, stock_code, period, date_from, date_to, adjustment,
            readiness_status, research_use_scope, corporate_action_status,
            missingness_status, provider_validation_status, review_reason, evidence,
            reviewer_version, reviewed_at, requirement_profile, required_fields,
            validated_fields, unresolved_fields, rejected_fields, policy_version
        ) VALUES (
            's12-300502-gross-total-return', '300502.SZ', '1d', DATE '2026-06-01',
            DATE '2026-06-30', 'raw', 'ready', 'return_backtest',
            'event_verified_handled', 'complete', 'pass',
            'Official event dates and ratios are verified; gross pre-tax total-return accounting passed PIT validation.',
            jsonb_build_object('action_id','cninfo-1225351859-v1',
              'evidence_hash','bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d',
              'gross_policy','GROSS_PRETAX_TOTAL_RETURN_V1','net_tax_policy','blocked'),
            'sprint12-corporate-action-pit-v1', NOW(), 'OHLCV_TOTAL_RETURN_GROSS_V1',
            {GROSS_FIELDS}, {GROSS_FIELDS}, '[]'::jsonb, '[]'::jsonb,
            'corporate-action-pit-v1'
        )
        """
    )
    op.execute("ALTER TABLE market.corporate_actions OWNER TO quant_admin")


def downgrade() -> None:
    op.execute("DELETE FROM market.research_readiness_reviews WHERE review_id='s12-300502-gross-total-return'")
    op.execute("DELETE FROM market.research_requirement_profiles WHERE requirement_profile='OHLCV_TOTAL_RETURN_GROSS_V1'")
    op.execute("DROP TRIGGER trg_corporate_actions_immutable ON market.corporate_actions")
    op.execute("DROP FUNCTION market.reject_corporate_action_mutation()")
    op.execute("DROP TABLE market.corporate_actions")
