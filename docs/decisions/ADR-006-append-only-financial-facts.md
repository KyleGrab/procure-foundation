# ADR-006: Financial fact tables are append-only

**Status:** Accepted

**Context:** Spec section 123 lists financial auditability as priority #3, above maintainability. Section 92
separately asks for careful transaction handling on imports/approvals/deletes, and section 9 allows soft
deletion "where commercially appropriate" without distinguishing master data from financial fact data.

**Decision:** `purchase_invoices`, `purchase_invoice_lines`, `sales_facts` are insert-only after posting. A
correction is a new row with `corrects_id` referencing the original. Master data (suppliers, products,
users, locations) uses normal soft-delete (`deleted_at`).

**Consequences:** Reporting queries need a "latest non-superseded row" view rather than a plain SELECT —
built once as `v_current_invoice_lines` etc. in Phase 3, not repeated inline in every query. In exchange,
every historical number an opportunity/report/audit ever referenced stays exactly reconstructable.
