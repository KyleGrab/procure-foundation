from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin

MEASURE_CODES = ("expected_amount", "annual_financial_impact", "realised_savings")

_STATUS_VOCAB_BY_MEASURE = {
    "expected_amount": "('unknown','not_applicable','legacy_unverified','estimated','calculated','confirmed')",
    "annual_financial_impact": "('unknown','not_applicable','legacy_unverified','estimated','calculated')",
    "realised_savings": "('unknown','not_applicable','legacy_unverified','calculated','confirmed')",
}


class FinancialAmountStatusEvent(Base, TenantScopedMixin):
    """
    P-03: the authoritative, append-only history of every status/amount/source-basis/provenance
    change for the three governed measures. Current-state rows (RebatePeriodActual.
    expected_amount*, Opportunity.annual_financial_impact*/realised_savings*) are a DERIVED view
    of this table, proven so by a deferred constraint trigger (see migration 0021) - not just a
    convention services are expected to follow.

    Exactly one parent per row (rebate_period_actual_id XOR opportunity_id) - enforced by a CHECK
    constraint at the DB level, not just here. measure_code further restricts which parent type
    is valid: rebate_period_actual_id can only pair with 'expected_amount'; opportunity_id only
    with 'annual_financial_impact' or 'realised_savings'.

    event_version is a PER-PARENT-PER-MEASURE sequence (not the global id) - id alone conflates
    unrelated records' histories; event_version lets "give me events 1,2,3... for this specific
    parent+measure" be queried directly. Concurrency safety (no two transactions computing the
    same version for the same parent+measure) is a service-layer responsibility (SELECT ... FOR
    UPDATE on the parent row before computing next_version), backstopped by the UNIQUE
    constraints below.

    old_*/new_* pairs exist for every field the current-state snapshot can hold, including
    period fields - a period value changing is as real a historical fact as an amount changing.
    change_reference (non-null always - a request ID for human changes, a workflow-run/import-
    batch ID for automated ones) identifies WHAT triggered this; change_reason_code (separate,
    controlled vocabulary) identifies WHY - these are deliberately different questions.
    """

    __tablename__ = "financial_amount_status_events"
    __table_args__ = (
        CheckConstraint(f"measure_code IN {MEASURE_CODES}", name="ck_famev_measure_code"),
        CheckConstraint(
            "(rebate_period_actual_id IS NOT NULL AND opportunity_id IS NULL) OR "
            "(rebate_period_actual_id IS NULL AND opportunity_id IS NOT NULL)",
            name="ck_famev_exactly_one_parent",
        ),
        CheckConstraint(
            "rebate_period_actual_id IS NULL OR measure_code = 'expected_amount'",
            name="ck_famev_rebate_parent_measure",
        ),
        CheckConstraint(
            "opportunity_id IS NULL OR measure_code IN ('annual_financial_impact','realised_savings')",
            name="ck_famev_opportunity_parent_measure",
        ),
        CheckConstraint("event_version > 0", name="ck_famev_version_positive"),
        CheckConstraint(
            "event_version != 1 OR ("
            "old_amount IS NULL AND old_status IS NULL AND old_source_basis IS NULL AND "
            "old_calculated_at IS NULL AND old_approved_at IS NULL AND old_approved_by_user_id IS NULL AND "
            "old_effective_period_start IS NULL AND old_effective_period_end IS NULL)",
            name="ck_famev_genesis_old_fields_null",
        ),
        CheckConstraint(
            "change_reason_code IN ('initial_backfill','manual_estimate','recalculation',"
            "'evidence_received','correction','evidence_withdrawn','source_data_restated')",
            name="ck_famev_reason_code_vocabulary",
        ),
        CheckConstraint(
            "(measure_code = 'expected_amount' AND new_status IN " + _STATUS_VOCAB_BY_MEASURE["expected_amount"] + ") OR "
            "(measure_code = 'annual_financial_impact' AND new_status IN " + _STATUS_VOCAB_BY_MEASURE["annual_financial_impact"] + ") OR "
            "(measure_code = 'realised_savings' AND new_status IN " + _STATUS_VOCAB_BY_MEASURE["realised_savings"] + ")",
            name="ck_famev_status_valid_for_measure",
        ),
        UniqueConstraint("id", "organisation_id", name="uq_famev_id_org"),
        UniqueConstraint("rebate_period_actual_id", "measure_code", "event_version", name="uq_famev_rebate_seq"),
        UniqueConstraint("opportunity_id", "measure_code", "event_version", name="uq_famev_opportunity_seq"),
        Index("ix_famev_org", "organisation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)

    rebate_period_actual_id: Mapped[int | None] = mapped_column(ForeignKey("rebate_period_actuals.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    measure_code: Mapped[str] = mapped_column(String(32), nullable=False)
    event_version: Mapped[int] = mapped_column(BigInteger, nullable=False)

    old_amount: Mapped[float | None] = mapped_column(Numeric(18, 4))
    new_amount: Mapped[float | None] = mapped_column(Numeric(18, 4))
    old_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    old_source_basis: Mapped[str | None] = mapped_column(String(64))
    new_source_basis: Mapped[str | None] = mapped_column(String(64))
    old_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    old_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    old_approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    new_approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    old_effective_period_start: Mapped[date | None] = mapped_column(Date)
    new_effective_period_start: Mapped[date | None] = mapped_column(Date)
    old_effective_period_end: Mapped[date | None] = mapped_column(Date)
    new_effective_period_end: Mapped[date | None] = mapped_column(Date)

    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    change_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    change_reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    change_note: Mapped[str | None] = mapped_column(String)


class FinancialAmountEvidence(Base, TenantScopedMixin):
    """
    P-03: child of FinancialAmountStatusEvent - multiple rows may attach to one event (a
    'reconciled_actuals' confirmation needs a documented_baseline, an actual_cost_source, AND a
    variance_calculation_reference - three separate typed rows, not one string). Tenant integrity
    with the parent event is enforced by a composite FK (event_id, organisation_id) referencing
    the event table's own (id, organisation_id) unique constraint - not merely RLS - so a row
    cannot be attached to another tenant's event even by a bug that bypasses RLS.
    """

    __tablename__ = "financial_amount_evidence"
    __table_args__ = (
        CheckConstraint(
            "evidence_type IN ('invoice','credit_note','supplier_statement','gl_posting',"
            "'documented_baseline','actual_cost_source','variance_calculation_reference','supporting_document')",
            name="ck_famev_evid_type_vocabulary",
        ),
        ForeignKeyConstraint(
            ["event_id", "organisation_id"],
            ["financial_amount_status_events.id", "financial_amount_status_events.organisation_id"],
            name="fk_famev_evid_event_tenant_matched",
        ),
        Index("ix_famev_evid_org", "organisation_id"),
        Index("ix_famev_evid_event", "event_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)

    event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(48), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    document_date: Mapped[date | None] = mapped_column(Date)
    effective_period: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    document_storage_key: Mapped[str | None] = mapped_column(String(255))
