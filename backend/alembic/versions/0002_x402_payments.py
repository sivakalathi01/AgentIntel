"""x402 payment schema

Revision ID: 0002_x402_payments
Revises: 0001_initial
Create Date: 2026-04-08 23:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_x402_payments"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_intents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("wallet_address", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="x402"),
        sa.Column("provider_intent_id", sa.String(length=128), nullable=True),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
        sa.Column("confirmed_at", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_payment_intents_session_id", "payment_intents", ["session_id"])
    op.create_index("ix_payment_intents_task_id", "payment_intents", ["task_id"])
    op.create_index("ix_payment_intents_wallet_address", "payment_intents", ["wallet_address"])
    op.create_index("ix_payment_intents_provider_intent_id", "payment_intents", ["provider_intent_id"], unique=True)
    op.create_index("ix_payment_intents_status", "payment_intents", ["status"])

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("payment_intent_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_payment_events_payment_intent_id", "payment_events", ["payment_intent_id"])
    op.create_index("ix_payment_events_provider_event_id", "payment_events", ["provider_event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_payment_events_provider_event_id", table_name="payment_events")
    op.drop_index("ix_payment_events_payment_intent_id", table_name="payment_events")
    op.drop_table("payment_events")

    op.drop_index("ix_payment_intents_status", table_name="payment_intents")
    op.drop_index("ix_payment_intents_provider_intent_id", table_name="payment_intents")
    op.drop_index("ix_payment_intents_wallet_address", table_name="payment_intents")
    op.drop_index("ix_payment_intents_task_id", table_name="payment_intents")
    op.drop_index("ix_payment_intents_session_id", table_name="payment_intents")
    op.drop_table("payment_intents")
