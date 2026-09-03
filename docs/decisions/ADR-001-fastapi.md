# ADR-001: FastAPI + async SQLAlchemy 2.x for the backend

**Status:** Accepted

**Context:** Need a Python backend that handles high-concurrency I/O (imports, AI calls, file uploads)
without blocking, with strong typing for financial-data correctness.

**Decision:** FastAPI + Pydantic v2 for request/response validation, SQLAlchemy 2.x async ORM, asyncpg
driver. Sync fallback only for Alembic migrations (which don't need async).

**Consequences:** Every DB-touching function in services/ is async; background workers (Celery, Phase 3+)
use a separate sync session since Celery's worker model doesn't play well with asyncio event loops without
extra plumbing that isn't worth it at this scale.
