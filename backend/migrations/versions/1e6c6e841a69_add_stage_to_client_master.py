"""add_stage_to_client_master

Revision ID: xxxxx
Revises: xxxxx
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'xxxxx'
down_revision = 'xxxxx'
branch_labels = None
depends_on = None


def upgrade():
    # Add stage column to Client_Master
    op.add_column(
        'Client_Master',
        sa.Column('stage', sa.String(50), nullable=True),
        schema='StreemLyne_MT'
    )


def downgrade():
    # Remove stage column
    op.drop_column('Client_Master', 'stage', schema='StreemLyne_MT')