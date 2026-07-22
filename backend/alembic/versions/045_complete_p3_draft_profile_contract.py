"""Complete P3 draft profile contract without approval.

Revision ID: 045
Revises: 044
"""

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE market.research_requirement_profiles
        SET contract = '{"purpose":"p3_shadow_replay","status":"draft","raw_only":true,"required_fields":["trading_date","open","high","low","close","volume","amount","adjustment","trading_calendar","corporate_action_status","available_at","dataset_hash","batch_hash","row_hash","input_snapshot_hash"],"optional_fields":["turnover_rate","provider_time","fetched_at","received_at","evidence_ref"],"forbidden_fields":["qfq","hfq","estimated_available_at","realtime"],"pit":"available_at <= information_cutoff","trading_calendar":"confirmed","corporate_action":"verified","hashes":["dataset_hash","batch_hash","row_hash","input_snapshot_hash"],"fail_closed":["P3_INPUT_LINEAGE_UNVERIFIED","P3_INPUT_AVAILABLE_AT_MISSING","P3_INPUT_HASH_MISSING","P3_INPUT_CALENDAR_UNVERIFIED","P3_INPUT_CORPORATE_ACTION_UNVERIFIED"]}'::jsonb
        WHERE requirement_profile = 'P3_REPLAY_DUAL_MA_RAW_OHLCV_V1'
          AND status = 'draft' AND enabled = FALSE;
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE market.research_requirement_profiles
        SET contract = '{"raw_only":true,"pit":"available_at <= information_cutoff","fail_closed":true,"forbidden_fields":["qfq","hfq","estimated_available_at"]}'::jsonb
        WHERE requirement_profile = 'P3_REPLAY_DUAL_MA_RAW_OHLCV_V1';
    """)
