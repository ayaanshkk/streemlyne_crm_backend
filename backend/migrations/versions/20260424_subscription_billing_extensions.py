"""Add subscription billing extension tables and columns

Revision ID: 20260424_subscription_billing
Revises: add_invoice_vat_and_payment_status
Create Date: 2026-04-24
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260424_subscription_billing"
down_revision = "add_invoice_vat_and_payment_status"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE "StreemLyne_MT"."Tenant_Subscription"
        ADD COLUMN IF NOT EXISTS payment_attempts integer DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE "StreemLyne_MT"."Tenant_Subscription"
        ADD COLUMN IF NOT EXISTS next_retry_date timestamp with time zone
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Subscription_Invoice" (
            invoice_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL,
            tenant_id character varying NOT NULL,
            subscription_id smallint,
            stripe_invoice_id character varying UNIQUE,
            invoice_number character varying NOT NULL UNIQUE,
            amount numeric NOT NULL,
            tax_amount numeric DEFAULT 0,
            total_amount numeric NOT NULL,
            currency_id smallint NOT NULL,
            status character varying DEFAULT 'pending',
            period_start date,
            period_end date,
            invoice_pdf_url text,
            due_date date,
            paid_at timestamp with time zone,
            created_at timestamp with time zone DEFAULT now(),
            updated_at timestamp with time zone,
            PRIMARY KEY (invoice_id),
            CONSTRAINT subscription_invoice_tenant_fkey
                FOREIGN KEY (tenant_id)
                REFERENCES "StreemLyne_MT"."Tenant_Master"(tenant_id),
            CONSTRAINT subscription_invoice_subscription_fkey
                FOREIGN KEY (subscription_id)
                REFERENCES "StreemLyne_MT"."Tenant_Subscription"(tenant_subscription_mapping_id),
            CONSTRAINT subscription_invoice_currency_fkey
                FOREIGN KEY (currency_id)
                REFERENCES "StreemLyne_MT"."Currency_Master"(currency_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Payment_Attempt" (
            payment_attempt_id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
            tenant_id character varying NOT NULL,
            subscription_id smallint NOT NULL,
            stripe_payment_intent_id character varying,
            invoice_id smallint,
            attempt_number integer NOT NULL,
            amount numeric NOT NULL,
            currency_id smallint NOT NULL,
            status character varying NOT NULL,
            failure_reason text,
            failure_code character varying,
            created_at timestamp with time zone DEFAULT now(),
            PRIMARY KEY (payment_attempt_id),
            CONSTRAINT payment_attempt_tenant_fkey
                FOREIGN KEY (tenant_id)
                REFERENCES "StreemLyne_MT"."Tenant_Master"(tenant_id),
            CONSTRAINT payment_attempt_subscription_fkey
                FOREIGN KEY (subscription_id)
                REFERENCES "StreemLyne_MT"."Tenant_Subscription"(tenant_subscription_mapping_id),
            CONSTRAINT payment_attempt_invoice_fkey
                FOREIGN KEY (invoice_id)
                REFERENCES "StreemLyne_MT"."Subscription_Invoice"(invoice_id),
            CONSTRAINT payment_attempt_currency_fkey
                FOREIGN KEY (currency_id)
                REFERENCES "StreemLyne_MT"."Currency_Master"(currency_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Dunning_Config" (
            config_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL,
            plan_id smallint,
            retry_schedule jsonb NOT NULL DEFAULT '[3, 7]'::jsonb,
            max_retries integer DEFAULT 3,
            grace_period_days integer DEFAULT 0,
            is_active boolean DEFAULT true,
            created_at timestamp with time zone DEFAULT now(),
            updated_at timestamp with time zone,
            PRIMARY KEY (config_id),
            CONSTRAINT dunning_config_plan_fkey
                FOREIGN KEY (plan_id)
                REFERENCES "StreemLyne_MT"."Subscription_Plans"(subscription_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Notification_Preference" (
            preference_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL,
            tenant_id character varying NOT NULL,
            notification_type character varying NOT NULL,
            email_enabled boolean DEFAULT true,
            in_app_enabled boolean DEFAULT true,
            sms_enabled boolean DEFAULT false,
            created_at timestamp with time zone DEFAULT now(),
            PRIMARY KEY (preference_id),
            CONSTRAINT uq_notification_pref_tenant_type UNIQUE (tenant_id, notification_type),
            CONSTRAINT notification_preference_tenant_fkey
                FOREIGN KEY (tenant_id)
                REFERENCES "StreemLyne_MT"."Tenant_Master"(tenant_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Notification_Log" (
            notification_id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
            tenant_id character varying NOT NULL,
            notification_type character varying NOT NULL,
            channel character varying NOT NULL,
            recipient character varying,
            subject text,
            body text,
            status character varying DEFAULT 'pending',
            sent_at timestamp with time zone,
            created_at timestamp with time zone DEFAULT now(),
            PRIMARY KEY (notification_id),
            CONSTRAINT notification_log_tenant_fkey
                FOREIGN KEY (tenant_id)
                REFERENCES "StreemLyne_MT"."Tenant_Master"(tenant_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Subscription_Pause" (
            pause_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL,
            tenant_subscription_mapping_id smallint NOT NULL,
            paused_at timestamp with time zone NOT NULL,
            resume_at timestamp with time zone,
            pause_reason character varying,
            is_active boolean DEFAULT true,
            PRIMARY KEY (pause_id),
            CONSTRAINT subscription_pause_subscription_fkey
                FOREIGN KEY (tenant_subscription_mapping_id)
                REFERENCES "StreemLyne_MT"."Tenant_Subscription"(tenant_subscription_mapping_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Pending_Plan_Change" (
            change_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL,
            tenant_id character varying NOT NULL UNIQUE,
            current_plan_id smallint,
            new_plan_id smallint NOT NULL,
            scheduled_for date NOT NULL,
            created_at timestamp with time zone DEFAULT now(),
            updated_at timestamp with time zone,
            PRIMARY KEY (change_id),
            CONSTRAINT pending_plan_change_tenant_fkey
                FOREIGN KEY (tenant_id)
                REFERENCES "StreemLyne_MT"."Tenant_Master"(tenant_id),
            CONSTRAINT pending_plan_change_current_plan_fkey
                FOREIGN KEY (current_plan_id)
                REFERENCES "StreemLyne_MT"."Subscription_Plans"(subscription_id),
            CONSTRAINT pending_plan_change_new_plan_fkey
                FOREIGN KEY (new_plan_id)
                REFERENCES "StreemLyne_MT"."Subscription_Plans"(subscription_id)
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenant_subscription_status
        ON "StreemLyne_MT"."Tenant_Subscription"(tenant_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenant_subscription_trial_end
        ON "StreemLyne_MT"."Tenant_Subscription"(tenant_id, trial_end_date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_invoice_tenant
        ON "StreemLyne_MT"."Subscription_Invoice"(tenant_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_payment_attempt_tenant
        ON "StreemLyne_MT"."Payment_Attempt"(tenant_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notification_log_tenant
        ON "StreemLyne_MT"."Notification_Log"(tenant_id, created_at)
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS "StreemLyne_MT".idx_notification_log_tenant')
    op.execute('DROP INDEX IF EXISTS "StreemLyne_MT".idx_payment_attempt_tenant')
    op.execute('DROP INDEX IF EXISTS "StreemLyne_MT".idx_invoice_tenant')
    op.execute('DROP INDEX IF EXISTS "StreemLyne_MT".idx_tenant_subscription_trial_end')
    op.execute('DROP INDEX IF EXISTS "StreemLyne_MT".idx_tenant_subscription_status')

    op.execute('DROP TABLE IF EXISTS "StreemLyne_MT"."Pending_Plan_Change"')
    op.execute('DROP TABLE IF EXISTS "StreemLyne_MT"."Subscription_Pause"')
    op.execute('DROP TABLE IF EXISTS "StreemLyne_MT"."Notification_Log"')
    op.execute('DROP TABLE IF EXISTS "StreemLyne_MT"."Notification_Preference"')
    op.execute('DROP TABLE IF EXISTS "StreemLyne_MT"."Dunning_Config"')
    op.execute('DROP TABLE IF EXISTS "StreemLyne_MT"."Payment_Attempt"')
    op.execute('DROP TABLE IF EXISTS "StreemLyne_MT"."Subscription_Invoice"')

    op.execute(
        """
        ALTER TABLE "StreemLyne_MT"."Tenant_Subscription"
        DROP COLUMN IF EXISTS next_retry_date
        """
    )
    op.execute(
        """
        ALTER TABLE "StreemLyne_MT"."Tenant_Subscription"
        DROP COLUMN IF EXISTS payment_attempts
        """
    )
