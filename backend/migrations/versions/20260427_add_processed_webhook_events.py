"""Add processed webhook event table

Revision ID: 20260427_processed_webhook_events
Revises: 20260424_subscription_billing
Create Date: 2026-04-27
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260427_processed_webhook_events"
down_revision = "20260424_subscription_billing"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Processed_Webhook_Event" (
            id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
            stripe_event_id character varying NOT NULL UNIQUE,
            event_type character varying NOT NULL,
            processed_at timestamp with time zone NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_processed_webhook_stripe_id
        ON "StreemLyne_MT"."Processed_Webhook_Event"(stripe_event_id)
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS "StreemLyne_MT".idx_processed_webhook_stripe_id')
    op.execute('DROP TABLE IF EXISTS "StreemLyne_MT"."Processed_Webhook_Event"')
