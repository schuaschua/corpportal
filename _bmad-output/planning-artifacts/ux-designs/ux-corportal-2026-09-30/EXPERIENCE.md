---
name: Contoso Digital Bank — Corporate Portal (PoC)
status: final
sources:
  - _bmad-output/specs/spec-corporate-portal-poc/SPEC.md
  - _bmad-output/specs/spec-corporate-portal-poc/demo-script.md
updated: 2026-09-30
---

# Corporate Portal PoC — Experience Spine

## Foundation

This is a desktop web app for a laptop-and-projector demo. It uses Fluent UI v9 in React. `DESIGN.md` is the visual reference, and this spine specifies behaviour. Every user belongs to exactly one fake company, and every screen is scoped to that company (SPEC CAP-1). All data is synthetic.

## Information Architecture

| Surface | Reached from | Purpose | CAP |
|---|---|---|---|
| Login | App URL | Entra External ID sign-in | CAP-1 |
| Dashboard | Nav, and after login | Cash position, liquidity trend, recent anomalies | CAP-2, CAP-8 |
| Accounts | Nav | Account list; select one to see balance and transactions | CAP-3 |
| Payments | Nav | Create a payment, approval queue, payment history with anomaly flags | CAP-4, CAP-8 |
| Forecast | Nav | 30-day ML cash forecast, with model name and version | CAP-7 |
| Behind the scenes | "Behind the scenes" button on Payments and Dashboard | Right-hand drawer tracking the latest payment through the stages | CAP-5 |

**Global chrome, on every screen:**
- A synthetic-data banner.
- A top bar with the bank name, the company name, the region badge (CAP-12) and the user menu.
- A left nav with 4 items.

Only one dialog can be open at a time. The drawer and dialogs never stack.

Visual reference: `mockups/portal.html`. If the mockup and this spine disagree, the spine wins.

## Voice and Tone

The copy is plain treasury language, stating amounts and dates. All amounts are in UAE dirham, written `AED 1,900,000` (the code first, with thousands separators). Account numbers are UAE IBANs (`AE07 …`), and company names end in LLC.

| Do | Don't |
|---|---|
| "Payroll due Thu 8 Oct — AED 1,900,000" | "Upcoming obligation detected!" |
| "Awaiting approval from Tom Okafor" | "Pending" |
| "Unusual: 4× this supplier's average" | "AI alert 🚨" |
| "You can't approve a payment you created." | "Error 403" |
| "Serving from: North Central US" | "Failover active" |

## Component Patterns

| Component | Use | Behavioral rules |
|---|---|---|
| KPI card | Dashboard | Three cards: Total cash, Available (every account except Reserve) after scheduled payments, and the 7-day forecast low. They are read-only. |
| Account row | Accounts | Clicking a row shows its transactions in a DataGrid below. There is no inline editing. |
| New payment form | Payments | Fields: from account, beneficiary (dropdown of synthetic suppliers), amount, date and reference. Submitting creates the payment with status "Awaiting approval". |
| Approval queue | Payments | Shows payments awaiting approval from the current user, with Approve and Reject buttons. The creator sees the row with the buttons disabled, and a tooltip explains why. |
| Anomaly flag | Payments history, Dashboard | Appears on any payment scored as anomalous. Hovering shows the score and reason. It never blocks the payment. |
| Stage panel | Behind the scenes drawer | Shows the latest payment ID. Steps tick as each stage completes: Ledger → Event Hubs → Bronze → Silver → Gold → Serving. The drawer checks for updates every 5 s. A "Next batch in mm:ss" countdown uses the configured cadence. The final step offers "View lineage", which opens Unity Catalog in a new tab (CAP-6). |
| Region badge | Top bar | Shows the region that served the last API response, read from a response header. It updates on every call. |
| Forecast chart | Forecast | Actual balance as a solid line, forecast as a dashed line with a shaded band, and a "today" marker. The caption names the model and its version from MLflow. |

## State Patterns

| State | Surface | Treatment |
|---|---|---|
| Loading | Any | Fluent `Skeleton` rows or cards |
| Batch not yet run | Stage panel | Ledger and Event Hubs are ticked, the rest are muted, and "Next batch in 4:12" is shown |
| Batch done | Stage panel, Dashboard | All steps are ticked. Figures on the Dashboard update on its next refresh (30 s interval) |
| Self-approval attempt | Approval queue | Buttons are disabled, with the tooltip "You can't approve a payment you created." |
| Cross-company access | Any API call | A `MessageBar` (error) reads "You don't have access to that company's data." The attempt is logged (CAP-14) |
| Region change | Top bar | The badge text changes and the dot flashes once. No modal |
| API unavailable | Any | A `MessageBar` (warning) reads "Can't reach the bank right now. Retrying…" and retries automatically |
| No anomalies | Dashboard | "No unusual payments in the last 30 days." |

## Interaction Primitives

- Mouse first. This is a demo, not a power-user tool.
- `Esc` closes the drawer or dialog.
- Data refreshes itself: the Dashboard every 30 s, the drawer every 5 s. There is no manual refresh button.
- Not used: drag and drop, infinite scroll, stacked modals.

## Accessibility Floor

This is a PoC, so the floor is Fluent's defaults:
- Keyboard access for every action.
- Visible focus.
- The region badge is an `aria-live="polite"` region, so failover is announced.

## Demo Controls

This section covers what the demo needs.
- A user switcher in the user menu, **for the PoC only**, lets the owner switch between Priya and Tom without signing out. It still goes through Entra with two test accounts. `[ASSUMPTION]`
- The "Behind the scenes" button can be pressed at any time. The drawer overlays the screen and doesn't navigate away.

## Key Flows

### Flow 1: Payroll squeeze (Priya Nair, Treasurer, Northwind Logistics, Monday 7:45)

1. Priya signs in. The Dashboard shows Total cash of AED 5.8m, and **Available (excl. Reserve) after scheduled payments of AED 1.78m**, which is below the AED 1.9m payroll due Thursday.
2. The Recent anomalies card shows one flag: "Unusual: 4× Harbour Freight's average."
3. On Payments, she creates a AED 450,000 transfer from the Reserve account to Operating, dated today. Its status is "Awaiting approval from Tom Okafor".
4. She switches to Tom, who approves it. The status changes to Executed.
5. She opens **Behind the scenes**. Ledger ✓ and Event Hubs ✓ are ticked, and "Next batch in 0:24" is counting down.
6. **Climax:** Bronze ✓ → Silver ✓ → Gold ✓ → Serving ✓ tick in turn. She closes the drawer. The Available figure now reads AED 2.23m, and the Forecast's dashed line no longer dips below payroll. She clicks "View lineage" and Unity Catalog shows the path from gold back to the raw event.

Failure: if Tom rejects the payment, its status becomes Rejected (shown in red) and nothing flows to the lake.

### Flow 2: Region down (Priya, same session, Act 5)

1. The badge reads "Serving from: West US 3".
2. Off screen, the owner deletes the region 1 ingress.
3. For up to about 60 s, calls may fail. The warning `MessageBar` reads "Can't reach the bank right now. Retrying…"
4. **Climax:** the badge changes to "Serving from: North Central US" and the MessageBar clears. Priya's AED 450k payment is still in her history, and Grafana on the second screen shows the traffic moving to region 2.
