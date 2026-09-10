"""
Assembles a strictly verified structured payload and calls LLMProvider (spec Section 26). Never
executed in this sandbox (no network, no LLM_API_KEY) - written and syntax-checked so the
guardrail shape is reviewable: notice every field in either context builder below traces back to
a value produced by proven calculation functions (app.analytics.price_review_calculations or
app.analytics.spend_analytics), never a value invented at this layer.
Uses complete_structured (app/ai/llm_provider.py) with NegotiationBriefOutput
(app/ai/schemas.py) so a malformed model response fails loudly rather than being coerced into a
half-filled brief.

Two context builders, one generator (ADR-016): build_negotiation_brief_context() sources from a
price review (Phase 2's original route), build_negotiation_brief_context_from_spend() sources
from spend analytics + contract/rebate data (Phase 5's general-purpose route). Both produce the
same NegotiationBriefContext shape and both call the same generate_brief() - adding a third
source later means one more builder function, not a third prompt/schema/generator to keep in sync.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm_provider import LLMProvider
from app.ai.schemas import NegotiationBriefOutput
from app.analytics.spend_analytics import SpendItem
from app.db.models import Contract, PriceReviewLine, Supplier
from app.services import spend_analytics_service

_PROMPT_TEMPLATE_PATH = "app/ai/prompts/negotiation_brief.md"


@dataclass(frozen=True)
class NegotiationBriefContext:
    supplier_name: str
    annual_spend: Decimal
    weighted_increase_pct: Decimal | None
    total_annual_impact: Decimal
    top_sku_impacts: list[tuple[str, Decimal]]
    negotiation_targets: list[tuple[str, Decimal]]
    supplier_performance_note: str


def build_negotiation_brief_context(
    supplier: Supplier, lines: list[PriceReviewLine], weighted_increase_pct: Decimal | None,
) -> NegotiationBriefContext:
    impacted = [l for l in lines if l.annual_impact is not None]
    annual_spend = sum((Decimal(str(l.annual_impact)) for l in impacted), Decimal(0))
    top_impacts = sorted(impacted, key=lambda l: -abs(Decimal(str(l.annual_impact))))[:10]
    targeted = [l for l in lines if l.target_price is not None]

    return NegotiationBriefContext(
        supplier_name=supplier.legal_name,
        annual_spend=annual_spend,
        weighted_increase_pct=weighted_increase_pct,
        total_annual_impact=annual_spend,
        top_sku_impacts=[
            (l.new_description or l.old_description or "Unknown", Decimal(str(l.annual_impact)))
            for l in top_impacts
        ],
        negotiation_targets=[
            (l.new_description or l.old_description or "Unknown", Decimal(str(l.target_price)))
            for l in targeted
        ],
        # Supplier performance (spec Section 26's "where available") is Phase 5+ scope (supplier
        # scorecards) - explicitly absent here rather than fabricated, per the prompt's own
        # instruction to say so when data is missing.
        supplier_performance_note="not available in this phase",
    )


async def build_negotiation_brief_context_from_spend(
    db: AsyncSession, *, organisation_id: int, supplier: Supplier,
) -> NegotiationBriefContext:
    """
    ADR-016: same output shape as build_negotiation_brief_context above, sourced from spend
    analytics + contracts instead of a price review. No weighted_increase_pct exists outside a
    price review's line-level movements, so it's None here - the prompt template already treats
    a None value as "not available," never fabricating one. Price variance findings (spec §26's
    "supplier performance where available") are folded into supplier_performance_note as text
    rather than adding a new field to NegotiationBriefContext - that dataclass is shared with the
    price-review-sourced builder (ADR-016), and adding a field only one builder populates would
    mean either a silent gap in the other builder's output or a schema change touching both.
    """
    items = await spend_analytics_service.get_spend_by_sku(
        db, organisation_id=organisation_id, supplier_id=supplier.id
    )
    top_items: list[SpendItem] = items[:10]
    annual_spend = sum((i.amount for i in items), Decimal(0))

    contract_result = await db.execute(
        select(Contract.rebate_terms_summary, Contract.sla_terms_summary)
        .where(Contract.supplier_id == supplier.id)
        .where(Contract.organisation_id == organisation_id)
    )
    contract_row = contract_result.first()
    performance_notes = [
        f"Contract terms on file: {contract_row[1] or 'no SLA summary recorded'}"
        if contract_row else "no contract on file for this supplier"
    ]

    # Price variance (spec §23) for the top few items - only items with more than one price
    # observation produce a meaningful consistency check, so failures here are skipped rather
    # than surfaced as noise (a single-observation item has nothing to compare against, per
    # calculate_price_consistency's own design - not an error condition to report).
    for item in top_items[:5]:
        try:
            variance = await spend_analytics_service.check_price_consistency(
                db, organisation_id=organisation_id, supplier_id=supplier.id, sku_or_description=item.key,
            )
        except ValueError:
            continue
        if variance.is_significant:
            performance_notes.append(
                f"{item.label}: price paid ranged from R{variance.min_price} to R{variance.max_price} "
                f"({variance.spread_pct:.1%} spread) across {variance.observation_count} purchases"
                if variance.spread_pct is not None else
                f"{item.label}: price spread of R{variance.spread} across {variance.observation_count} purchases"
            )

    return NegotiationBriefContext(
        supplier_name=supplier.legal_name,
        annual_spend=annual_spend,
        weighted_increase_pct=None,  # not derivable outside a price review - see docstring above
        total_annual_impact=annual_spend,
        top_sku_impacts=[(i.label, i.amount) for i in top_items],
        negotiation_targets=[],  # spend analytics has no per-line negotiation target concept
        supplier_performance_note=" | ".join(performance_notes),
    )


async def generate_brief(provider: LLMProvider, context: NegotiationBriefContext) -> NegotiationBriefOutput:
    with open(_PROMPT_TEMPLATE_PATH) as f:
        template = f.read()

    prompt = template.format(
        supplier_name=context.supplier_name,
        annual_spend=context.annual_spend,
        weighted_increase_pct=context.weighted_increase_pct,
        total_annual_impact=context.total_annual_impact,
        top_sku_impacts=", ".join(f"{desc}: R{impact}" for desc, impact in context.top_sku_impacts),
        negotiation_targets=", ".join(f"{desc}: R{price}" for desc, price in context.negotiation_targets),
        supplier_performance_or_none=context.supplier_performance_note,
    )
    return await provider.complete_structured(
        system="Procurement negotiation preparation assistant.",
        prompt=prompt,
        output_model=NegotiationBriefOutput,
    )
