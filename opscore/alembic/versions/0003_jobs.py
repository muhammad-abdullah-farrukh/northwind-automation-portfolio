"""jobs: one row per document through the extraction pipeline (sync now, async in P4)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("api_key_id", sa.Integer, sa.ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("schema_name", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255)),
        sa.Column("pages", sa.Integer),
        sa.Column("data", postgresql.JSONB),
        sa.Column("confidence", postgresql.JSONB),
        sa.Column("validation", postgresql.JSONB),
        sa.Column("meta", postgresql.JSONB),
        sa.Column("dedupe_hash", sa.String(64)),
        sa.Column("duplicate_of", sa.String(40), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_file_sha256", "jobs", ["file_sha256"])
    op.create_index("ix_jobs_dedupe_hash", "jobs", ["dedupe_hash"])


def downgrade() -> None:
    op.drop_table("jobs")
