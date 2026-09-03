from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Contract(Base, TenantScopedMixin):
    """
    Verified contract terms only (spec Section 31) - never written to directly from AI
    extraction. See ContractExtraction below and ADR-004/docs/phase3-contract-lifecycle-plan.md
    §2.1 for why. `status` is a cache of app.analytics.contract_calculations.classify_contract_status
    (ADR-010) - never edited directly, only re-derived.
    """

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)

    contract_number: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    notice_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    renewal_term_months: Mapped[int | None] = mapped_column(Integer)

    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ZAR")

    # See ADR-009: cpi_linked contracts never carry a stored index value here - the value is
    # supplied at calculation time, not persisted as if it were a fixed contract term.
    escalation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    escalation_rate_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))

    # Verified summaries only - free text a human confirmed against the signed document, never
    # raw AI output (spec Section 31's explicit warning).
    rebate_terms_summary: Mapped[str | None] = mapped_column(String(2048))
    sla_terms_summary: Mapped[str | None] = mapped_column(String(2048))
    minimum_spend_commitment: Mapped[float | None] = mapped_column(Numeric(18, 4))

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    status_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_file_storage_key: Mapped[str | None] = mapped_column(String(512))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class ContractExtraction(Base, TenantScopedMixin):
    """
    AI-extraction staging table (ADR-004's pattern, applied here). Nothing calculation-facing
    ever reads extracted_fields directly - promotion to Contract's verified fields is an explicit,
    audited human action (services/contract_service.py:promote_extraction).
    """

    __tablename__ = "contract_extractions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))

    source_file_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    extracted_fields: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {field: {value, confidence}}
    extraction_model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))

    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    verified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContractAlert(Base, TenantScopedMixin):
    """Idempotency record for the alert engine (spec Section 32) - see
    app.analytics.contract_calculations.determine_due_alerts. One row per alert type per
    contract, ever - the engine checks this table before deciding an alert is 'due'."""

    __tablename__ = "contract_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), nullable=False)

    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'expiry_180' etc.
    trigger_date: Mapped[date] = mapped_column(Date, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
