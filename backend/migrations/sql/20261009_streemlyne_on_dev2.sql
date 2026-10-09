-- Additive changes so the StreemLyne app runs on "streemLyne_mt_dev2".
-- Only ADD COLUMN / CREATE TABLE; nothing existing is altered or dropped.
BEGIN;
DO $$ BEGIN
  CREATE TYPE "streemLyne_mt_dev2".subscription_status_enum AS ENUM ('trialing','active','expired','canceled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE SEQUENCE IF NOT EXISTS "streemLyne_mt_dev2".quote_id_seq;
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "item_name" VARCHAR;
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "description" TEXT;
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "unit" VARCHAR DEFAULT 'each';
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "item_code" VARCHAR(50);
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "dimension_based" BOOLEAN DEFAULT false;
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "dimension_formula" VARCHAR;
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "door_type" VARCHAR(100);
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "width" INTEGER;
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "height" INTEGER;
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "depth" INTEGER;
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "brand" VARCHAR(50);
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "colour" VARCHAR(255);
ALTER TABLE "streemLyne_mt_dev2"."PriceList_Master" ADD COLUMN IF NOT EXISTS "alias_codes" TEXT;
ALTER TABLE "streemLyne_mt_dev2"."Client_Master" ADD COLUMN IF NOT EXISTS "client_contact_name" VARCHAR(255);
ALTER TABLE "streemLyne_mt_dev2"."Client_Master" ADD COLUMN IF NOT EXISTS "stage" VARCHAR(50);
ALTER TABLE "streemLyne_mt_dev2"."Client_Master" ADD COLUMN IF NOT EXISTS "is_deleted" BOOLEAN DEFAULT false;
ALTER TABLE "streemLyne_mt_dev2"."Client_Master" ADD COLUMN IF NOT EXISTS "assigned_employee_id" SMALLINT;
ALTER TABLE "streemLyne_mt_dev2"."Client_Master" ADD COLUMN IF NOT EXISTS "created_by_employee_id" SMALLINT;
ALTER TABLE "streemLyne_mt_dev2"."Tenant_Subscription" ADD COLUMN IF NOT EXISTS "updated_at" TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE "streemLyne_mt_dev2"."Tenant_Subscription" ADD COLUMN IF NOT EXISTS "status" "streemLyne_mt_dev2".subscription_status_enum DEFAULT 'trialing';
ALTER TABLE "streemLyne_mt_dev2"."Tenant_Subscription" ADD COLUMN IF NOT EXISTS "trial_end_date" TIMESTAMP WITH TIME ZONE;
ALTER TABLE "streemLyne_mt_dev2"."Tenant_Subscription" ADD COLUMN IF NOT EXISTS "stripe_subscription_id" VARCHAR(255);
ALTER TABLE "streemLyne_mt_dev2"."Tenant_Subscription" ADD COLUMN IF NOT EXISTS "cancel_at_period_end" BOOLEAN DEFAULT false;
ALTER TABLE "streemLyne_mt_dev2"."Tenant_Subscription" ADD COLUMN IF NOT EXISTS "current_period_start" TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE "streemLyne_mt_dev2"."Tenant_Subscription" ADD COLUMN IF NOT EXISTS "current_period_end" TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE "streemLyne_mt_dev2"."User_Master" ADD COLUMN IF NOT EXISTS "is_invite_pending" BOOLEAN DEFAULT false;
ALTER TABLE "streemLyne_mt_dev2"."User_Master" ADD COLUMN IF NOT EXISTS "invite_token" VARCHAR(100);
ALTER TABLE "streemLyne_mt_dev2"."User_Master" ADD COLUMN IF NOT EXISTS "invite_expires_at" TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE "streemLyne_mt_dev2"."User_Master" ADD COLUMN IF NOT EXISTS "created_by_employee_id" SMALLINT;
CREATE TABLE IF NOT EXISTS "streemLyne_mt_dev2"."Proposal_Master" (
	quote_id VARCHAR(10) DEFAULT 'QUO-' || lpad(nextval('"streemLyne_mt_dev2".quote_id_seq')::text, 3, '0') NOT NULL, 
	proposal_id SERIAL NOT NULL, 
	tenant_id INTEGER, 
	client_id SMALLINT, 
	project_id SMALLINT, 
	currency_id SMALLINT, 
	sub_total NUMERIC(12, 2), 
	total_amount NUMERIC(12, 2) NOT NULL, 
	discount_percent FLOAT(24), 
	discount_amount NUMERIC(12, 2), 
	tax_id SMALLINT, 
	customer_name VARCHAR(255), 
	notes TEXT, 
	company_details JSON, 
	payment_details JSON, 
	tax_breakdown JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (proposal_id), 
	UNIQUE (quote_id), 
	FOREIGN KEY(tenant_id) REFERENCES "streemLyne_mt_dev2"."Tenant_Master" (tenant_id), 
	FOREIGN KEY(client_id) REFERENCES "streemLyne_mt_dev2"."Client_Master" (client_id), 
	FOREIGN KEY(currency_id) REFERENCES "streemLyne_mt_dev2"."Currency_Master" (currency_id)
);
CREATE TABLE IF NOT EXISTS "streemLyne_mt_dev2"."Proposal_Details" (
	proposal_details_id SERIAL NOT NULL, 
	proposal_id INTEGER NOT NULL, 
	quantity NUMERIC(10, 2) NOT NULL, 
	amount NUMERIC(12, 2), 
	service_id SMALLINT NOT NULL, 
	uom_id SMALLINT NOT NULL, 
	service_name VARCHAR(255), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (proposal_details_id), 
	FOREIGN KEY(proposal_id) REFERENCES "streemLyne_mt_dev2"."Proposal_Master" (proposal_id), 
	FOREIGN KEY(service_id) REFERENCES "streemLyne_mt_dev2"."Services_Master" (service_id), 
	FOREIGN KEY(uom_id) REFERENCES "streemLyne_mt_dev2"."UOM_Master" (uom_id)
);
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Master" ADD COLUMN IF NOT EXISTS "proposal_id" SMALLINT;
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Master" ADD COLUMN IF NOT EXISTS "sub_total" FLOAT(24);
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Master" ADD COLUMN IF NOT EXISTS "vat" NUMERIC(12, 2);
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Master" ADD COLUMN IF NOT EXISTS "other_taxes" NUMERIC(12, 2);
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Master" ADD COLUMN IF NOT EXISTS "discount_percent" FLOAT(24);
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Master" ADD COLUMN IF NOT EXISTS "payment_status" VARCHAR(50) DEFAULT 'Not Paid';
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Master" ADD COLUMN IF NOT EXISTS "tax_id" SMALLINT;
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Details" ADD COLUMN IF NOT EXISTS "service_id" SMALLINT;
ALTER TABLE "streemLyne_mt_dev2"."Invoice_Details" ADD COLUMN IF NOT EXISTS "service_name" VARCHAR(500);
COMMIT;
