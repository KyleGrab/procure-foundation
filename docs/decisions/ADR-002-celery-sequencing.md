# ADR-002: Defer Celery to Phase 3, not Phase 1

**Status:** Accepted (deviates from spec's "prefer Celery from the start")

**Context:** Spec section 5 asks for Celery+Redis as the default background job system. Phase 1–2 workload
(auth, master data CRUD, small import files) doesn't need retries, task routing, or worker pool tuning.

**Decision:** Phase 1–2 uses FastAPI BackgroundTasks + a `job_status` table in Postgres for anything
long-running enough to need a status the frontend can poll. Celery is introduced in Phase 3 when import
volume and product-matching workload actually justify the operational cost of running and monitoring a
worker fleet.

**Consequences:** Phase 3 requires a real migration of the job-status pattern to Celery task signatures —
budgeted explicitly in the Phase 3 plan, not a surprise.
