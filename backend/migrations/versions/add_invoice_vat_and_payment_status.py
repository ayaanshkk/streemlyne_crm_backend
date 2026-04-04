"""Add vat, other_taxes, payment_status to Invoice_Master

Revision ID: add_invoice_vat_and_payment_status
Revises: add_invoice_details_custom_fields
Create Date: 2026-04-01

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_invoice_vat_and_payment_status'
down_revision = 'add_invoice_details_custom_fields'
branch_labels = None
depends_on = None


def upgrade():
    # Add vat column to store VAT amount
    op.add_column(
        'Invoice_Master',
        sa.Column('vat', sa.NUMERIC(precision=12, scale=2), nullable=True)
    )
    
    # Add other_taxes column to store other tax amounts
    op.add_column(
        'Invoice_Master',
        sa.Column('other_taxes', sa.NUMERIC(precision=12, scale=2), nullable=True)
    )
    
    # Add payment_status column to track payment status
    op.add_column(
        'Invoice_Master',
        sa.Column('payment_status', sa.String(length=50), nullable=True, server_default='Not Paid')
    )


def downgrade():
    # Remove payment_status column
    op.drop_column(
        'Invoice_Master',
        'payment_status'
    )
    
    # Remove other_taxes column
    op.drop_column(
        'Invoice_Master',
        'other_taxes'
    )
    
    # Remove vat column
    op.drop_column(
        'Invoice_Master',
        'vat'
    )