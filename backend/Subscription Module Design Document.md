# 📄 Pricing Plans Page Design Document (Updated)
## CRM Subscription Module (Tailark-Based Custom Implementation)

---

# 1. 🎯 Purpose & Goals

## 1.1 Objective
Design a **modern, high-conversion pricing system** adapted from Tailark design, customized for:
- Multi-tenant CRM architecture
- Subscription-based billing
- Stripe integration
- Upgrade modal + pricing page reuse

---

## 1.2 Key Improvements Over Base Design

- Removed Free plan
- Added Starter, Pro, Custom plans
- Currency changed to £ (GBP)
- Integrated with backend subscription system
- Designed for both modal and page usage
- Multi-tenant aware

---

# 2. 🧱 Final Layout & Structure

## Layout

----------------------------------------
[ Header ]

[ 3 Pricing Cards ]
Starter | Pro ⭐ | Custom

----------------------------------------

---

## Grid

- Desktop: 3 columns
- Tablet: 2 columns
- Mobile: 1 column

---

# 3. 🎨 Visual Design

## Colors
- Background: bg-muted
- Card: bg-card
- Primary: text-primary
- Secondary: text-muted-foreground

---

## Highlighted Plan (Pro)
- border-primary
- shadow-lg
- scale-105
- Badge: Most Popular

---

## Typography
- Title: text-3xl / text-4xl
- Price: text-4xl / text-5xl
- Plan name: text-xl

---

## Currency
All prices use:
£ (British Pound)

Example:
£49 / month

---

# 4. 🧩 Plan Definitions

## Starter
- Basic CRM usage
- CTA: Select Plan

## Pro ⭐
- Highlighted
- CTA: Upgrade Now

## Custom
- Manual plan
- CTA: Contact Sales

---

# 5. ⚡ Interaction Design

## Trial Banner

### Placement
- Top of dashboard, above all other content

### Content
- "Your trial ends in X days"
- CTA button: "Upgrade Now"

### Behavior
- Visible only during `trialing` state
- Hidden once subscription is `active` or `canceled`
- Countdown is calculated from `trial_end_date` in `Tenant_Subscription`

---

## Sidebar Upgrade Button

### Placement
- Inside user account dropdown in the app sidebar (`nav-user.tsx`)

### Dynamic Labels

| State    | Label                     |
| -------- | ------------------------- |
| trialing | Upgrade (X days left)     |
| expired  | Upgrade Required          |
| active   | Manage Subscription       |

### Behavior
- Opens upgrade modal on click
- Label and behaviour update reactively based on current subscription state

---

## Block Page

### Route
`/subscription-required`

### Layout
- Full screen — no sidebar, no navigation elements
- Only visible element is the upgrade CTA

### Content
```
Your trial has ended
Upgrade to continue using the CRM
[Upgrade Now]
```

### Behavior
- Cannot be bypassed by navigating to other routes
- Upgrade Now button opens the upgrade modal

---

## Buttons

Starter → Select Plan  
Pro → Upgrade Now  
Custom → Contact Sales  

---

## Hover Effects
- Cards: scale + shadow
- Buttons: darker primary

---

## Modal Behavior

- Used for upgrade
- **During `trialing` state**: modal can be dismissed (user is not yet blocked)
- **During `expired` state**: modal cannot be closed — user must select a plan to proceed
- Forces user decision only when subscription has expired

---

# 6. 🔗 Backend Integration

## Data Source

Tables:
- Subscription_Plans
- Tenant_Subscription
- Currency_Master

---

## Mapping

- name → subscription_name
- price → price
- currency → currency_id

---

## Plan Selection Flow

User clicks plan  
→ API call  
→ Stripe Checkout (Starter / Pro only)  
→ Webhook  
→ DB updated  

---

## Webhook Events

The backend must handle the following Stripe webhook events to keep the DB in sync:

| Event                             | Action                                      |
| --------------------------------- | ------------------------------------------- |
| `checkout.session.completed`      | Activate subscription, set status = active  |
| `invoice.paid`                    | Renew subscription, extend end date         |
| `customer.subscription.deleted`   | Set status = canceled                       |

- Webhook handler must match events to tenants via `stripe_subscription_id` stored in `Tenant_Subscription`
- No manual DB sync required; all state transitions are driven by webhooks

---

# 7. 💳 Payment Integration

Using Stripe:

- Each **Starter and Pro** plan is linked to a `stripe_price_id`
- **Custom plan is excluded from Stripe** — it has no `stripe_price_id` and does not trigger a Stripe Checkout session. Custom plan enquiries route to a sales contact flow only
- Backend creates checkout session for Starter and Pro
- Frontend redirects user to Stripe Checkout for Starter and Pro; Custom plan CTA opens a contact/sales form instead

---

# 8. 🧠 Subscription States

- trialing
- active
- expired
- canceled

### Cancellation Behaviour
- When a user cancels, access continues until the current billing period ends
- After the billing period ends, status transitions to `canceled`
- A `canceled` tenant is treated the same as `expired` for access control purposes — full app blocking applies

---

# 9. 🚫 Access Control

## Subscription Enforcement

- expired / canceled → full app blocked
- only `/subscription-required` accessible
- modal forced on upgrade when expired

---

## Role-Based Access Control

- Only the **Tenant Owner** can upgrade a plan, manage billing, or cancel a subscription
- Other users within the tenant:
  - Can view current subscription status
  - Cannot interact with upgrade, billing, or cancellation flows
- Unauthorized upgrade attempts return a `403` response from the backend
- The upgrade modal and sidebar subscription button must be hidden or disabled for non-owner users

---

## Edge Cases

| Scenario                              | Behaviour                                                              |
| ------------------------------------- | ---------------------------------------------------------------------- |
| Trial expires during active session   | Redirect immediately to `/subscription-required`                       |
| Payment success but webhook delayed   | Show a loading/pending state; do not block access until confirmed      |
| User closes browser during checkout   | Subscription remains unchanged; no partial state written               |
| Multiple users in same tenant         | Subscription status applies globally to all users in the tenant        |
| Unauthorized upgrade attempt          | Return 403; show error message to non-owner users                      |

---

# 10. 📱 Responsiveness

- Mobile: stacked cards
- Tablet: 2 columns
- Desktop: 3 columns

---

# 11. ♿ Accessibility

- keyboard navigation
- proper headings
- accessible buttons
- good contrast

---

# 12. 🚀 Enhancements

- trust logos section
- feature comparison (future)
- yearly billing (future)

---

# 13. ✅ Acceptance Criteria

UI:
- 3 plans displayed
- Pro highlighted
- GBP currency used
- Trial banner visible at top of dashboard during trialing state
- Sidebar upgrade button shows correct label per subscription state
- Block page renders full screen with no navigation

UX:
- clear CTAs
- modal works correctly — dismissible during trial, locked when expired
- no confusion
- Tenant Owner restriction enforced on upgrade flow

Integration:
- Stripe works for Starter and Pro plans
- Custom plan does not trigger Stripe — routes to contact/sales flow
- DB synced via webhooks
- subscription enforced

---

# 14. 🏁 Final Summary

This is a **Tailark-inspired pricing system customized for a multi-tenant CRM SaaS**, with:
- clean UI
- strong upgrade flow
- Stripe-ready architecture
- scalable design

---

# 📌 Next Steps

- Implement React component
- Connect backend APIs
- Integrate Stripe