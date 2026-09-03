# tests_pure

Unlike `backend/tests/` (pytest + httpx + a live Postgres, or testcontainers for the RLS suite —
none of which run in this sandbox), everything imported by these tests is pure
Python/`Decimal`/`datetime`/stdlib `re`/`difflib`, plus `openpyxl` (the one third-party package
that genuinely is available offline here, used only by `test_excel_export.py`) — no SQLAlchemy,
no FastAPI, no network. That means these are the tests that actually RUN in this sandboxed
environment, using `python3 -m unittest discover tests_pure`.

152 tests across Phases 2–5: description normalization and pack/unit parsing, the product-matching
pipeline, price-review financial calculations, ingestion (CSV/XLSX reading, column mapping,
validation) for both price-review and purchase-transaction shapes, Excel export, contract
lifecycle calculations (notice periods, renewal dates, status, escalation), the ADR-004
staging→verification→calculation-engine pipeline (using the real production guardrail and
calculation code, not a reimplementation), rebate calculations (expected/leakage/tier progress,
threshold alerts, transaction aggregation), purchase-ledger calculations (Purchase Price
Variance, invoice line net amounts, goods-receipt variance), spend analytics (aggregation, ABC
classification, Pareto contributors, price consistency), the five-savings-type discipline and
waterfall, and the Safe AI Copilot's intent router (the actual safety boundary — tested against
SQL-injection- and prompt-injection-shaped adversarial inputs, no LLM required).

See each phase's plan doc (`docs/phase2-price-review-plan.md`, `docs/phase3-contract-lifecycle-plan.md`,
`docs/phase4-rebate-leakage-plan.md`) for which parts of that phase this covers vs. what's still
syntax-checked-only (DB models, migrations, API routes, service-layer DB I/O).
