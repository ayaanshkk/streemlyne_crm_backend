"""Add subscription plan user limits

Revision ID: 20260809_subscription_user_limits
Revises: 20260427_processed_webhook_events
Create Date: 2026-08-09
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260809_subscription_user_limits"
down_revision = "20260427_processed_webhook_events"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE "StreemLyne_MT"."Subscription_Plans"
        ADD COLUMN IF NOT EXISTS max_users integer
        """
    )
    op.execute(
        """
        UPDATE "StreemLyne_MT"."Subscription_Plans"
        SET price = 49.00, max_users = 250
        WHERE subscription_code = 'STARTER'
        """
    )
    op.execute(
        """
        UPDATE "StreemLyne_MT"."Subscription_Plans"
        SET price = 99.00, max_users = NULL
        WHERE subscription_code = 'PRO'
        """
    )
    op.execute(
        """
        UPDATE "StreemLyne_MT"."Subscription_Plans"
        SET max_users = NULL
        WHERE subscription_code = 'CUSTOM'
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE "StreemLyne_MT"."Subscription_Plans"
        DROP COLUMN IF EXISTS max_users
        """
    )
