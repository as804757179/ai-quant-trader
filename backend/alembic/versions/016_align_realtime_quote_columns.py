"""Align legacy realtime quote columns with the observed quote contract.

Revision ID: 016
Revises: 015
"""

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column, column_type in (
        ("open", "NUMERIC(12,4)"),
        ("high", "NUMERIC(12,4)"),
        ("low", "NUMERIC(12,4)"),
        ("change", "NUMERIC(12,4)"),
        ("bid1_price", "NUMERIC(12,4)"),
        ("bid1_vol", "BIGINT"),
        ("bid2_price", "NUMERIC(12,4)"),
        ("bid2_vol", "BIGINT"),
        ("bid3_price", "NUMERIC(12,4)"),
        ("bid3_vol", "BIGINT"),
        ("ask1_price", "NUMERIC(12,4)"),
        ("ask1_vol", "BIGINT"),
        ("ask2_price", "NUMERIC(12,4)"),
        ("ask2_vol", "BIGINT"),
        ("ask3_price", "NUMERIC(12,4)"),
        ("ask3_vol", "BIGINT"),
    ):
        op.execute(
            f"ALTER TABLE market.quotes ADD COLUMN IF NOT EXISTS {column} {column_type}"
        )
    op.execute("ALTER TABLE market.quotes OWNER TO quant_admin")


def downgrade() -> None:
    # Retain columns to avoid dropping observed quote data during rollback.
    pass
