---
title: 'Portal web UI (React + Fluent UI v9) wired to accounts and payments APIs'
type: 'feature'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: 'cebec97fdb401c762e9c9bf6629a2052e7a488c8'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['inline-single']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-corportal-2026-09-30/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-corportal-2026-09-30/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-corportal-2026-09-30/mockups/portal.html'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The APIs exist, but there is no portal for treasurers or for the demo. The approved mockup (the owner: "ui is perfect") has to become a working app.

**Approach:**
- Build a Vite + React + TypeScript SPA using Fluent UI v9 `webLightTheme`. It reproduces the mockup's five screens, the Behind-the-scenes drawer, the region badge and the synthetic banner, all driven by live API data.
- Serve it from an nginx container that also proxies `/api/accounts/*` and `/api/payments/*` in compose. In AKS, Kong does the same routing.

## Boundaries & Constraints

**Always:**
- The mockup layout and copy, and the EXPERIENCE.md voice and state patterns (AED formatting `AED 1,900,000`).
- Money arrives from the API as strings. Format it with `Intl.NumberFormat('en-AE')`, never with float arithmetic on totals.
- The region badge shows the `X-Served-From` header of the most recent API response, uses `aria-live="polite"`, and refreshes on every call.
- Auth, chosen by `VITE_AUTH_MODE`:
  - `dev` sends `X-Demo-User`. The PoC-only user switcher in the user menu offers Priya, Tom and Omar.
  - `entra` uses `@azure/msal-react`: login redirect and a bearer token. "Switch user" re-runs login with `prompt: select_account`.
- The Dashboard auto-refreshes every 30 s.
- ≤10 UI tests in total (Vitest + Testing Library). The project-wide cap is 100, and 11 are already used.

**Never:**
- Chart libraries (inline SVG only, per DESIGN.md).
- A state-management library.
- Changes to payment or ledger logic.
- Terraform.
- Real pipeline status in the drawer. Piece 3 adds the trace endpoint.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Dashboard | Priya signed in | KPIs AED 5,800,000 / 1,780,000 / −120,000; payroll line; Unusual payments card | Skeleton while loading |
| Self-approval | Priya views her own awaiting payment | Approve and Reject disabled, tooltip "You can't approve a payment you created." | — |
| Approve | Tom clicks Approve | Row moves to History as Executed; dashboard live block updates on next refresh | 409 → MessageBar with the API's message |
| Cross-company | API returns 404 on a deep link | error MessageBar "You don't have access to that company's data." | — |
| API down | fetch fails or 5xx | warning MessageBar "Can't reach the bank right now. Retrying…", auto-retry every 5 s | clears on success |
| Region change | `X-Served-From` changes | badge text updates, dot flashes once | — |

</frozen-after-approval>

## Code Map

- `services/accounts-api/app.py`:
  - `/me`, `/accounts`, `/accounts/{id}/transactions` and `/dashboard` exist already. `/dashboard` returns serving KPIs, trend, anomalies and an `operational` live block.
  - **Add `GET /forecast`**, reading `serving.forecast` for the caller's company (30 days plus the model name and version) and scoped like `/dashboard`. Add one test to `tests/test_apis.py`.
- `services/payments-api/app.py`: `/payments` (with a `status` filter), `POST /payments`, `/payments/{id}/approve|reject` and `/beneficiaries`. Reuse these as they are.
- `services/common/corp_common/middleware.py` sets `X-Served-From`. Browsers only see it when it's exposed, which nginx handles because calls are same-origin, so no CORS change is needed.
- `docker-compose.yml`: add the `portal-web` service on port 8080.
- Mockup IDs and copy to mirror: `mockups/portal.html` (the screens `#dashboard #accounts #payments #forecast`, the drawer `#bts` and the failover and error states).

## Tasks & Acceptance

**Execution:**
- [x] `services/accounts-api/app.py`, `tests/test_apis.py` -- `GET /forecast` + 1 test -- the Forecast screen needs data.
- [x] `web/` (package.json, vite.config.ts, tsconfig, index.html, src/**) -- the SPA:
  - an `api.ts` fetch wrapper that captures the region header and handles auth;
  - `AuthProvider` (dev/entra);
  - `Shell` (banner, top bar, nav, badge, user menu with switcher);
  - pages `Login`, `Dashboard`, `Accounts`, `Payments`, `Forecast`;
  - `BehindTheScenes` drawer. It shows Ledger ✓ from the payment status and the remaining stages as pending with "Pipeline status available after piece 3". It links to `VITE_LINEAGE_URL`.
- [x] `web/Dockerfile`, `web/nginx.conf` -- a multi-stage build; nginx serves the SPA with an SPA fallback and proxies `/api/accounts/` → `accounts-api:8000/` and `/api/payments/` → `payments-api:8000/`. Runtime config (`/config.js`) is generated from env at container start, so one image works in every environment.
- [x] `docker-compose.yml`, `README.md` (run section) -- add portal-web.
- [x] `web/src/**/*.test.tsx` -- ≤10 tests covering the matrix rows (mock fetch).

**Acceptance Criteria:**
- Given `docker compose up`, when you open `localhost:8080` as Priya, then the dashboard shows the Northwind figures and the badge reads "Serving from: local".
- Given Priya creates an AED 450,000 Reserve→Operating payment and switches to Tom, when Tom approves it, then it shows Executed and the dashboard's live figures update within 30 s.
- Given `npm run build`, when it completes, then there are no TypeScript errors.

## Implementation Notes

- `GET /forecast` returns `{company, currency, model: {name, version}, generated_at, points: [{date, predicted, lower, upper}]}`; test `test_forecast_is_30_days_scoped_to_callers_company`.
- SPA: no router or state library. `router.ts` is a small history-API path router (`/dashboard`, `/accounts[/:id]`, `/payments`, `/forecast`); `api.ts` holds two tiny stores (region, reachable) read with `useSyncExternalStore`.
- Money: `money.ts` parses API strings into BigInt fils and formats with `Intl.NumberFormat('en-AE')`; floats only place chart pixels.
- API down: any network error or 5xx marks the bank unreachable → a global warning MessageBar; the Shell probes `/me` every 5 s and pages reload failed loads on recovery.
- Dashboard shows the serving KPIs (5,800,000 / 1,780,000 / −120,000) plus a "Live ledger now" line from `operational`, which is what moves within 30 s after an approval until piece 3 refreshes the serving figures.
- Runtime config: `/config.js` is written by `docker-entrypoint.d/40-portal-config.sh` from `VITE_*` env; nginx upstreams come from `ACCOUNTS_API_URL`/`PAYMENTS_API_URL` and are resolved per request, so the container starts even when an API is down.
- Entra mode (`@azure/msal-react`) is lazy-loaded and type-checked, but not exercised: there is no tenant yet.
- 8 UI tests (7 in `App.test.tsx`, 1 in `money.test.ts`); project total 12 + 8 = 20.

## Plan Change Log

## Review Triage Log

- Pass 1 (one inline reviewer): 1 medium patched, 2 low deferred.
  - medium, patch: host port 8080 clashed with the owner's Jenkins SSH tunnel; compose now maps the portal to 8088 (container still listens on 8080, so AKS is unaffected).
  - low, deferred to piece 3/4: the headline Available only moves once serving is refreshed; the chart jumps at Today because actual and forecast measure different things.
  - low, accepted: `Table` used instead of `DataGrid`; no batch countdown until piece 3.
  - Browser walkthrough is left to the owner.

## Verification

**Commands:**
- `cd web && npm ci && npm run build && npx vitest run` -- expected: build OK, ≤10 tests pass.
- `uv run pytest -q` -- expected: 12 pass.
- `docker compose up -d --build && curl -s localhost:8080/api/accounts/dashboard -H 'X-Demo-User: priya'` -- expected: 200 JSON.

**Manual checks:**
- Walk EXPERIENCE.md Flow 1 in the browser and compare it with `mockups/portal.html`.
