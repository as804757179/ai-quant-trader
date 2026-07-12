"""orders idempotency unique per mode

Revision ID: 002
Revises: 001
Create Date: 2026-07-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 去掉全局 UNIQUE(idempotency_key)，改为 (mode, idempotency_key)
    op.execute(
        """
        ALTER TABLE trade.orders
        DROP CONSTRAINT IF EXISTS orders_idempotency_key_key
        """
    )
    # 兼容可能的约束名
    op.execute(
        """
        DO $$
        DECLARE
            cname text;
        BEGIN
            SELECT conname INTO cname
            FROM pg_constraint
            WHERE conrelid = 'trade.orders'::regclass
              AND contype = 'u'
              AND pg_get_constraintdef(oid) ILIKE '%idempotency_key%'
              AND pg_get_constraintdef(oid) NOT ILIKE '%mode%';
            IF cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE trade.orders DROP CONSTRAINT %I', cname);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_mode_idempotency
        ON trade.orders (mode, idempotency_key)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS trade.uq_orders_mode_idempotency")
    op.execute(
        """
        ALTER TABLE trade.orders
        ADD CONSTRAINT orders_idempotency_key_key UNIQUE (idempotency_key)
        """
    )
