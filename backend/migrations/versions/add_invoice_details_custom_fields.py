"""Add service_name and unit_price to Invoice_Details

This migration adds user-entered custom fields to the Invoice_Details table.
Run this to fix the issue where service name and amount weren't being saved/displayed.

Revision ID: add_invoice_details_custom_fields
Revises: 
Create Date: 2026-03-28 07:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_invoice_details_custom_fields'
down_revision = '3561401439a9'
branch_labels = None
depends_on = None


def upgrade():
    # For SQLite compatibility - we need to handle the schema differently
    # The table is in StreemLyne_MT schema
    
    # Add service_name column to store user-entered custom service name
    # Using batch operations for SQLite compatibility
    op.add_column(
        'Invoice_Details',
        sa.Column('service_name', sa.String(length=500), nullable=True)
    )
    
    # Add unit_price column to store user-entered custom amount
    op.add_column(
        'Invoice_Details',
        sa.Column('unit_price', sa.Float(precision=24), nullable=True)
    )


def downgrade():
    # Remove unit_price column
    op.drop_column(
        'Invoice_Details',
        'unit_price'
    )
    
    # Remove service_name column
    op.drop_column(
        'Invoice_Details',
        'service_name'
    )
