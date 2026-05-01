-- Manual Supabase migration handoff for subscription module runtime fixes.
-- Copy and run these statements in the Supabase SQL Editor.
-- Do not execute backend/New db schema.sql; it is reference-only.

CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Processed_Webhook_Event" (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  stripe_event_id character varying NOT NULL UNIQUE,
  event_type character varying,
  processed_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT Processed_Webhook_Event_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_processed_webhook_stripe_id
ON "StreemLyne_MT"."Processed_Webhook_Event"(stripe_event_id);

CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Subscription_Invoice" (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  invoice_id integer GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  tenant_id character varying NOT NULL,
  subscription_id smallint,
  stripe_invoice_id character varying NOT NULL UNIQUE,
  stripe_subscription_id character varying,
  invoice_number character varying NOT NULL UNIQUE,
  amount numeric NOT NULL,
  amount_paid integer,
  tax_amount numeric DEFAULT 0,
  total_amount numeric NOT NULL,
  currency_id smallint NOT NULL,
  currency character varying,
  status character varying,
  invoice_date timestamp with time zone,
  period_start date,
  period_end date,
  invoice_pdf_url text,
  due_date date,
  paid_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone,
  CONSTRAINT Subscription_Invoice_pkey PRIMARY KEY (id),
  CONSTRAINT subscription_invoice_tenant_fkey FOREIGN KEY (tenant_id)
    REFERENCES "StreemLyne_MT"."Tenant_Master"(tenant_id),
  CONSTRAINT subscription_invoice_subscription_fkey FOREIGN KEY (subscription_id)
    REFERENCES "StreemLyne_MT"."Tenant_Subscription"(tenant_subscription_mapping_id),
  CONSTRAINT subscription_invoice_currency_fkey FOREIGN KEY (currency_id)
    REFERENCES "StreemLyne_MT"."Currency_Master"(currency_id)
);

CREATE INDEX IF NOT EXISTS idx_subscription_invoice_tenant_status
ON "StreemLyne_MT"."Subscription_Invoice"(tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_subscription_invoice_stripe_subscription
ON "StreemLyne_MT"."Subscription_Invoice"(stripe_subscription_id);
