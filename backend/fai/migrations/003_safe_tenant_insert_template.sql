-- Additive-only tenant onboarding insert.
-- This writes ONE new row to tenant_master and does not alter schema/data of existing tenants.
-- Keep exact identifier casing for your production schema (example uses "TenantId").

WITH next_tenant AS (
    SELECT COALESCE(MAX("TenantId"), 0) + 1 AS next_id
    FROM tenant_master
),
inserted AS (
    INSERT INTO tenant_master (
        "TenantId",
        tenant_company_name,
        tenant_contact_name,
        onboarding_date,
        is_active,
        created_at,
        updated_at
    )
    SELECT
        next_tenant.next_id,
        :tenant_name,
        :tenant_contact_name,
        :onboarding_date,
        TRUE,
        NOW(),
        NOW()
    FROM next_tenant
    WHERE NOT EXISTS (
        SELECT 1
        FROM tenant_master
        WHERE LOWER(COALESCE(tenant_company_name, '')) = LOWER(:tenant_name)
    )
    RETURNING "TenantId"
)
SELECT * FROM inserted;
