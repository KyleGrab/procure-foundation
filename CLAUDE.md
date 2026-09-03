# CLAUDE.md

## Mandatory reading before any change

**`UNIVERSAL_ENGINEERING_SPEC.md` (project root) is binding, not advisory.** Read it before
writing or reviewing code in this repo. Section references below (`§2.1`, `§4.2`, etc.) point into
that document. If a change conflicts with something in it, the spec wins unless there's an
explicit, written reason logged in `docs/decisions/` for the exception — the same way every
deviation from the original master spec already lives as a numbered ADR in this repo.

## What this project is

ProcureIQ — a multi-tenant B2B procurement intelligence platform. Full architecture:
`docs/architecture.md`. Full data model: `docs/data-model.md`. Phase-by-phase status, including
what's genuinely verified vs. syntax-checked-only: `docs/implementation-plan.md`.

## Running things

**No network access in the sandbox that built this so far** — nothing below has been confirmed to
run outside a real environment with `pip`/`npm`/Docker access. Treat every command here as
"this is what should work," not "this has been proven to work," until someone actually runs it
(see `docs/runbook.md` for the full first-run sequence and known rough edges).

```bash
# The only test suite that has actually executed, repeatedly, this entire build:
cd backend
PYTHONPATH=. python3 -m unittest discover -s tests_pure -v

# The DB-dependent suite - written, never executed (no Postgres/pytest install available so far):
pytest tests/ -v

# RLS-specific integration suite (needs Docker - testcontainers spins up its own Postgres):
pytest tests/test_rls_integration.py -v

# Full local stack:
docker compose up -d postgres redis minio
cd backend && alembic upgrade head && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

## §2.1 — Pure-logic separation is load-bearing here, not optional style

Every calculation module under `backend/app/analytics/` (and the safety-critical guardrail
modules under `backend/app/ai/` and `backend/app/matching/`) must:

- Import nothing from `sqlalchemy`, `fastapi`, `pydantic`, or any DB/web framework.
- Take plain Python types (`Decimal`, `date`, `dataclass`es, `str`, `dict`) as input and return
  plain Python types — never an ORM model, never a request/response schema.
- Be callable and testable from `backend/tests_pure/` with zero setup beyond stdlib and (where
  genuinely needed) `openpyxl`.

This isn't a style preference — it's the reason 156 tests in this repo have actually run and
caught real bugs (a nonexistent ORM relationship, a token-overlap scoring flaw, a synthetic-data
collision) in an environment that can't run the DB layer at all. Every phase this session that
kept this boundary clean got real verification; nothing that crossed it did.

**Concretely:** if you're adding a calculation, ask "could I unit-test this with `unittest`, no
`pytest`, no DB, no FastAPI, right now?" If the answer is no, the calculation logic and the
DB/route plumbing around it aren't separated yet — separate them before adding the feature, not
after.

## Before considering any change "done"

Per `UNIVERSAL_ENGINEERING_SPEC.md` §7.3: the existing `tests_pure/` suite must still pass in
full, not just "the new test I added." Run the whole discovery command above, not a filtered
subset, before calling anything finished.
