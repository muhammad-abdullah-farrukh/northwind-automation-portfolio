"""idempotency_records.response_body: jsonb -> json

jsonb reorders object keys, so replays came back with a different field order than the
original response. json keeps the text as written, so replays are byte-identical.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE idempotency_records ALTER COLUMN response_body TYPE json USING response_body::text::json")


def downgrade() -> None:
    op.execute("ALTER TABLE idempotency_records ALTER COLUMN response_body TYPE jsonb USING response_body::jsonb")
