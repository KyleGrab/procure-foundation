"""
Orchestrates contract creation, status recomputation, escalation calculation, alert generation,
and the extraction-verification workflow. Same pattern as price_review_service.py: this module
contains no calculation logic of its own - everything financial/date-related is a call into
app.analytics.contract_calculations (genuinely tested - see tests_pure/test_contract_calculations.py).
DB-dependent, syntax-checked only in this sandbox.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract_calculations import (
    EscalationType,
    calculate_escalated_price,
    calculate_next_renewal_date,
    calculate_notice_deadline,
    classify_contract_status,
    determine_due_alerts,
)
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.db.models import Contract, ContractAlert, ContractExtraction, Supplier
from app.schemas.contract import ContractCreate
from app.services import audit_service


async def create_contract(
    db: AsyncSession, *, organisation_id: int, user_id: int, payload: ContractCreate
) -> Contract:
    supplier_result = await db.execute(
        select(Supplier).where(Supplier.public_id == payload.supplier_public_id)
    )
    supplier = supplier_result.scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("Supplier not found")

    contract = Contract(
        organisation_id=organisation_id,
        supplier_id=supplier.id,
        title=payload.title,
        contract_number=payload.contract_number,
        start_date=payload.start_date,
        expiry_date=payload.expiry_date,
        notice_period_days=payload.notice_period_days,
        auto_renew=payload.auto_renew,
        renewal_term_months=payload.renewal_term_months,
        payment_terms_days=payload.payment_terms_days,
        currency=payload.currency,
        escalation_type=payload.escalation_type,
        escalation_rate_pct=payload.escalation_rate_pct,
        rebate_terms_summary=payload.rebate_terms_summary,
        sla_terms_summary=payload.sla_terms_summary,
        minimum_spend_commitment=payload.minimum_spend_commitment,
        created_by_user_id=user_id,
    )
    refresh_status(contract)
    db.add(contract)
    await db.flush()

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="contract_created",
        entity_type="contract", entity_id=str(contract.id),
    )
    await db.commit()
    await db.refresh(contract)
    return contract


def refresh_status(contract: Contract, *, today=None) -> None:
    """See ADR-010: recomputes status from dates rather than trusting whatever's stored. Called
    on every write and should also be called by a scheduled daily job (Phase 9, not built here)
    so status doesn't go stale purely from time passing with no user action."""
    from datetime import date as date_cls

    today = today or date_cls.today()
    deadline = calculate_notice_deadline(contract.expiry_date, contract.notice_period_days)
    status = classify_contract_status(
        today, contract.expiry_date, deadline, auto_renew=contract.auto_renew
    )
    contract.status = status.value
    contract.status_calculated_at = datetime.now(timezone.utc)


def get_derived_fields(contract: Contract) -> dict:
    """notice_deadline / next_renewal_date shown alongside stored fields (ContractRead schema) -
    always computed fresh, never persisted as if they were independent facts."""
    deadline = calculate_notice_deadline(contract.expiry_date, contract.notice_period_days)
    next_renewal = calculate_next_renewal_date(
        contract.expiry_date, auto_renew=contract.auto_renew,
        renewal_term_months=contract.renewal_term_months,
    )
    return {"notice_deadline": deadline, "next_renewal_date": next_renewal}


async def calculate_escalated_price_for_contract(
    db: AsyncSession, *, contract: Contract, base_price: Decimal,
    periods_elapsed: int, external_index_value_pct: Decimal | None,
) -> Decimal:
    """
    See ADR-009. Rejects a supplied external_index_value_pct for anything other than
    cpi_linked contracts, rather than silently ignoring it - if a client sends one, they
    believed it mattered, and silently dropping it would hide that misunderstanding.
    """
    escalation_type = EscalationType(contract.escalation_type)
    if escalation_type != EscalationType.CPI_LINKED and external_index_value_pct is not None:
        raise ValidationFailedError(
            f"external_index_value_pct was supplied but this contract's escalation_type is "
            f"{escalation_type.value!r}, not cpi_linked - it would be silently ignored"
        )
    rate = (
        Decimal(str(contract.escalation_rate_pct))
        if contract.escalation_rate_pct is not None else None
    )
    return calculate_escalated_price(
        base_price, escalation_type,
        escalation_rate_pct=rate,
        external_index_value_pct=external_index_value_pct,
        periods_elapsed=periods_elapsed,
    )


async def run_alert_check(db: AsyncSession, *, organisation_id: int, contract: Contract) -> list[ContractAlert]:
    """Idempotent - see contract_alerts' unique constraint and
    app.analytics.contract_calculations.determine_due_alerts. Intended to be called once per day
    per contract by a scheduled job (Phase 9); calling it more often is safe, just redundant."""
    from datetime import date as date_cls

    today = date_cls.today()
    deadline = calculate_notice_deadline(contract.expiry_date, contract.notice_period_days)

    existing_result = await db.execute(
        select(ContractAlert.alert_type).where(ContractAlert.contract_id == contract.id)
    )
    already_fired = {row[0] for row in existing_result.all()}

    due_types = determine_due_alerts(today, contract.expiry_date, deadline, already_fired)
    new_alerts = [
        ContractAlert(
            organisation_id=organisation_id, contract_id=contract.id,
            alert_type=alert_type, trigger_date=today,
        )
        for alert_type in due_types
    ]
    db.add_all(new_alerts)
    if new_alerts:
        await audit_service.record(
            db, organisation_id=organisation_id, user_id=None, action="contract_alerts_fired",
            entity_type="contract", entity_id=str(contract.id),
            context={"alert_types": due_types},
        )
    await db.commit()
    return new_alerts


async def promote_extraction_fields(
    db: AsyncSession, *, organisation_id: int, user_id: int,
    extraction: ContractExtraction, contract: Contract, field_names: list[str],
) -> Contract:
    """
    The DB-I/O half of ADR-004's promotion flow - all gating logic (verification-status check,
    field allowlist) lives in app.ai.extraction_guardrails.promote_fields_from_extraction, which
    is what actually decides what's allowed through; this function only fetches, applies the
    result, and persists. See tests_pure/test_adr004_staging_pipeline.py for the guardrail logic
    tested directly, without a DB.
    """
    from app.ai.extraction_guardrails import promote_fields_from_extraction

    promotable = promote_fields_from_extraction(
        extraction.extracted_fields, extraction.verification_status, field_names
    )
    for field_name, value in promotable.items():
        setattr(contract, field_name, value)

    refresh_status(contract)
    extraction.verification_status = "human_verified"
    extraction.verified_by_user_id = user_id
    extraction.verified_at = datetime.now(timezone.utc)

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="contract_extraction_promoted",
        entity_type="contract", entity_id=str(contract.id),
        context={"promoted_fields": list(promotable.keys())},
    )
    await db.commit()
    await db.refresh(contract)
    return contract
