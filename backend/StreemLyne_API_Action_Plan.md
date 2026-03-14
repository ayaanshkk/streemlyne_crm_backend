# StreemLyne CRM — API & Frontend Consolidated Code Review Action Plan

**Scope:** `api.ts` · `app.py` · `streem-ai/page.tsx` · `chatbot/page.tsx` · `settings/page.tsx` · `useInvoiceQuote.ts` · `CreateCustomerModal.tsx`  
**Total Issues:** 3 Critical · 5 Medium · 2 Low · 1 Info

---

## All Issues at a Glance

| # | Severity | File | Issue | Phase |
|---|----------|------|-------|-------|
| 1 | 🔴 CRITICAL | `api.ts` | Tenant ID sent as query param (`?tenant_id=`) — backend registered `X-Tenant-ID` as an allowed header, implying header-based delivery | 1 |
| 2 | 🔴 CRITICAL | `streem-ai/page.tsx` | 21 occurrences of `/customers`, `/jobs` — bypasses `/api/*` prefix so `tenant_id` is never injected | 1 |
| 3 | 🔴 CRITICAL | `useInvoiceQuote.ts` | `tenant_id` typed as `string` — DB schema defines it as `smallint` (numeric); PostgreSQL will throw a cast error on invoice/quote creation | 1 |
| 4 | 🟠 MEDIUM | `api.ts` | Dual token lookup: `localStorage.getItem('auth_token') \|\| localStorage.getItem('token')` — inconsistency between staff and customer portal login flows | 2 |
| 5 | 🟠 MEDIUM | `api.ts` | Customer portal public endpoints (`/customer/login`, `/customer/register`) missing from `publicEndpoints` list — Bearer token incorrectly attached to unauthenticated routes | 2 |
| 6 | 🟠 MEDIUM | `api.ts` | `localStorage.clear()` on 401 wipes all stored data including non-auth state (preferences, tenant config) | 2 |
| 7 | 🟠 MEDIUM | `chatbot/page.tsx` | Hardcoded `http://127.0.0.1:5000` in error message — should use `config.apiUrl` | 2 |
| 8 | 🟠 MEDIUM | `settings/page.tsx` | Hardcoded URL in read-only display field — should use `config.apiUrl` | 2 |
| 9 | 🟡 LOW | `api.ts` | Dev bypass via `config.apiUrl.includes('localhost')` too broad — localhost staging against real DB silently skips auth. Use `NODE_ENV` only | 3 |
| 10 | 🟡 LOW | `api.ts` | No graceful handling when `drawing_bp` or `assignment_bp` returns 404 (conditional backend modules) | 3 |
| 11 | 🔵 INFO | `CreateCustomerModal.tsx` | Missing fields (stage, industry, notes) — pending design decision on Opportunities integration | Backlog |

---

## Phase 1 — Fix Immediately (Breaks Production)

> These three issues will cause runtime failures or silent data corruption in production. Fix before any deployment.

---

### Issue 1 · Tenant ID Delivery Method

**`CRITICAL` — `api.ts` — getTenantId / apiRequest**

The backend registers `X-Tenant-ID` as an allowed CORS header, strongly implying blueprints read it from the request headers. The frontend delivers it as a query parameter. These two approaches are mutually exclusive — one will always be ignored.

#### Step 1 — Confirm which method your blueprints use

Search your Flask route files for one of these patterns:

```python
# Header-based (matches CORS allow_headers declaration)
tenant_id = request.headers.get('X-Tenant-ID')

# Query-param-based (matches current api.ts behaviour)
tenant_id = request.args.get('tenant_id')
```

#### Step 2 — Apply the matching fix in api.ts

If blueprints use headers (recommended):

```typescript
const requestConfig: RequestInit = {
  ...options,
  headers: {
    "Content-Type": "application/json",
    "X-Tenant-ID": getTenantId(),          // ← add this
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  },
};
```

> Remove the `fullEndpoint` query-param injection block entirely once headers are confirmed working.

---

### Issue 2 · streem-ai Endpoints Missing /api/ Prefix

**`CRITICAL` — `streem-ai/page.tsx` — 21 occurrences**

Endpoints like `/customers` and `/jobs` skip the `/api/*` prefix check in `apiRequest`. This means `tenant_id` is never injected, breaking multi-tenant data isolation entirely for this page.

#### Required replacements

| Current | Replace With | Note |
|---------|-------------|------|
| `/customers` | `/api/clients` | Maps to `ClientMaster` in schema |
| `/jobs` | `/api/projects` | Maps to `ProjectDetails` in schema |
| `/customers/:id` | `/api/clients/:id` | Include `tenant_id` via header/param |
| `/jobs/:id` | `/api/projects/:id` | Include `tenant_id` via header/param |

> After renaming, verify each endpoint exists in the corresponding Flask blueprint (`client_bp`, `project_bp`).

---

### Issue 3 · tenant_id Type Mismatch

**`CRITICAL` — `useInvoiceQuote.ts` — lines 16, 26**

The DB schema defines `tenant_id` as `smallint`. The TypeScript hook types it as `string`. PostgreSQL is strict about numeric type coercion — passing a string will throw a cast error at query execution time, silently failing all invoice and quote creation.

#### Fix

```typescript
// Before
tenant_id: string

// After
tenant_id: number
```

Also audit any component that calls this hook and ensure it passes a numeric value, not a stringified tenant ID from `localStorage` (which always returns `string`).

```typescript
// Safe conversion at call site
tenant_id: Number(localStorage.getItem('tenantId') ?? '0')
```

---

## Phase 2 — Fix Before Next Release (Correctness & Security)

---

### Issue 4 · Dual Token Key Lookup

**`MEDIUM` — `api.ts`**

```typescript
const token = localStorage.getItem('auth_token') || localStorage.getItem('token');
```

This pattern exists because staff login (`UserMaster`/JWT) and customer portal login (`CustomerAuth`) likely store tokens under different keys. This is fragile — a partially-logged-in state could return the wrong token or no token silently.

#### Fix

Standardise both login flows to write to one key:

```typescript
// In both staff login and customer portal login handlers:
localStorage.setItem('auth_token', token)

// In api.ts — simplified, single key:
const token = localStorage.getItem('auth_token');
```

---

### Issue 5 · Customer Portal Endpoints Missing from publicEndpoints

**`MEDIUM` — `api.ts`**

```typescript
const publicEndpoints = ["/auth/register", "/auth/login", "/auth/check-company"];
```

The backend has a `customer_bp` covering `CustomerAuth` and `CustomerPasswordReset`. Customer-facing login/register endpoints are not in this list, so the frontend will attempt to attach a Bearer token to unauthenticated routes.

#### Fix — add customer portal routes

```typescript
const publicEndpoints = [
  "/auth/register",
  "/auth/login",
  "/auth/check-company",
  "/customer/login",           // ← add
  "/customer/register",        // ← add
  "/customer/reset-password",  // ← add (CustomerPasswordReset)
];
```

> Verify the exact path prefixes used in `customer_bp` and update accordingly.

---

### Issue 6 · Destructive localStorage.clear() on 401

**`MEDIUM` — `api.ts`**

```typescript
localStorage.clear();
```

Clearing all of `localStorage` on session expiry will wipe UI preferences, cached tenant config, and any other state stored by the app. Replace with targeted key removal:

```typescript
// Replace localStorage.clear() with:
localStorage.removeItem("auth_token");
localStorage.removeItem("token");
localStorage.removeItem("tenantId");
```

---

### Issue 7 · Hardcoded URL in chatbot/page.tsx

**`MEDIUM` — `chatbot/page.tsx` — line 1177**

```typescript
// Before
const url = "http://127.0.0.1:5000/api/chat";

// After
import { config } from "@/lib/config";
const url = `${config.apiUrl}/api/chat`;
```

---

### Issue 8 · Hardcoded URL in settings/page.tsx

**`MEDIUM` — `settings/page.tsx` — line 1066**

```tsx
// Before
<span>http://127.0.0.1:5000</span>

// After
import { config } from "@/lib/config";
<span>{config.apiUrl}</span>
```

---

## Phase 3 — Cleanup (Low Risk, Good Hygiene)

---

### Issue 9 · Overly Broad Dev Mode Bypass

**`LOW` — `api.ts`**

```typescript
const isDevelopment =
  process.env.NODE_ENV === "development" ||
  !process.env.NODE_ENV ||
  config.apiUrl.includes("localhost");  // ← too broad
```

The `localhost` URL check means any environment that points to a local server — including a developer running against a real production DB — silently bypasses auth. This masks authentication bugs that only surface in production.

#### Fix

```typescript
// Rely solely on NODE_ENV
const isDevelopment = process.env.NODE_ENV === "development" || !process.env.NODE_ENV;
```

---

### Issue 10 · No Graceful Handling for Conditional Blueprint 404s

**`LOW` — Anywhere calling `/api/drawing/*` or `/api/assignments/*`**

The backend conditionally registers `drawing_bp` only if `DRAWING_MODULE_AVAILABLE` is true. If the frontend calls a drawing or assignment endpoint when the module is off, the API returns a 404. The current error handler will surface a generic network error with no context.

#### Recommended approach

```typescript
if (error.status === 404 && endpoint.startsWith('/api/drawing')) {
  throw new ApiError(404, 'Drawing Analyser module is not enabled on this account');
}
```

---

## Backlog

### Issue 11 · CreateCustomerModal Missing Fields

**`INFO` — `CreateCustomerModal.tsx`**

Fields for `stage`, `industry`, and `notes` are absent from the modal. These map to the Opportunities system (`OpportunityDetails` / `StageMaster`) rather than `ClientMaster` directly. Options:

- Route post-creation to an Opportunity creation step
- Add a second modal step that creates a linked Opportunity record
- Defer until a dedicated Opportunity onboarding flow is designed

---

## Verification Checklist

Use this after applying all fixes to confirm production readiness.

| # | Check | How to Verify | Done |
|---|-------|---------------|------|
| 1 | Blueprint route files confirmed to use header OR query-param for `tenant_id` (not both) | Code search | ☐ |
| 2 | `api.ts` tenant delivery matches blueprint expectation | Network tab in DevTools | ☐ |
| 3 | All `streem-ai` endpoints prefixed with `/api/` and verified in blueprint | API test | ☐ |
| 4 | `useInvoiceQuote` `tenant_id` is `number`, call sites pass numeric value | TypeScript compile | ☐ |
| 5 | Single token key used across all login flows | Auth flow test | ☐ |
| 6 | Customer portal endpoints in `publicEndpoints` list | Network tab on login | ☐ |
| 7 | `localStorage.clear()` replaced with targeted key removal | Code review | ☐ |
| 8 | No hardcoded `127.0.0.1` or `localhost` URLs in any page file | `grep` search | ☐ |
| 9 | Dev bypass uses `NODE_ENV` only | Code review | ☐ |
| 10 | 404 from drawing/assignment returns friendly error message | Unit test / manual | ☐ |
