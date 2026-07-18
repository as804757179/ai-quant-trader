"""Scope order intent idempotency to its expiration window."""

from alembic import op


revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE trade.order_intents
            ADD COLUMN intent_generation INTEGER NOT NULL DEFAULT 1
                CHECK (intent_generation >= 1);
        ALTER TABLE trade.order_intents
            DROP CONSTRAINT order_intents_principal_id_client_intent_key_key;
        ALTER TABLE trade.order_intents
            ADD CONSTRAINT uq_order_intents_principal_client_generation
                UNIQUE (principal_id, client_intent_key, intent_generation);
        """
    )


def downgrade() -> None:
    raise RuntimeError("030 preserves expired order intent audit records and must not be downgraded")
