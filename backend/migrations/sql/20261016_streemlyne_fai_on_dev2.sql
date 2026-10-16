-- StreemLyne + FAI on the shared database "streemLyne_mt_dev2".
--
-- 1. 11 columns StreemLyne needs that have no place in the new tables:
--      User_Master          team invitations (4)
--      Tenant_Subscription  trials / subscriptions / Stripe billing (7)
-- 2. Automatic ID numbering for older tables whose primary key has none.
--    The client's new tables (Quotation_Master_new, Lead_Master, ...) already
--    number themselves and are left alone.
--
-- Additive only: nothing is dropped, renamed or changed in type.
-- Safe to re-run: every step checks first. Re-running also moves each
-- numbering sequence past the highest existing ID, so run it again right
-- before go-live (older code still assigns IDs as MAX + 1).

BEGIN;

-- ---------------------------------------------------------------- 1. columns
DO $$ BEGIN
  CREATE TYPE "streemLyne_mt_dev2".subscription_status_enum
    AS ENUM ('trialing', 'active', 'expired', 'canceled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE "streemLyne_mt_dev2"."User_Master"
  ADD COLUMN IF NOT EXISTS is_invite_pending      BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS invite_token           VARCHAR(100),
  ADD COLUMN IF NOT EXISTS invite_expires_at      TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS created_by_employee_id SMALLINT;

ALTER TABLE "streemLyne_mt_dev2"."Tenant_Subscription"
  ADD COLUMN IF NOT EXISTS status                 "streemLyne_mt_dev2".subscription_status_enum DEFAULT 'trialing',
  ADD COLUMN IF NOT EXISTS trial_end_date         TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255),
  ADD COLUMN IF NOT EXISTS cancel_at_period_end   BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS current_period_start   TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS current_period_end     TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS updated_at             TIMESTAMP WITHOUT TIME ZONE;

-- Invite links are looked up by token
CREATE UNIQUE INDEX IF NOT EXISTS "User_Master_invite_token_key"
  ON "streemLyne_mt_dev2"."User_Master" (invite_token)
  WHERE invite_token IS NOT NULL;

-- ------------------------------------------------- 2. automatic ID numbering
DO $$
DECLARE
  r record;
  seq text;
BEGIN
  -- every single-column integer primary key in the schema (pg_catalog is
  -- used instead of information_schema, which is very slow on Supabase)
  FOR r IN
    SELECT cl.relname AS tbl, a.attname AS col,
           pg_get_expr(d.adbin, d.adrelid) AS dflt,
           CASE WHEN a.attidentity <> '' THEN 'YES' ELSE 'NO' END AS ident
    FROM pg_index i
    JOIN pg_class cl      ON cl.oid = i.indrelid
    JOIN pg_namespace n   ON n.oid = cl.relnamespace
    JOIN pg_attribute a   ON a.attrelid = cl.oid AND a.attnum = i.indkey[0]
    LEFT JOIN pg_attrdef d ON d.adrelid = cl.oid AND d.adnum = a.attnum
    WHERE n.nspname = 'streemLyne_mt_dev2'
      AND i.indisprimary
      AND i.indnatts = 1
      AND a.atttypid IN ('int2'::regtype, 'int4'::regtype, 'int8'::regtype)
  LOOP
    IF r.ident = 'YES' THEN
      CONTINUE;  -- identity columns (the new tables) number themselves
    END IF;

    IF r.dflt IS NULL THEN
      seq := left(r.tbl || '_' || r.col, 54) || '_auto_seq';
      EXECUTE format('CREATE SEQUENCE IF NOT EXISTS "streemLyne_mt_dev2".%I', seq);
      EXECUTE format('ALTER TABLE "streemLyne_mt_dev2".%I ALTER COLUMN %I SET DEFAULT nextval(%L)',
                     r.tbl, r.col, '"streemLyne_mt_dev2".' || quote_ident(seq));
      EXECUTE format('ALTER SEQUENCE "streemLyne_mt_dev2".%I OWNED BY "streemLyne_mt_dev2".%I.%I',
                     seq, r.tbl, r.col);
    ELSIF r.dflt LIKE 'nextval(%' THEN
      seq := substring(r.dflt from '''([^'']+)''');   -- existing sequence
    ELSE
      CONTINUE;
    END IF;

    -- start after the highest existing ID
    EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(%I) FROM "streemLyne_mt_dev2".%I), 0) + 1, false)',
                   CASE WHEN seq LIKE '"%' OR seq LIKE '%.%' THEN seq ELSE '"streemLyne_mt_dev2".' || quote_ident(seq) END,
                   r.col, r.tbl);
  END LOOP;
END $$;

COMMIT;
