"""kite pass entitlements

Revision ID: 0003_kite_pass_entitlements
Revises: 0002_x402_payments
Create Date: 2026-04-08 23:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_kite_pass_entitlements"
down_revision = "0002_x402_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kite_pass_entitlements",
        sa.Column("wallet_address", sa.String(length=64), primary_key=True),
        sa.Column("has_pass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("checked_at", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_kite_pass_entitlements_expires_at", "kite_pass_entitlements", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_kite_pass_entitlements_expires_at", table_name="kite_pass_entitlements")
    op.drop_table("kite_pass_entitlements")
