from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class CostAllocationRule(Base, TenantScopedMixin):
    """
    Tenant configuration - a rule someone sets and edits, not a fact that happened. Mutable,
    following organisation_settings' established pattern in this codebase rather than ADR-006's
    append-only fact-table pattern, which doesn't fit a config row (see class docstrings below
    for the tables that DO fit ADR-006).

    Extended (Phase 1 deep-dive, grounded in Gourmet_Foods_Cost_to_Serve_July2026.xlsx's real
    30_TRUCK_PROFITABILITY data) after that data proved a real, quantified R288,373/month
    cross-subsidy across a real 17-truck fleet, produced by exactly the two gaps below.
    """

    __tablename__ = "cost_allocation_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    cost_category: Mapped[str] = mapped_column(String(64), nullable=False)
    # 'warehouse_picking' | 'receiving' | 'outbound_logistics' | 'overhead' - open-ended on
    # purpose (a tenant's real cost categories vary by industry); not an Enum for that reason.
    allocation_method: Mapped[str] = mapped_column(String(32), nullable=False)
    # Matches app.analytics.management_accounting.AllocationLevel's values exactly
    # ('direct'|'activity_rate'|'volumetric') - 'unallocated' is never a configured rule, only a
    # calculated outcome when no rule applies, so it's not a valid value here.
    default_unit_rate: Mapped[float | None] = mapped_column(Numeric(18, 4))

    allocation_basis: Mapped[str | None] = mapped_column(String(32))
    # 'weight' | 'distance' | 'trips' | 'volume' | 'time' - what default_unit_rate is actually
    # per-unit-of. Nullable: a DIRECT allocation_method has no basis (it's a known actual cost,
    # not a rate), so this is only meaningful alongside activity_rate/volumetric.

    is_fallback_rate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Chaos Audit Domain 1: was `default=False`, matching this column's original DB-level
    # server_default=sa.false() (migration 0015) - both defaults meant a row nobody ever
    # explicitly classified silently read as "matched, high confidence," the exact opposite of
    # what this column exists to make visible. Both defaults removed (migration 0017) - every
    # INSERT must now state a real value.
    # The real, load-bearing distinction this whole extension exists for - mirrors
    # 30_TRUCK_PROFITABILITY's own green/amber/grey: False = a rate matched against this
    # specific entity's real cost; True = an averaged stand-in applied because no matched real
    # cost was available. That "amber" fallback rate, applied uniformly regardless of each
    # truck's real weight, is the exact mechanism that produced the R288,373/month distortion.
    matched_entity_reference: Mapped[str | None] = mapped_column(String(128))
    # When is_fallback_rate is False, which specific real-world entity (a vehicle registration,
    # an invoice, a GL line) this rate was actually verified against - an audit trail, not a
    # calculated field.

    rate_effective_date: Mapped[date | None] = mapped_column(Date)
    rate_source: Mapped[str | None] = mapped_column(String(32))
    # 'manual' | 'indexed' | 'contractual' - manual rates are the ones a fuel/cost shock can
    # silently leave stale; see app.analytics.management_accounting.is_rate_stale.

    temperature_zone: Mapped[str | None] = mapped_column(String(16))
    # 'chilled' | 'frozen' | 'ambient' - nullable/open-ended, not an Enum: not every tenant is
    # multi-temperature. Grounded in real evidence this one is - Gourmet's own real stock master
    # (02_STOCK_MASTER, Gourmet_Foods_Cost_to_Serve_July2026.xlsx) has genuine FROZEN-P,
    # FROZEN-B, FROZEN-G, and DAIRY product classes alongside ambient lines.

    set_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class CostToServeLedger(Base, TenantScopedMixin):
    """
    Append-only (ADR-006) - a per-invoice cost-to-serve calculation is a fact about what was
    computed for that invoice, same category as purchase_transactions/purchase_invoices. A
    correction is a new row referencing corrects_id, never a mutated figure.
    """

    __tablename__ = "cost_to_serve_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    invoice_id: Mapped[str | None] = mapped_column(String(128))
    order_id: Mapped[str | None] = mapped_column(String(128))
    customer_id: Mapped[str | None] = mapped_column(String(128))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))

    net_revenue: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    cogs: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    direct_logistics_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    allocated_warehouse_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    allocated_overhead_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    net_margin: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    net_margin_pct: Mapped[float | None] = mapped_column(Numeric(9, 4))  # nullable - None when
    # net_revenue was zero (calculate_customer_net_margin's own documented behavior, never a
    # fabricated 0%)

    allocation_level: Mapped[str] = mapped_column(String(16), nullable=False)
    # String, not Integer(1,2,3) as originally specified - AllocationLevel
    # (app.analytics.management_accounting) has FOUR values including 'unallocated', which has
    # no slot in a 1-3 integer scheme. Storing the enum's real string value directly also means
    # this column can never silently drift from the pure engine's actual vocabulary the way an
    # integer mapping maintained separately could.

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("cost_to_serve_ledger.id"))
    source_file_storage_key: Mapped[str | None] = mapped_column(String(512))
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class WorkingCapitalSnapshot(Base, TenantScopedMixin):
    """Append-only (ADR-006) - a periodic fact-in-time, same category as inventory_snapshots."""

    __tablename__ = "working_capital_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    accounts_receivable: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    accounts_payable: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    inventory_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    cash_balance: Mapped[float | None] = mapped_column(Numeric(18, 4))  # nullable - see
    # calculate_working_capital_metrics: working_capital_ratio is None when cash isn't supplied,
    # never assumed zero
    annualized_revenue: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    annualized_cogs: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)

    # dso/dio/dpo/ccc/working_capital_ratio are STORED, computed once at ingestion time via the
    # pure engine, not recomputed on every read - same "the number that was actually used is
    # what's stored" principle as PurchaseInvoiceLine.net_amount (Phase 4c). All nullable,
    # matching the pure functions' own None-on-undefined behavior.
    dso: Mapped[float | None] = mapped_column(Numeric(9, 1))
    dio: Mapped[float | None] = mapped_column(Numeric(9, 1))
    dpo: Mapped[float | None] = mapped_column(Numeric(9, 1))
    ccc: Mapped[float | None] = mapped_column(Numeric(9, 1))
    working_capital_ratio: Mapped[float | None] = mapped_column(Numeric(9, 2))

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("working_capital_snapshots.id"))
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class AgingLedgerSnapshot(Base, TenantScopedMixin):
    """Append-only (ADR-006) - a periodic debtors/creditors aging fact-in-time."""

    __tablename__ = "aging_ledger_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    ledger_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'debtors' | 'creditors'

    current_balance: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    days_30: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    days_60: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    days_90: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    days_120_plus: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("aging_ledger_snapshots.id"))
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
