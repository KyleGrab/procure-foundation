# ProcureIQ — Local Execution Runbook

Everything below matches the actual code in `procureiq_phase5_final.zip` — file names, exact env
var names, exact commands — checked against the repo before writing this, not from memory. Where
something is a known gap rather than a working feature, it's called out as one.

**Before anything else:** this repository was built in a sandbox with no network access. None of
it — migrations, the FastAPI app, `npm install`, the frontend — has ever actually run. Everything
in `backend/tests_pure/` (156 tests) has been genuinely executed and passes; everything else is
syntax-checked and reasoned-through, not run. This runbook is the first time any of it will
actually be started end to end. Expect to hit and fix a small thing or two — that's normal for a
first real run, not a sign anything here was careless.

## 1. Environment & Setup Checklist

### 1.1 Prerequisites
- Docker + Docker Compose
- Python 3.12+
- Node 22+
- An Anthropic or OpenAI API key, only if you want to test the AI Copilot / negotiation brief —
  everything else works without one.

### 1.2 Environment variables

```bash
cp .env.example .env
```

Then edit `.env`. The keys that actually matter to get right:

| Variable | Purpose | Local dev default (from `.env.example`) |
|---|---|---|
| `SECRET_KEY` | JWT signing | **Change this** — `openssl rand -hex 32` |
| `DATABASE_URL` / `DATABASE_URL_SYNC` | Admin/migration connection (Alembic only) | `postgresql+asyncpg://procureiq:procureiq@localhost:5432/procureiq` / `postgresql+psycopg://...` |
| `DATABASE_URL_APP` | **The running app's actual connection** — least-privilege `procureiq_app` role (ADR-011) | `postgresql+asyncpg://procureiq_app:procureiq_app_dev_only_rotate_in_production@localhost:5432/procureiq` |
| `REDIS_URL` | Redis | `redis://localhost:6379/0` |
| `OBJECT_STORAGE_*` | MinIO (file uploads) | defaults work with the compose `minio` service as-is |
| `LLM_PROVIDER` | `anthropic` or `openai` | only matters if you're testing `/ai/query` or `/ai/negotiation-brief` |
| `LLM_API_KEY` | Real API key | leave blank to skip AI testing — everything else works without it |
| `NEXT_PUBLIC_API_URL` | Frontend → backend | `http://localhost:8000/api/v1` |

**Why there are two DB URLs, and why it matters for setup order:** `DATABASE_URL`/`_SYNC` is the
admin role Alembic uses to run migrations. `DATABASE_URL_APP` is a separate, least-privilege role
(`procureiq_app`) that the running FastAPI app actually connects as — and that role **does not
exist until migration 0004 runs**. Skip ahead to "Service Launch" before migrating and every API
call will fail with a database authentication error. This isn't a bug to work around; it's the
fix from ADR-011 (RLS didn't actually protect anything before this role existed) working as
intended — the ordering is now load-bearing, not optional.

### 1.3 Start infrastructure

```bash
docker compose up -d postgres redis minio
```

Don't start `backend`/`frontend` via compose yet — run them manually the first time so you can see
errors directly rather than through `docker compose logs`.

### 1.4 Run migrations

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
```

This runs all nine migrations (`0001` through `0009`) in one shot — foundation, price review,
contracts, the `procureiq_app` role + `FORCE ROW LEVEL SECURITY` fix (0004), rebates, purchase
transactions, price-review file staging, the full purchase ledger, and the Phase 5 opportunity
engine extensions. If this fails partway through, check the error against the specific migration
file named in the traceback — don't just retry, since a partially-applied migration can leave the
schema in a state `alembic upgrade head` won't cleanly re-attempt.

**Verify the role that everything downstream depends on actually got created:**
```bash
docker compose exec postgres psql -U procureiq -d procureiq -c \
  "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'procureiq_app';"
```
Expect one row: `rolsuper = f`, `rolbypassrls = f`. If this returns zero rows, migration 0004
didn't complete — nothing past this point will work, and the error you'll see everywhere else
will be a misleading "authentication failed" rather than an obvious "role missing" message.

## 2. Service Launch Sequence

### 2.1 Backend

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Confirm it's actually up before touching the frontend:
```bash
curl http://localhost:8000/api/v1/health
# expect: {"status":"ok"}
curl http://localhost:8000/api/v1/docs
# expect: the FastAPI/Swagger UI HTML, not a connection error
```

If this fails immediately with a DB connection error, re-check step 1.4's role verification
before anything else — that's the most likely cause.

### 2.2 Frontend

```bash
cd frontend
npm install
npm run dev
```

`npm install` is the step most likely to surface something this sandbox couldn't catch — it's the
first time `recharts`, `lucide-react`, and every other declared dependency actually get resolved
and type-checked against the code. If `next dev` reports a type error, it's real and needs
fixing; nothing in this delivery has been through `tsc` before now.

Frontend serves at `http://localhost:3000`.

## 3. Quick Verification Protocol (3-minute smoke test)

**Set expectations first:** a fresh database has zero purchase history. The dashboard is
*supposed* to render mostly empty states on first load — R0 metrics, "No purchase data yet",
"No spend data yet" — not an error. A blank chart is success here; a crashed page or a spinner
that never resolves is the failure to look for.

1. **Register** at `http://localhost:3000/register`. Should land you on `/dashboard` (this redirect
   was pointing at a page that was never built — `/onboarding` — and has been fixed as part of
   writing this runbook; if you're running an earlier build of this zip, you'll hit a 404 here and
   need to manually navigate to `/dashboard`).
2. **Dashboard loads without a JS error.** Open the browser console. The four metric cards should
   show Skeleton loaders briefly, then settle to R0 / "No data" values — not stay stuck loading,
   not throw an unhandled fetch error. This is the actual thing being tested: does the typed API
   client (`lib/dashboard-api.ts`) successfully reach the FastAPI backend, get back real (if
   empty) JSON, and render it — end-to-end wiring, not fake data.
3. **Confirm one real number flows through**, since an all-empty dashboard alone doesn't prove
   the ZAR formatting path works:
   ```bash
   cd backend
   python scripts/generate_synthetic_price_review_data.py   # writes real XLSX files, no DB needed
   python -m scripts.seed_phase2_demo
   ```
   **Be precise about what this actually seeds:** it inserts Cape Valley Foods as a supplier plus
   real `PriceReviewLine` rows (price increases/decreases/new/discontinued products) — proven
   correct back in Phase 2's demo run. It does **not** insert any `purchase_transactions` or
   `purchase_invoices` rows, so `/spend-analytics/by-supplier`, `/trend`, `/pareto`, and
   `/abc-classification` will still correctly show empty after seeding — that's not a bug, there's
   no purchase-ledger seed script yet (a real, tracked gap, not an oversight). What *should* change
   after seeding and a page refresh: the "Top Supplier Increases" panel (reads `PriceReviewLine`
   data directly) shows real ranked entries with progress bars, and the "PPV Leakage Identified"
   metric card shows a non-zero `formatZAR()`-formatted amount instead of R0.
4. **Confirm RLS is actually protecting something**, since that's the property this whole session
   cared about most: register a second account with a different organisation, log in as it, and
   confirm its dashboard is *also* empty (or shows only its own data if you've seeded it too) —
   never Cape Valley Foods' numbers leaking across. This is the fastest manual version of
   `backend/tests/test_tenant_isolation.py`.

If all four pass: registration → dashboard → real backend data → tenant isolation, in that order,
you have a genuinely working integrated system, not just a codebase that compiles.

## 4. Verifying the white-label gateway specifically

The `/welcome` page makes zero backend calls on its own (`resolveClientBrand()` only reads
`process.env`) - you can check the branding/gateway route in isolation before bringing up the
full stack, then do the real end-to-end check once the backend is up.

### 4.1 Branding/visual check only (no backend needed)

```bash
cd frontend
npm install
cp ../.env.example .env.local   # Next.js only reads frontend/.env.local for `npm run dev` -
                                  # NOT the root .env docker-compose uses (see .env.example's
                                  # own comment on this)
npm run dev
```

Open `http://localhost:3000/welcome` directly. Expect:
- Dark background (`#0B0D17`), "PPS LOGISTICS" small-caps label, "Choose your workspace" heading.
- The real worker character visible bottom-right on viewports ≥640px wide (hidden below that -
  check by resizing, not just a narrow window from the start).
- Three cards: Procurement Analysis, Management Accounting, Operations & Inventory.
- Click **Operations & Inventory** → real truck image slides left-to-right across a dark
  full-screen overlay (~1.1s), then the URL changes to `/dashboard/canvas?lens=operations` (this
  will show the canvas's own loading/error state without a backend running - that's the correct,
  expected result for this isolated check, not a bug).
- Click **Procurement Analysis** or **Management Accounting** → navigates immediately, no truck
  transition (by design - only Operations gets it).

**Test the override actually works**, not just the default: edit `frontend/.env.local`, change
`NEXT_PUBLIC_CLIENT_BRAND_NAME=Test Override Co`, save, hard-refresh the browser tab (Next.js
picks up `.env.local` changes on server restart, not always on save alone - restart `npm run dev`
if the label doesn't change). Confirm the small-caps label updates to "TEST OVERRIDE CO". Revert
before continuing.

**Test the fallback path deliberately**: temporarily rename or delete
`frontend/public/images/pps-logistics-worker-front-removebg-preview.png`, refresh `/welcome`.
Expect the worker character to simply disappear (the `onError` handler firing, `showWorker`
flips false) - not a broken-image icon, not a console error that breaks the page. Restore the
file afterward.

### 4.2 Full end-to-end check (needs the backend)

```bash
# terminal 1
docker compose up -d postgres redis minio
cd backend && alembic upgrade head && uvicorn app.main:app --reload

# terminal 2 (frontend already running from 5.1, or start it now)
cd frontend && npm run dev
```

1. Register a new account at `http://localhost:3000/register`.
2. Expect redirect to `/welcome`, not `/dashboard` directly (this was changed a few turns back -
   confirm it actually took effect, don't assume).
3. Click **Management Accounting** → lands on `/dashboard/canvas?lens=management` with the
   Management Accounting tab already active - confirms the `?lens=` deep link from the gateway
   card is actually being read by `ProcureIQCanvas.tsx`, not just navigated to and ignored.
4. Log out, log back in via `/login` → same `/welcome` redirect, not `/dashboard`.

If step 2 or 4 lands you on `/dashboard` instead of `/welcome`, the redirect change didn't take -
check `frontend/src/app/login/page.tsx` and `register/page.tsx` for `router.push("/welcome")`
before assuming anything else is wrong.

## 5. What to expect to fix on this first real run

Named honestly rather than left for you to discover cold:
- `npm install` may surface a version conflict between `recharts@2.13.0` and React 18/Next 15 that
  this sandbox had no way to catch (no network to install and test against).
- The `tests/` pytest suite (45 tests, tenant isolation + RLS integration + the new Phase 5 API
  tests) has never run — `pytest backend/tests/ -v` after the above is up is the next real
  verification step, and is likely to catch a handful of small issues the same way every
  `tests_pure/` run this session caught real bugs by actually executing.
- No purchase-ledger seed data exists — if you want the dashboard to show real spend trends and
  ABC/Pareto results, you'll need to either build a Phase 4b/4c seed script (following
  `scripts/seed_phase2_demo.py`'s pattern) or upload real data through `/purchase-transactions/
  {supplier_id}/upload` or `/purchase-invoices` manually.
