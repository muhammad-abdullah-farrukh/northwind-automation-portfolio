"""async jobs: job files, callback delivery log, human reviews

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("callback_url", sa.Text))
    op.add_column("jobs", sa.Column("attempts", sa.Integer, nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("last_error", sa.Text))
    op.add_column("jobs", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_jobs_api_key_status", "jobs", ["api_key_id", "status"])

    op.create_table(
        "job_files",
        sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("status_code", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "job_reviews",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("data", postgresql.JSONB, nullable=False),
        sa.Column("validation", postgresql.JSONB, nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("job_reviews")
    op.drop_table("webhook_deliveries")
    op.drop_table("job_files")
    op.drop_index("ix_jobs_api_key_status", table_name="jobs")
    for col in ("completed_at", "last_error", "attempts", "callback_url"):
        op.drop_column("jobs", col)
