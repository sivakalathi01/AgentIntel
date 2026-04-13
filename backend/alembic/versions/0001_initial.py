"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-04-07 22:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("budget_limit", sa.Float(), nullable=False),
        sa.Column("spent_budget", sa.Float(), nullable=False, server_default="0"),
        sa.Column("allowed_providers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_until", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("budget", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("proof", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_tasks_session_id", "tasks", ["session_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "session_challenges",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.String(length=64), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_session_challenges_wallet_address", "session_challenges", ["wallet_address"])
    op.create_index("ix_session_challenges_expires_at", "session_challenges", ["expires_at"])

    op.create_table(
        "task_challenges",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("budget", sa.Float(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.String(length=64), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_task_challenges_session_id", "task_challenges", ["session_id"])
    op.create_index("ix_task_challenges_wallet_address", "task_challenges", ["wallet_address"])
    op.create_index("ix_task_challenges_expires_at", "task_challenges", ["expires_at"])

    op.create_table(
        "security_counters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_security_counters_key", "security_counters", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_security_counters_key", table_name="security_counters")
    op.drop_table("security_counters")

    op.drop_index("ix_task_challenges_expires_at", table_name="task_challenges")
    op.drop_index("ix_task_challenges_wallet_address", table_name="task_challenges")
    op.drop_index("ix_task_challenges_session_id", table_name="task_challenges")
    op.drop_table("task_challenges")

    op.drop_index("ix_session_challenges_expires_at", table_name="session_challenges")
    op.drop_index("ix_session_challenges_wallet_address", table_name="session_challenges")
    op.drop_table("session_challenges")

    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_session_id", table_name="tasks")
    op.drop_table("tasks")

    op.drop_table("sessions")
