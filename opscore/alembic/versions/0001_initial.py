"""initial: api_keys, idempotency_records, domain_cache (+ pgvector extension for later phases)

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("rate_limit_per_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("api_key_id", sa.Integer, sa.ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("idem_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="in_progress"),
        sa.Column("status_code", sa.Integer),
        sa.Column("response_body", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("api_key_id", "endpoint", "idem_key", name="uq_idem_scope"),
    )

    op.create_table(
        "domain_cache",
        sa.Column("domain", sa.String(253), primary_key=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("domain_cache")
    op.drop_table("idempotency_records")
    op.drop_table("api_keys")
