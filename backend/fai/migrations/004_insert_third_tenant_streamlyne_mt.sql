-- Inserts one new tenant row into StreamLyne_MT.Tenant_Master.
-- This does not modify or delete existing tenant rows.
INSERT INTO "StreamLyne_MT"."Tenant_Master" (
    "Tenant_id",
    "tenant_company_name",
    "tenant_contact_name",
    "onboarding_date",
    "is_active"
)
SELECT
    COALESCE(MAX("Tenant_id"), 0) + 1,
    'My CRM Project',
    'CRM Admin',
    CURRENT_DATE,
    TRUE
FROM "StreamLyne_MT"."Tenant_Master"
WHERE NOT EXISTS (
    SELECT 1
    FROM "StreamLyne_MT"."Tenant_Master"
    WHERE LOWER("tenant_company_name") = LOWER('My CRM Project')
)
RETURNING "Tenant_id";
