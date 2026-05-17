# 📄 PRODUCT REQUIREMENTS DOCUMENT (PRD)

## Subscription Module – Multi-Tenant CRM

---

# 1. 📌 Overview

## 1.1 Objective

The Subscription Module enables monetization of the CRM by managing tenant-level subscriptions, including:

* Free trial handling
* Plan upgrades (Starter, Pro, Custom)
* Subscription enforcement (full app blocking after expiry)
* Payment integration via Stripe

---

## 1.2 Scope

### Included (Phase 1)

* 7-day free trial
* Monthly billing only
* Starter & Pro plans (Custom handled manually)
* Full app blocking after expiry
* Upgrade via in-app modal
* Tenant-level subscription (multi-tenant system)

---

### Excluded (Future Phases)

* Yearly billing
* Usage-based limits
* Seat-based pricing
* Coupons/discounts
* Grace period for failed payments

---

# 2. 🧠 Core Concepts

## 2.1 Subscription Ownership

* Subscription belongs to **Tenant (Organization)**
* Not individual users

---

## 2.2 User Roles

* Any authenticated tenant user can:

  * Upgrade plan
  * Manage subscription
* Role restrictions do not apply to billing actions

---

# 3. 🔄 Subscription Lifecycle

## 3.1 States

| State    | Description                      |
| -------- | -------------------------------- |
| trialing | Free trial active                |
| active   | Paid subscription                |
| expired  | Trial ended, no payment          |
| canceled | Subscription ended after billing |

---

## 3.2 Lifecycle Flow

```
Tenant Created
   ↓
Trial Starts (7 days)
   ↓
User gets reminders
   ↓
Trial Ends
   ↓
App Fully Blocked
   ↓
User Upgrades
   ↓
Stripe Checkout
   ↓
Subscription Active
```

---

# 4. ⚙️ Functional Requirements

---

## 4.1 Trial Management

### Behavior

* Trial starts automatically when tenant is created
* Duration: 7 days

---

### System Actions

* Create record in `Tenant_Subscription`
* Set:

  * `status = trialing`
  * `trial_end_date = created_at + 7 days`

---

### Acceptance Criteria

* Trial starts without user action
* Trial countdown is accurate
* Trial ends exactly after 7 days

---

## 4.2 Subscription Enforcement (CRITICAL)

### Behavior

* After trial expiry:

  * Entire app is blocked
  * No access to any module

---

### System Logic

```
IF status == active OR trialing → allow access
IF status == expired OR canceled → block access
```

---

### Enforcement Points

* Backend (Flask middleware)
* Frontend (route guard)

---

### Acceptance Criteria

* Expired users cannot access any page except subscription screen
* No API interaction is allowed
* No UI interaction is possible

---

## 4.3 Upgrade Flow

### Trigger Points

* Trial banner
* Sidebar button
* Block screen

---

### Flow

1. User clicks "Upgrade"
2. Upgrade modal opens
3. User selects plan
4. Redirect to Stripe Checkout (Starter / Pro only)
5. On success → subscription activated

---

### Acceptance Criteria

* Upgrade flow completes in ≤ 3 clicks
* Modal opens instantly
* Stripe redirect works correctly for Starter and Pro plans
* Custom plan does not redirect to Stripe — routes to sales contact

---

## 4.4 Plan Management

### Plans:

#### Starter

* Basic CRM usage
* Monthly billing
* Linked to `stripe_price_id` in `Subscription_Plans`

---

#### Pro (Highlighted)

* Advanced features (placeholder for now)
* Marked as "Most Popular"
* Linked to `stripe_price_id` in `Subscription_Plans`

---

#### Custom

* No Stripe integration
* **Does not have a `stripe_price_id`** — Custom plans are provisioned manually by the sales team
* Handled manually (sales contact)
* Selecting Custom plan opens a contact/sales form; it does not trigger a Stripe Checkout session

---

### Acceptance Criteria

* Plans are clearly distinguishable
* Pro plan is visually highlighted
* Custom plan does not trigger payment — routes to sales contact only

---

## 4.5 Cancellation

### Behavior

* User can cancel subscription
* Access continues until billing period ends

---

### Acceptance Criteria

* Subscription remains active until period end
* After end → status becomes `canceled`
* `canceled` status triggers the same full app blocking as `expired`

---

# 5. 🎨 UI / UX Requirements

---

## 5.1 Trial Banner

### Placement

* Top of dashboard

---

### Content

* "Your trial ends in X days"
* CTA: "Upgrade Now"

---

### Behavior

* Visible only during trial

---

## 5.2 Sidebar Upgrade Button

### Placement

* Inside user account dropdown

---

### Dynamic Labels

| State    | Label                 |
| -------- | --------------------- |
| trialing | Upgrade (X days left) |
| expired  | Upgrade Required      |
| active   | Manage Subscription   |

---

### Behavior

* Opens upgrade modal

---

## 5.3 Block Page (`/subscription-required`)

### Behavior

* Full screen (no sidebar)
* Cannot be bypassed

---

### Content

```
Your trial has ended  
Upgrade to continue using the CRM  
[Upgrade Now]
```

---

### Acceptance Criteria

* No navigation elements visible
* Only CTA is upgrade

---

## 5.4 Upgrade Modal

### Definition

A modal is a popup overlay that appears on top of the current page.

---

### Behavior

* Opens from anywhere
* **During `trialing` state**: modal can be dismissed — the user is not yet blocked and choosing to dismiss is a valid action
* **During `expired` state**: modal cannot be closed — the user must select a plan to proceed
* Must select a plan when in expired state

---

### Layout

* 3 plan cards:

  * Starter
  * Pro (highlighted)
  * Custom

---

### Hover / Micro-interaction Behaviour

* Pricing cards: scale up slightly + shadow on hover
* CTA buttons: transition to a darker primary colour on hover
* These micro-interactions apply on both the standalone pricing page and inside the upgrade modal

---

### Acceptance Criteria

* Modal is centered and responsive
* Pro plan is visually emphasized
* CTA buttons are clear and functional
* Modal is dismissible during trialing, locked during expired

---

# 6. 💳 Payment Integration

---

## 6.1 Checkout Flow

* Backend creates Stripe Checkout Session for Starter and Pro plans only
* Frontend redirects user to Stripe Checkout
* Custom plan does not initiate a Checkout Session — it opens a sales contact form

---

## 6.2 Webhooks (Backend)

Handle events:

* `checkout.session.completed`
* `invoice.paid`
* `customer.subscription.deleted`

---

## 6.3 Behavior

| Event                           | Action                |
| ------------------------------- | --------------------- |
| Payment success                 | Activate subscription |
| Cancel                          | Update status         |

---

### Acceptance Criteria

* Webhook updates DB correctly
* No manual sync required

---

# 7. 🔐 Security & Access Control

---

## 7.1 Backend Enforcement

* Every API call must validate subscription

---

## 7.2 Tenant Isolation

* All queries scoped by `tenant_id`

---

## 7.3 Role Restriction

* Any authenticated tenant user can upgrade or manage the subscription

---

### Acceptance Criteria

* Unauthenticated requests cannot upgrade (auth still required)
* Cross-tenant access is impossible

---

# 8. ⚡ Performance & Rate Limiting

---

## Requirements

* Prevent excessive API calls

---

## Implementation

* Flask rate limiting (e.g., 100 requests/minute per user)

---

### Acceptance Criteria

* API does not overload under normal use
* Abuse requests are throttled

---

# 9. ⚠️ Edge Cases & Error Handling

---

## Cases

### 1. Trial expires during session

* Redirect immediately to block page

---

### 2. Payment success but webhook delay

* Temporarily show loading state

---

### 3. User closes browser during checkout

* Subscription remains unchanged

---

### 4. Multiple users in tenant

* Subscription applies globally

---

### 5. Unauthenticated upgrade attempt

* Return 401

---

# 10. 🧾 Database Requirements

---

## Extend:

### `Tenant_Subscription`

Add:

* `status` — enum: trialing / active / expired / canceled
* `trial_end_date`
* `stripe_subscription_id`

---

### `Subscription_Plans`

Add:

* `stripe_price_id` — applies to Starter and Pro plans only; null for Custom plan

---

### `Tenant_Master`

Add:

* `stripe_customer_id` — required to associate Stripe invoices, payment methods, and subscription objects with the correct tenant

---

# 11. 📊 Success Metrics

---

## Product Metrics

* Trial → Paid conversion rate
* Time to upgrade
* Drop-off after trial

---

## Technical Metrics

* API success rate
* Webhook success rate
* Error rate < 1%

---

# 12. 🚀 Implementation Phases

---

## Phase 1 (MVP)

* Trial logic
* Block page
* Upgrade modal (dismissible during trial, locked when expired)
* Stripe checkout (Starter and Pro only)
* Custom plan sales contact flow
* Pricing card and button hover micro-interactions

---

## Phase 2

* Billing management page
* Cancellation UI
* Trust logos / social proof section on pricing page

---

## Phase 3

* Usage limits
* Seat pricing
* Yearly billing

---

# 🏁 Final Summary

A tenant-based subscription system with:

* Trial → enforced upgrade → Stripe billing
* Full app blocking after expiry or cancellation
* Modal-based upgrade UX (dismissible during trial, enforced when expired)
* Scalable architecture for future enhancements

---
