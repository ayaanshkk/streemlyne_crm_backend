-- Invoice lines for the new invoice table.
--
-- Invoice_Master_New (the client's new invoice header table) has no lines
-- table: Invoice_Details still points at the retired Invoice_Master. Both old
-- tables are empty, so Invoice_Details is re-pointed at Invoice_Master_New
-- and its invoice_id widened to bigint to match "Invoice_ID".
--
-- Safe to re-run.

BEGIN;

ALTER TABLE "streemLyne_mt_dev2"."Invoice_Details"
  DROP CONSTRAINT IF EXISTS "Invoice_Details_invoice_id_fkey";

ALTER TABLE "streemLyne_mt_dev2"."Invoice_Details"
  ALTER COLUMN invoice_id TYPE BIGINT;

ALTER TABLE "streemLyne_mt_dev2"."Invoice_Details"
  ADD CONSTRAINT "Invoice_Details_invoice_id_fkey"
  FOREIGN KEY (invoice_id) REFERENCES "streemLyne_mt_dev2"."Invoice_Master_New"("Invoice_ID")
  ON DELETE CASCADE;

COMMIT;
