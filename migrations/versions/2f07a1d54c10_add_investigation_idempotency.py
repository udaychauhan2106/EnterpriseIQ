"""add organization-scoped investigation idempotency

Revision ID: 2f07a1d54c10
Revises: 8d4a39ac72b1
Create Date: 2026-11-18 08:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2f07a1d54c10"
down_revision: Union[str, Sequence[str], None] = "8d4a39ac72b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_investigations_org_idempotency_key",
        "investigations",
        ["organization_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_investigations_org_idempotency_key", table_name="investigations"
    )
    op.drop_column("investigations", "request_fingerprint")
    op.drop_column("investigations", "idempotency_key")
