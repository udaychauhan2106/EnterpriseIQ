"""associate investigations with synthetic scenarios

Revision ID: 8d4a39ac72b1
Revises: 4936eb60c0ac
Create Date: 2026-11-18 07:27:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d4a39ac72b1"
down_revision: Union[str, Sequence[str], None] = "4936eb60c0ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("simulation_scenario_id", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("investigations", "simulation_scenario_id")
