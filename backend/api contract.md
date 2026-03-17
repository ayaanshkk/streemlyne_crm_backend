# API Contract — Full Backend Reference
> Covers: `client_routes.py`, `job_routes.py`, `project_routes.py`, `opportunity_routes.py`, `employee_routes.py`
> All endpoints require JWT (`@auth_required`). Tenant isolation is automatic via `g.tenant_id`.
> Last updated: after reviewing all five route files.

---

## ⚠️ Critical Finding — Two Separate Project Endpoints

There are **two active route files** for the same underlying `Project_Details` table:

| Route file | URL prefix | Response shape | Misc_Col1 fields | Legacy aliases |
|---|---|---|---|---|
| `job_routes.py` | `/api/jobs` | `_project_to_job_dict` | ✅ Unpacked (job_reference, stage, priority, etc.) | ✅ Yes (id, title, customer_id, etc.) |
| `project_routes.py` | `/api/projects` | `_project_dict` | ❌ Not included | ❌ None |

**Frontend rule:** Use `/api/jobs` for the jobs/projects list and detail views — it returns the richer shape including all Misc_Col1 fields. `/api/projects` is the clean canonical endpoint but loses all misc data in its response. The create form on `/api/jobs` POST accepts `customer_id` as an alias for `client_id`; `/api/projects` POST only accepts `client_id`.

---

## 1. `/api/clients`

### `GET /api/clients`
**Query params:** `name` (partial, `client_company_name`), `country_id` (int)
**Response 200:** `Client[]`

### `POST /api/clients` — requires `client.create`
**Required:** `client_company_name` (also as `name`)
**Optional:** `client_contact_name` / `contact_name`, `client_email` / `email`, `client_phone` / `phone`, `address`, `post_code` / `postcode`, `country_id`, `default_currency_id`, `client_website`
**Response 201:** `Client` | **400** missing name | **409** duplicate

### `GET /api/clients/:client_id`
Returns full detail: client + interactions[] + opportunities[] + form_submissions[]

**Embedded opportunity shape:**
```
opportunity_id, opportunity_title, opportunity_description,
stage_id (int ⚠️ — not a name), opportunity_value, currency_id,
service_id, start_date, end_date, created_at
```

### `PUT /api/clients/:client_id` — requires `client.update`
Same field aliases as POST. Partial update — only sent fields change.
**Response 200:** `{ message, client: Client }` | **409** constraint

### `DELETE /api/clients/:client_id` — requires `client.delete`
**Response 409** if client is referenced by Opportunity_Details or Customer_Auth.

### Interaction sub-routes
| Method | URL | Permission | Notes |
|---|---|---|---|
| GET | `/api/clients/:id/interactions` | auth only | Newest first |
| POST | `/api/clients/:id/interactions` | `client.interaction.create` | `contact_date` + `contact_method` required |
| PUT | `/api/clients/:id/interactions/:iid` | `client.interaction.update` | Partial update |
| DELETE | `/api/clients/:id/interactions/:iid` | `client.interaction.delete` | |

> ⚠️ `contact_method` is a smallint FK. No lookup endpoint identified yet — needs investigation before building the interaction form UI.

### Client object shape
```typescript
// Canonical — use these
client_id:           number
tenant_id:           number
client_company_name: string
client_contact_name: string | null
client_email:        string | null
client_phone:        string | null
address:             string | null
post_code:           string | null
country_id:          number | null
default_currency_id: number | null
client_website:      string | null
created_at:          string | null

// @deprecated aliases — backwards compat only
id, name, email, phone, postcode
```

---

## 2. `/api/jobs` (job_routes.py — preferred for frontend)

### `GET /api/jobs`
Tenant-scoped via `Client_Master` join.
**Query params:** `customer_id`, `employee_id`, `opportunity_id`, `ref`, `stage`, `priority`, `account_manager`, `team_member`/`team`, `from_date`, `to_date`
> ⚠️ String params (`ref`, `stage`, etc.) do ILIKE on the raw JSON blob — not exact match.

### `GET /api/jobs/:job_id`
**Response 200:** Job object

### `POST /api/jobs` — requires `project.create`
| Field | Required | Notes |
|---|---|---|
| `customer_id` | ✅ | Also as `client_id`. Tenant-validated. |
| `opportunity_id` | ✅ | int FK → Opportunity_Details. NOT NULL. |
| `employee_id` | ✅ | int FK → Employee_Master. NOT NULL. |
| `title` | ✅ | Also as `project_title` or `job_name` |
| `start_date` | ✅ | ISO date |
| `end_date` / `due_date` | — | |
| `address` / `location` | — | |
| `job_reference` | — | Auto-generated `JOB-XXXXXXXX` if omitted |
| `stage` | — | Free string → Misc_Col1 |
| `priority` | — | Misc_Col1, default `"Medium"` |
| `job_type` | — | Misc_Col1, default `"General"` |
| `estimated_value`, `agreed_value`, `deposit_amount`, `deposit_due_date` | — | Misc_Col1 |
| `primary_contact`, `account_manager` | — | Misc_Col1 |
| `team_members` | — | Array or comma string → Misc_Col1 |
| `tags`, `notes`, `requirements`, `completion_date` | — | Misc_Col1 |

**Response 400:** Lists exactly which required fields are missing (use this in the UI).
**Response 409:** Invalid `opportunity_id` or `employee_id` FK.

### `PUT /api/jobs/:job_id` — requires `project.update`
All fields optional. Misc_Col1 fields are **merged** — existing values preserved if not re-sent.

### `DELETE /api/jobs/:job_id` — requires `project.delete`
**Response 409** if referenced by invoices or energy contracts.

### `GET /api/jobs/pipeline-opportunities?stage=Closed Won`
Resolves stage by name (case-insensitive) → `stage_id` via Stage_Master. Returns opportunities in that stage.

### `PUT /api/jobs/pipeline-opportunities/:opportunity_id/stage`
**Body:** `{ "stage_id": number }` — must be valid Stage_Master PK.

### Job object shape (`_project_to_job_dict`)
```typescript
// Canonical project fields
project_id:          number
client_id:           number
opportunity_id:      number
project_title:       string
project_description: string | null
start_date:          string | null
end_date:            string | null
employee_id:         number
address:             string | null
created_at:          string | null
updated_at:          string | null

// From Misc_Col1 JSON blob
job_reference:    string | null
stage:            string | null   // ⚠️ free string, NOT a stage_id
priority:         string           // default "Medium"
job_type:         string           // default "General"
completion_date:  string | null
estimated_value:  number | null
agreed_value:     number | null
deposit_amount:   number | null
deposit_due_date: string | null
primary_contact:  string | null
account_manager:  string | null
team_members:     string[]
tags:             string | null
notes:            string | null
requirements:     string | null

// @deprecated aliases
id, title, description, customer_id, customer_name, due_date, location
```

---

## 3. `/api/projects` (project_routes.py — canonical, no Misc_Col1)

Use this only if you don't need Misc_Col1 data. POST uses `client_id` only (no `customer_id` alias).

### `GET /api/projects`
**Query params:** `client_id`, `employee_id`, `opportunity_id`

### `POST /api/projects` — requires `project.create`
**Required:** `client_id`, `opportunity_id`, `project_title`, `start_date`, `employee_id`
**Optional:** `project_description`, `end_date`, `address`
> Note: NO `customer_id` alias here — must send `client_id`.

### `GET /api/projects/:project_id`
Returns project + `energy_contracts[]` array.

### `PUT /api/projects/:project_id` — requires `project.update`
Updatable: `project_title`, `project_description`, `employee_id`, `address`, `start_date`, `end_date`

### `DELETE /api/projects/:project_id` — requires `project.delete`
**Response 409** if referenced by invoices, proposals, or energy contracts.

### Project object shape (`_project_dict`) — clean, no aliases, no Misc_Col1
```typescript
project_id, client_id, opportunity_id, project_title,
project_description, start_date, end_date, employee_id,
address, created_at, updated_at
```

---

## 4. `/api/opportunities`

### `GET /api/opportunities`
**Query params:** `client_id`, `stage_id` (int), `assigned_to` (employee_id), `owner` (employee_id), `service_id`, `include_deleted` (bool, default false)
> ✅ Use `GET /api/opportunities?client_id=X` to populate the opportunity dropdown after client selection on the job create form.

### `POST /api/opportunities` — requires `opportunity.create`
**Required:** `opportunity_title`, `stage_id` (int FK)
**Optional:** `client_id`, `opportunity_description`, `opportunity_date`, `opportunity_owner_employee_id`, `assigned_to_employee_id`, `opportunity_value`, `currency_id`, `service_id`, `start_date`, `end_date`, `mpan_mpr`, `business_name`, `contact_person`, `tel_number`, `email`

### `GET /api/opportunities/:opportunity_id`
### `PUT /api/opportunities/:opportunity_id` — requires `opportunity.update`
### `DELETE /api/opportunities/:opportunity_id` — requires `opportunity.delete`
Soft-delete only (`deleted_at` timestamp set). Hard-delete not exposed.

### `PATCH /api/opportunities/:opportunity_id/stage` — requires `opportunity.update`
**Body:** `{ "stage_id": number }` — Kanban drag-and-drop handler.

### `PATCH /api/opportunities/:opportunity_id/assign` — requires `opportunity.assign`
**Body:** `{ "employee_id": number | null }` — pass null to unassign.

### `GET /api/opportunities/pipeline`
Returns all active opportunities grouped by `stage_id` as a dict:
```json
{ "1": [Opportunity, ...], "2": [...] }
```
Keys are `stage_id` as strings.

### `GET /api/opportunities/stages` ← **Use this to load stage names**
Returns all Stage_Master rows. Use to populate stage dropdowns and resolve `stage_id` → display name.

### Stage CRUD — requires `opportunity.manage_stages`
| Method | URL |
|---|---|
| POST | `/api/opportunities/stages` |
| PUT | `/api/opportunities/stages/:stage_id` |
| DELETE | `/api/opportunities/stages/:stage_id` |

### Opportunity object shape (`_opportunity_dict`) — no legacy aliases
```typescript
opportunity_id:                  number
tenant_id:                       number
client_id:                       number | null
opportunity_title:               string
opportunity_description:         string | null
opportunity_date:                string | null
stage_id:                        number          // ⚠️ always int, never string
opportunity_value:               number | null
currency_id:                     number | null
service_id:                      number | null
opportunity_owner_employee_id:   number | null
assigned_to_employee_id:         number | null
start_date:                      string | null
end_date:                        string | null
mpan_mpr:                        string | null
business_name:                   string | null
contact_person:                  string | null
tel_number:                      string | null
email:                           string | null
deleted_at:                      string | null   // null = active
created_at:                      string
```

### Stage object shape
```typescript
stage_id:           number
stage_name:         string
stage_description:  string | null
preceding_stage_id: number | null
stage_type:         number
```

---

## 5. `/api/employees`

### `GET /api/employees` ← **Use this to populate employee dropdown on job create form**
**Query params:** `designation_id` (int), `name` (partial match)
**Response 200:** `Employee[]` ordered by `employee_name`

### `POST /api/employees` — requires `employee.create`
**Required:** `employee_name`
**Optional:** `email` (unique across table), `phone`, `employee_designation_id`, `date_of_birth`, `date_of_joining`, `id_type`, `id_number`, `commission_percentage`

### `GET /api/employees/:employee_id`
### `PUT /api/employees/:employee_id` — requires `employee.update`
Updatable: `employee_name`, `phone`, `employee_designation_id`, `id_type`, `id_number`, `commission_percentage`, `email`, `date_of_birth`, `date_of_joining`
### `DELETE /api/employees/:employee_id` — requires `employee.delete`
**Response 409** if referenced by opportunities, projects, or energy contracts.

### `GET /api/employees/designations`
Not tenant-scoped — global lookup table.

### Designation CRUD — requires `employee.manage_designations`
| Method | URL |
|---|---|
| POST | `/api/employees/designations` |
| PUT | `/api/employees/designations/:designation_id` |
| DELETE | `/api/employees/designations/:designation_id` |

### Employee object shape (`_employee_dict`) — no legacy aliases
```typescript
employee_id:              number
tenant_id:                number
employee_name:            string
email:                    string | null
phone:                    string | null
employee_designation_id:  number | null
designation:              string | null  // resolved label from relationship, if loaded
date_of_birth:            string | null
date_of_joining:          string | null
id_type:                  string | null
id_number:                string | null
commission_percentage:    number | null
created_on:               string | null
updated_on:               string | null
```

---

## 6. Job Create Form — Required API Calls

This is the complete sequence the `jobs/page.tsx` create form must make:

```
1. On page load:
   GET /api/clients                    → populate client dropdown

2. On client selected:
   GET /api/opportunities?client_id=X  → populate opportunity dropdown
                                         (filtered to selected client, excludes deleted)

3. On page load (can be parallel with step 1):
   GET /api/employees                  → populate employee dropdown

4. On form submit:
   POST /api/jobs  {
     customer_id:    number   ← from client dropdown (also accepts client_id)
     opportunity_id: number   ← from opportunity dropdown (REQUIRED)
     employee_id:    number   ← from employee dropdown (REQUIRED)
     title:          string   ← required
     start_date:     string   ← required ISO date
     end_date?:      string
     address?:       string
     // misc fields optional
   }
```

---

## 7. Global Constraints Summary

| Rule | Detail |
|---|---|
| `opportunity_id` + `employee_id` are NOT NULL on job create | Backend returns 400 with field names listed |
| `stage_id` is always an integer | Never use a stage name string as a FK value |
| Stage names for display | Fetch from `GET /api/opportunities/stages` — never hardcode |
| `stage` on a Job (Misc_Col1) is a free string | Not linked to Stage_Master — different concept from opportunity stage |
| Opportunity delete is soft only | `deleted_at` is set; `GET /api/opportunities` excludes deleted by default |
| Project tenant scoping is via join | Project_Details has no `tenant_id` — join through Client_Master |
| Use `/api/jobs` not `/api/projects` for the jobs page | Only `/api/jobs` returns Misc_Col1 fields |
| All API calls via `api.ts` | Never raw `fetch()` with hardcoded tenant IDs |
| `contact_method` on interactions | int FK — lookup endpoint not yet identified |

---

## 6b. `/api/master`

All lookup/reference data. Most are global (not tenant-scoped) except Services.

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /api/master/countries` | auth | Global. Returns `country_id`, `country_name`, `country_isd_code` |
| `GET /api/master/currencies` | auth | Global. Returns `currency_id`, `currency_name`, `currency_code` |
| `GET /api/master/uoms` | auth | Global. Returns `uom_id`, `uom_description` |
| `GET /api/master/services` | auth | **Tenant-scoped.** Query param: `supplier_id`. Use to populate service dropdowns on proposal/invoice forms |
| `GET /api/master/suppliers` | auth | Global |
| `GET /api/master/modules` | auth | Active modules only |
| `GET /api/master/modules/tenant` | auth | Modules enabled for current tenant |

> ⚠️ **`contact_method` has NO lookup endpoint.** `Client_Interactions.contact_method` is a smallint FK in the schema but there is no `Contact_Method_Master` table in the DDL and no route serving a lookup list. This is a backend gap — the interaction form UI cannot resolve int → label until this is addressed. Options: (a) add a master table + route, (b) hardcode a small enum on the frontend.

> ⚠️ **`tax_id` has NO lookup endpoint.** `tax_id` is NOT NULL on both `Proposal_Master` and `Invoice_Master`, but there is no `Tax_Master` table in the schema DDL and no route in any reviewed file. This will block proposal and invoice create forms. Must be resolved before those forms can be built.

---

## 6c. `/api/proposals`

> ⚠️ Proposal_Master has no `tenant_id`. Tenant isolation via Client_Master join. Always supply `client_id` on create.

### `GET /api/proposals`
**Query params:** `client_id` (recommended), `project_id`
Returns list without `details[]` array (lightweight).

### `POST /api/proposals` — requires `proposal.create`
| Field | Required | Notes |
|---|---|---|
| `tax_id` | ✅ | NOT NULL in schema. **No lookup endpoint exists yet — see gap above** |
| `total_amount` | ✅ | NOT NULL |
| `client_id` | — | Recommended. Tenant-validated if supplied |
| `project_id` | — | FK → Project_Details |
| `currency_id` | — | FK → Currency_Master |
| `sub_total` | — | |
| `discount_percent` | — | |
| `discount_amount` | — | |
| `details` | — | Array of line items (see below). Validated before any write. |

**Detail line object (all required if sending):**
```json
{ "service_id": 2, "quantity": 10.0, "uom_id": 3 }
```
> ⚠️ No free-text line items. `service_id` → Services_Master, `uom_id` → UOM_Master. Both are FK references. Use `GET /api/master/services` and `GET /api/master/uoms` to populate dropdowns.

**Response 201:** Full proposal with `details[]`
**Response 400:** Missing `tax_id`/`total_amount`, or malformed detail line (error names the line index)
**Response 409:** Invalid FK (`project_id`, `service_id`, `uom_id`)

### `GET /api/proposals/:proposal_id`
Returns proposal + `details[]`.

### `PUT /api/proposals/:proposal_id` — requires `proposal.update`
Header fields only (`tax_id`, `currency_id`, `sub_total`, `total_amount`, `discount_percent`, `discount_amount`, `client_id`, `project_id`). Manage line items via sub-resource.

### `DELETE /api/proposals/:proposal_id` — requires `proposal.delete`
Cascades to detail lines. **Response 409** if referenced by an invoice.

### Detail line sub-resource
| Method | URL | Notes |
|---|---|---|
| GET | `/api/proposals/:id/details` | List lines |
| POST | `/api/proposals/:id/details` | Add line. Requires `service_id`, `quantity`, `uom_id` |
| PUT | `/api/proposals/:id/details/:did` | Update line |
| DELETE | `/api/proposals/:id/details/:did` | Remove line |

### Proposal object shape
```typescript
proposal_id:      number
client_id:        number | null
project_id:       number | null
tax_id:           number           // NOT NULL — no lookup endpoint yet
sub_total:        number | null
currency_id:      number | null
total_amount:     number           // NOT NULL
discount_percent: number | null
discount_amount:  number | null
created_at:       string
updated_at:       string | null
details?:         ProposalDetail[] // included on GET single, excluded on list
```

### ProposalDetail object shape
```typescript
proposal_details_id: number
proposal_id:         number
service_id:          number   // FK → Services_Master
quantity:            number
uom_id:              number   // FK → UOM_Master
created_at:          string
updated_at:          string | null
```

---

## 6d. `/api/invoices`

Invoice_Master mirrors Proposal_Master in structure. Same FK pattern, same line-item sub-resource, same `tax_id` gap.

> ⚠️ Invoice_Master has no `tenant_id`. Tenant isolation uses a dual subquery: `client_id` → Client_Master, OR `project_id` → Project_Details → Client_Master. Both paths checked on every read/write.

### `GET /api/invoices`
**Query params:** `client_id`, `project_id`, `proposal_id`
Returns list without `details[]` (lightweight).

### `POST /api/invoices` — requires `invoice.create`
| Field | Required | Notes |
|---|---|---|
| `invoice_number` | ✅ | Must be unique within tenant. 409 on collision |
| `tax_id` | ✅ | NOT NULL. **No lookup endpoint — backend gap** |
| `total_amount` | ✅ | NOT NULL |
| `client_id` | — | Tenant-validated if supplied |
| `project_id` | — | Tenant-validated if supplied |
| `proposal_id` | — | FK → Proposal_Master |
| `billing_remarks` | — | |
| `currency_id` | — | FK → Currency_Master |
| `sub_total`, `discount_percent`, `discount_amount` | — | |
| `details` | — | Array of `{ service_id, quantity, uom_id }` — all three required per line |

> ⚠️ No free-text line items. `service_id` → Services_Master, `uom_id` → UOM_Master. Both FK-validated on write.

**Response 201:** Full invoice with `details[]` | **400** missing fields | **409** duplicate number or invalid FK

### `GET /api/invoices/:invoice_id`
Returns invoice + `details[]`.

### `PUT /api/invoices/:invoice_id` — requires `invoice.update`
Header fields only. `invoice_number` change is tenant-scoped uniqueness-checked before write.

### `DELETE /api/invoices/:invoice_id` — requires `invoice.delete`
Cascades to detail lines.

### Detail line sub-resource
| Method | URL |
|---|---|
| GET | `/api/invoices/:id/details` |
| POST | `/api/invoices/:id/details` — requires `service_id`, `quantity`, `uom_id` |
| PUT | `/api/invoices/:id/details/:did` |
| DELETE | `/api/invoices/:id/details/:did` |

### Invoice object shape — no legacy aliases
```typescript
invoice_id, client_id, project_id, proposal_id,
invoice_number: string,      // NOT NULL, unique within tenant
billing_remarks: string | null,
tax_id: number,              // NOT NULL — no lookup endpoint yet
currency_id, sub_total, total_amount, discount_percent, discount_amount,
created_at, updated_at,
details?: InvoiceDetail[]    // included on GET single, excluded on list
// InvoiceDetail: invoice_details_id, invoice_id, service_id, quantity, uom_id, created_at, updated_at
```

---

## 6e. `/api/forms`

Customer-facing form token system. Minimal frontend relevance for the current migration sprint — no changes needed here. Token store is in-memory (single-process only — not production-safe at scale).

| Endpoint | Auth | Use |
|---|---|---|
| `POST /api/forms/clients/:id/generate-link` | staff auth | Issue one-time form link |
| `GET /api/forms/validate-token/:token` | none | Customer form page validation |
| `POST /api/forms/submit` | none | Customer submission |
| `GET /api/forms/submissions` | staff auth | View submissions |

---

## 8. Resolved vs Remaining Unknowns

| Item | Status |
|---|---|
| `contact_method` lookup endpoint | ❌ **Gap confirmed** — no lookup table or route exists anywhere in the backend. Must be resolved before interaction form UI can be built |
| `tax_id` lookup endpoint | ❌ **Gap confirmed** — NOT NULL FK on Proposal_Master + Invoice_Master but no Tax_Master table in schema and no route. Blocks proposal + invoice create forms |
| Stages endpoint for dropdown | ✅ `GET /api/opportunities/stages` |
| Opportunity dropdown for job form | ✅ `GET /api/opportunities?client_id=X` |
| Employee dropdown for job form | ✅ `GET /api/employees` |
| Service dropdown for proposa l/invoice | ✅ `GET /api/master/services` (tenant-scoped) |
| UOM dropdown for proposal/invoice | ✅ `GET /api/master/uoms` |
| Currency dropdown | ✅ `GET /api/master/currencies` |
| `invoice_routes.py` | ✅ Reviewed — section 6d |
| `CreateCustomerModal.tsx` POST payload | ❌ Not yet audited against `POST /api/clients` contract |