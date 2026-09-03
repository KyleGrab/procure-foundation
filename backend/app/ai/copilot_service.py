"""
Wires the pure IntentRouter (app/ai/intent_router.py, tested without a DB or LLM) to real,
DB-dependent handlers, and orchestrates the full pipeline from docs/architecture.md §1:
NL question -> LLM classification (constrained to the fixed Intent enum) -> router validates and
dispatches -> deterministic handler -> structured result -> LLM turns it into prose.

Never executed in this sandbox (no network, no LLM_API_KEY) - same honesty pattern as every
AI-touching module since Phase 2's negotiation brief. The permission check before a handler runs
uses the same ROLE_PERMISSIONS table require_permission (app/core/permissions.py) checks against
FastAPI's Depends system - reimplemented as a plain function call here since this runs inside a
service function, not a route parameter, but it is the same table, not a second one that could
drift from the real RBAC rules.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent_router import Intent, IntentRouter
from app.ai.llm_provider import LLMProvider
from app.ai.schemas import IntentClassificationOutput
from app.core.constants import ROLE_PERMISSIONS, Permission, Role
from app.core.exceptions import PermissionDeniedError
from app.db.models import Contract, RebateAgreement, RebatePeriodActual, Supplier
from app.services import spend_analytics_service

_router = IntentRouter()


async def _resolve_supplier_id(db: AsyncSession, organisation_id: int, name: str) -> int | None:
    """Deterministic name->id lookup - the ONLY thing an extracted entity name is ever used for.
    Never interpolated into a query beyond this equality/ILIKE check, never used to build any
    other part of a query."""
    result = await db.execute(
        select(Supplier.id).where(Supplier.organisation_id == organisation_id)
        .where(Supplier.legal_name.ilike(f"%{name}%"))
    )
    return result.scalars().first()


async def _handle_spend_by_supplier(db: AsyncSession, organisation_id: int, entities: dict) -> dict:
    items = await spend_analytics_service.get_spend_by_supplier(db, organisation_id=organisation_id)
    return {"items": [{"supplier": i.label, "amount": str(i.amount)} for i in items[:20]]}


async def _handle_spend_by_sku(db: AsyncSession, organisation_id: int, entities: dict) -> dict:
    supplier_id = None
    if "supplier" in entities:
        supplier_id = await _resolve_supplier_id(db, organisation_id, entities["supplier"])
    items = await spend_analytics_service.get_spend_by_sku(db, organisation_id=organisation_id, supplier_id=supplier_id)
    return {"items": [{"sku": i.label, "amount": str(i.amount)} for i in items[:20]]}


async def _handle_abc_classification(db: AsyncSession, organisation_id: int, entities: dict) -> dict:
    results = await spend_analytics_service.get_abc_classification(db, organisation_id=organisation_id)
    return {
        "classification": [
            {"supplier": r.item.label, "amount": str(r.item.amount), "class": r.classification.value,
             "cumulative_pct": str(r.cumulative_pct)}
            for r in results
        ]
    }


async def _handle_pareto_contributors(db: AsyncSession, organisation_id: int, entities: dict) -> dict:
    result = await spend_analytics_service.get_pareto_contributors(db, organisation_id=organisation_id)
    return {
        "contributor_count": result.contributor_count, "total_item_count": result.total_item_count,
        "cumulative_pct_covered": str(result.cumulative_pct_covered),
        "contributors": [{"supplier": c.label, "amount": str(c.amount)} for c in result.contributors],
    }


async def _handle_price_variance_check(db: AsyncSession, organisation_id: int, entities: dict) -> dict:
    if "supplier" not in entities or "sku" not in entities:
        return {"error": "Both a supplier and an item are needed to check price consistency"}
    supplier_id = await _resolve_supplier_id(db, organisation_id, entities["supplier"])
    if supplier_id is None:
        return {"error": f"No supplier found matching {entities['supplier']!r}"}
    result = await spend_analytics_service.check_price_consistency(
        db, organisation_id=organisation_id, supplier_id=supplier_id, sku_or_description=entities["sku"],
    )
    return {
        "min_price": str(result.min_price), "max_price": str(result.max_price),
        "spread": str(result.spread), "spread_pct": str(result.spread_pct) if result.spread_pct else None,
        "is_significant": result.is_significant, "observation_count": result.observation_count,
    }


async def _handle_rebate_status(db: AsyncSession, organisation_id: int, entities: dict) -> dict:
    if "supplier" not in entities:
        return {"error": "A supplier name is needed to check rebate status"}
    supplier_id = await _resolve_supplier_id(db, organisation_id, entities["supplier"])
    if supplier_id is None:
        return {"error": f"No supplier found matching {entities['supplier']!r}"}
    result = await db.execute(
        select(RebatePeriodActual, RebateAgreement.title)
        .join(RebateAgreement, RebateAgreement.id == RebatePeriodActual.rebate_agreement_id)
        .where(RebateAgreement.supplier_id == supplier_id)
        .where(RebatePeriodActual.earned_amount.is_(None))
    )
    return {
        "open_periods": [
            {"agreement": title, "expected_amount": str(p.expected_amount) if p.expected_amount else None,
             "status": p.status}
            for p, title in result.all()
        ]
    }


async def _handle_contract_expiry_check(db: AsyncSession, organisation_id: int, entities: dict) -> dict:
    result = await db.execute(
        select(Contract, Supplier.legal_name)
        .join(Supplier, Supplier.id == Contract.supplier_id)
        .where(Contract.organisation_id == organisation_id)
        .where(Contract.status.in_(("expiring_soon", "notice_period_open")))
    )
    return {
        "expiring_contracts": [
            {"supplier": name, "title": c.title, "expiry_date": c.expiry_date.isoformat(), "status": c.status}
            for c, name in result.all()
        ]
    }


_router.register(
    Intent.SPEND_BY_SUPPLIER, required_permission=Permission.VIEW_FINANCIALS,
    handler=_handle_spend_by_supplier, description="Total spend grouped by supplier",
)
_router.register(
    Intent.SPEND_BY_SKU, required_permission=Permission.VIEW_FINANCIALS,
    handler=_handle_spend_by_sku, description="Total spend grouped by product/SKU, optionally filtered by supplier",
)
_router.register(
    Intent.ABC_CLASSIFICATION, required_permission=Permission.VIEW_FINANCIALS,
    handler=_handle_abc_classification, description="ABC classification of suppliers by cumulative spend",
)
_router.register(
    Intent.PARETO_CONTRIBUTORS, required_permission=Permission.VIEW_FINANCIALS,
    handler=_handle_pareto_contributors, description="Minimum suppliers accounting for 80% of spend",
)
_router.register(
    Intent.PRICE_VARIANCE_CHECK, required_permission=Permission.VIEW_FINANCIALS,
    handler=_handle_price_variance_check,
    description="Whether a specific item has been purchased at inconsistent prices from one supplier",
)
_router.register(
    Intent.REBATE_STATUS, required_permission=Permission.VIEW_FINANCIALS,
    handler=_handle_rebate_status, description="Open rebate periods and expected amounts for a supplier",
)
_router.register(
    Intent.CONTRACT_EXPIRY_CHECK, required_permission=Permission.VIEW_CONTRACTS,
    handler=_handle_contract_expiry_check, description="Contracts expiring soon or in their notice period",
)


_CLASSIFICATION_PROMPT_TEMPLATE = """You are classifying a procurement question into exactly one \
of the following pre-approved intents - never anything else. If the question doesn't clearly \
match one of these, classify it as "unsupported".

Available intents:
{intents_json}

Extract any entity values mentioned (e.g. a supplier name, a SKU/product name) as plain text - \
never as an ID, and never attempt to write any part of a database query.

Question: {question}"""


def _check_permission(role: str, required_permission: Permission) -> None:
    if required_permission not in ROLE_PERMISSIONS.get(Role(role), frozenset()):
        raise PermissionDeniedError(
            f"Role {role!r} does not have permission {required_permission.value!r} for this query"
        )


async def answer_query(
    db: AsyncSession, provider: LLMProvider, *, organisation_id: int, role: str, question: str,
) -> dict:
    """The full pipeline. Raises UnsupportedIntentError (via router.resolve_classification) for
    anything outside the fixed intent set, and PermissionDeniedError if the caller's role can't
    use the classified intent - both before any handler runs."""
    classification = await provider.complete_structured(
        system="Procurement copilot intent classifier.",
        prompt=_CLASSIFICATION_PROMPT_TEMPLATE.format(
            intents_json=json.dumps(_router.available_intents_for_prompt()), question=question,
        ),
        output_model=IntentClassificationOutput,
    )

    intent = _router.resolve_classification(classification.intent)
    entry = _router.get_entry(intent)
    _check_permission(role, entry.required_permission)

    structured_result = await entry.handler(db, organisation_id, classification.entities)

    summary = await provider.complete(
        system=(
            "You are summarising procurement data for a manager. Use ONLY the structured data "
            "given to you - never invent or estimate a figure not present in it."
        ),
        prompt=f"Question: {question}\n\nData: {json.dumps(structured_result)}\n\nWrite a concise summary.",
    )

    return {"intent": intent.value, "structured_result": structured_result, "summary": summary}
