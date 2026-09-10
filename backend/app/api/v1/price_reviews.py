"""
Price review API surface (spec Sections 1, 3, 10, 22-26, 29). Thin routes - all logic lives in
services/price_review_service.py; routes only handle request/response shaping and permission
checks (docs/architecture.md's rule that business logic never lives in route handlers).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.price_review_calculations import PriceReviewMatchStatus
from app.core.constants import Permission
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import PriceReview, PriceReviewFile, PriceReviewLine, PriceReviewMappingTemplate
from app.db.session import get_db
from app.ingestion.csv_reader import read_csv_rows
from app.ingestion.excel_reader import read_xlsx_rows
from app.ingestion.mapping import apply_mapping, suggest_mapping
from app.ingestion.validation import summarize_issues, validate_rows
from app.integrations.object_storage import get_storage
from app.reporting.price_review_excel_export import ExportLine, ExportSummary, export_price_review
from app.schemas.price_review import (
    BuyerDecisionUpdate,
    ColumnMappingConfirm,
    ManualQuantityUpdate,
    MatchDecision,
    NegotiationOutcomeUpdate,
    NegotiationTargetUpdate,
    PriceReviewCreate,
    PriceReviewLineRead,
    PriceReviewRead,
    SupplierSummaryRead,
)
from app.services import audit_service, price_review_service

router = APIRouter(prefix="/price-reviews", tags=["price-reviews"])


async def _get_review(db: AsyncSession, public_id: str) -> PriceReview:
    result = await db.execute(select(PriceReview).where(PriceReview.public_id == public_id))
    review = result.scalar_one_or_none()
    if review is None:
        raise NotFoundError("Price review not found")
    return review


async def _get_line(db: AsyncSession, review_id: int, line_public_id: str) -> PriceReviewLine:
    result = await db.execute(
        select(PriceReviewLine)
        .where(PriceReviewLine.public_id == line_public_id)
        .where(PriceReviewLine.price_review_id == review_id)
    )
    line = result.scalar_one_or_none()
    if line is None:
        raise NotFoundError("Price review line not found")
    return line


@router.post("", response_model=PriceReviewRead, status_code=201)
async def create_price_review(
    payload: PriceReviewCreate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> PriceReviewRead:
    review = await price_review_service.create_review(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    return PriceReviewRead.model_validate(review)


@router.get("/{review_public_id}", response_model=PriceReviewRead)
async def get_price_review(
    review_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> PriceReviewRead:
    review = await _get_review(db, review_public_id)
    return PriceReviewRead.model_validate(review)


@router.post("/{review_public_id}/files/{file_type}", status_code=201)
async def upload_price_list_file(
    review_public_id: str,
    file_type: str,  # 'previous' | 'new'
    file: UploadFile,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if file_type not in ("previous", "new"):
        raise ValidationFailedError("file_type must be 'previous' or 'new'")

    review = await _get_review(db, review_public_id)
    file_bytes = await file.read()
    extension = Path(file.filename or "upload.xlsx").suffix.lstrip(".") or "xlsx"

    storage_key = await get_storage().put(claims.active_org_id, file_bytes, extension)
    record = await price_review_service.register_uploaded_file(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, review_id=review.id,
        file_type=file_type, original_filename=file.filename or "upload", storage_key=storage_key,
        file_bytes=file_bytes,
    )

    # Column-mapping suggestion returned immediately (spec Section 3) - the user confirms via
    # POST .../mapping before any row is committed as a PriceReviewLine.
    if extension.lower() == "csv":
        rows = read_csv_rows(file_bytes.decode("utf-8"))
    else:
        raw_bytes_path = Path(f"/tmp/{storage_key.split('/')[-1]}")
        raw_bytes_path.write_bytes(file_bytes)
        rows = read_xlsx_rows(raw_bytes_path)

    suggested_mapping = suggest_mapping(list(rows[0].keys())) if rows else {}
    return {
        "file_public_id": str(record.public_id),
        "row_count": len(rows),
        "suggested_mapping": suggested_mapping,
        "source_columns": list(rows[0].keys()) if rows else [],
    }


@router.post("/{review_public_id}/mapping", status_code=200)
async def confirm_column_mapping(
    review_public_id: str,
    payload: ColumnMappingConfirm,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Confirms a user-reviewed mapping (spec Section 3's requirement that ambiguous mappings are
    always confirmed, never auto-applied). Re-reads the stored file via object storage, applies
    the confirmed mapping, and runs validation (spec Section 4) - returning errors/warnings for
    the user to act on. Mapped+validated rows are staged on the file record (migration 0007) so
    /match can read both files' staged data without re-parsing, mirroring ContractExtraction's
    staging shape (ADR-004) applied to file parsing instead of AI extraction.
    """
    review = await _get_review(db, review_public_id)
    file_result = await db.execute(
        select(PriceReviewFile)
        .where(PriceReviewFile.public_id == payload.file_public_id)
        .where(PriceReviewFile.price_review_id == review.id)
    )
    file_record = file_result.scalar_one_or_none()
    if file_record is None:
        raise NotFoundError("Price review file not found")

    file_bytes = await get_storage().get(file_record.storage_key)
    extension = file_record.storage_key.rsplit(".", 1)[-1].lower()
    if extension == "csv":
        raw_rows = read_csv_rows(file_bytes.decode("utf-8"))
    else:
        tmp_path = Path(f"/tmp/{file_record.storage_key.split('/')[-1]}")
        tmp_path.write_bytes(file_bytes)
        raw_rows = read_xlsx_rows(tmp_path)

    mapped_rows = [apply_mapping(r, payload.column_mapping) for r in raw_rows]
    validated = validate_rows(mapped_rows)
    issue_summary = summarize_issues(validated)

    file_record.column_mapping = payload.column_mapping
    file_record.staged_rows = [mapped_rows[i] for i, v in enumerate(validated) if v.is_valid]
    file_record.row_count = len(raw_rows)
    file_record.processing_status = "validated"

    if payload.save_as_template_name:
        db.add(PriceReviewMappingTemplate(
            organisation_id=claims.active_org_id, supplier_id=review.supplier_id,
            name=payload.save_as_template_name, column_mapping=payload.column_mapping,
            created_by_user_id=claims.user_id,
        ))

    await audit_service.record(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id,
        action="price_review_mapping_confirmed", entity_type="price_review_file",
        entity_id=str(file_record.id), context={"valid_rows": len(file_record.staged_rows)},
    )
    await db.commit()

    return {"status": "mapping_confirmed", "next_step": "validate_and_match", **issue_summary}


@router.post("/{review_public_id}/match", status_code=200)
async def run_product_matching(
    review_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Reads both files' staged_rows (populated by confirm_column_mapping above) and runs the
    proven matching pipeline (app.matching.scorer - tested in tests_pure/test_matching.py,
    exercised end-to-end in scripts/demo_price_review.py) via
    price_review_service.run_matching, persisting one PriceReviewLine per old-list item plus
    each unmatched new-list item.
    """
    review = await _get_review(db, review_public_id)
    files_result = await db.execute(
        select(PriceReviewFile).where(PriceReviewFile.price_review_id == review.id)
    )
    files = {f.file_type: f for f in files_result.scalars().all()}
    if "previous" not in files or "new" not in files:
        raise ValidationFailedError("Both 'previous' and 'new' price list files must be uploaded")
    if files["previous"].staged_rows is None or files["new"].staged_rows is None:
        raise ValidationFailedError("Both files must have a confirmed column mapping before matching")

    lines = await price_review_service.run_matching(
        db, organisation_id=claims.active_org_id, review_id=review.id,
        old_rows=files["previous"].staged_rows, new_rows=files["new"].staged_rows,
    )
    review.status = "review_required" if any(l.match_status == PriceReviewMatchStatus.REVIEW_REQUIRED.value for l in lines) else "analysing"
    await audit_service.record(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id,
        action="price_review_matching_run", entity_type="price_review", entity_id=str(review.id),
        context={"line_count": len(lines)},
    )
    await db.commit()
    return {"status": review.status, "line_count": len(lines)}


@router.get("/{review_public_id}/lines", response_model=list[PriceReviewLineRead])
async def list_price_review_lines(
    review_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[PriceReviewLineRead]:
    review = await _get_review(db, review_public_id)
    result = await db.execute(
        select(PriceReviewLine).where(PriceReviewLine.price_review_id == review.id)
    )
    return [PriceReviewLineRead.model_validate(l) for l in result.scalars().all()]


@router.post("/{review_public_id}/lines/{line_public_id}/match-decision", response_model=PriceReviewLineRead)
async def resolve_match_decision(
    review_public_id: str, line_public_id: str, payload: MatchDecision,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> PriceReviewLineRead:
    review = await _get_review(db, review_public_id)
    line = await _get_line(db, review.id, line_public_id)
    candidate_line = None
    if payload.action == "choose_different" and payload.chosen_new_line_public_id:
        candidate_line = await _get_line(db, review.id, str(payload.chosen_new_line_public_id))
    updated = await price_review_service.resolve_match(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, line=line,
        decision=payload, candidate_line=candidate_line,
    )
    return PriceReviewLineRead.model_validate(updated)


@router.post("/{review_public_id}/lines/{line_public_id}/quantity", response_model=PriceReviewLineRead)
async def set_line_manual_quantity(
    review_public_id: str, line_public_id: str, payload: ManualQuantityUpdate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> PriceReviewLineRead:
    review = await _get_review(db, review_public_id)
    line = await _get_line(db, review.id, line_public_id)
    updated = await price_review_service.set_manual_quantity(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, line=line, payload=payload
    )
    return PriceReviewLineRead.model_validate(updated)


@router.post("/{review_public_id}/lines/{line_public_id}/decision", response_model=PriceReviewLineRead)
async def set_line_buyer_decision(
    review_public_id: str, line_public_id: str, payload: BuyerDecisionUpdate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_PRICE_INCREASES)),
    db: AsyncSession = Depends(get_db),
) -> PriceReviewLineRead:
    review = await _get_review(db, review_public_id)
    line = await _get_line(db, review.id, line_public_id)
    updated = await price_review_service.set_buyer_decision(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, line=line, payload=payload
    )
    return PriceReviewLineRead.model_validate(updated)


@router.post("/{review_public_id}/lines/{line_public_id}/negotiation-target", response_model=PriceReviewLineRead)
async def set_line_negotiation_target(
    review_public_id: str, line_public_id: str, payload: NegotiationTargetUpdate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_PRICE_INCREASES)),
    db: AsyncSession = Depends(get_db),
) -> PriceReviewLineRead:
    review = await _get_review(db, review_public_id)
    line = await _get_line(db, review.id, line_public_id)
    updated = await price_review_service.set_negotiation_target(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, line=line, payload=payload
    )
    return PriceReviewLineRead.model_validate(updated)


@router.post("/{review_public_id}/lines/{line_public_id}/negotiation-outcome", response_model=PriceReviewLineRead)
async def record_line_negotiation_outcome(
    review_public_id: str, line_public_id: str, payload: NegotiationOutcomeUpdate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_PRICE_INCREASES)),
    db: AsyncSession = Depends(get_db),
) -> PriceReviewLineRead:
    review = await _get_review(db, review_public_id)
    line = await _get_line(db, review.id, line_public_id)
    updated = await price_review_service.record_negotiation_outcome(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, line=line, payload=payload
    )
    return PriceReviewLineRead.model_validate(updated)


@router.post("/{review_public_id}/lines/{line_public_id}/opportunity", status_code=201)
async def create_opportunity_from_line(
    review_public_id: str, line_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_OPPORTUNITIES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    review = await _get_review(db, review_public_id)
    line = await _get_line(db, review.id, line_public_id)
    opportunity = await price_review_service.create_opportunity_from_line(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, review=review, line=line
    )
    return {"opportunity_public_id": str(opportunity.public_id), "status": opportunity.status}


@router.get("/{review_public_id}/summary", response_model=SupplierSummaryRead)
async def get_price_review_summary(
    review_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> SupplierSummaryRead:
    review = await _get_review(db, review_public_id)
    summary = await price_review_service.get_summary(db, review_id=review.id)
    return SupplierSummaryRead(**summary.__dict__)


@router.post("/{review_public_id}/negotiation-brief")
async def generate_negotiation_brief(
    review_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.ACCESS_AI)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    spec Section 26. Never executed in this sandbox - no network, no LLM_API_KEY (see
    app/ai/llm_provider.py and app/services/negotiation_brief_service.py docstrings). Wired here
    so the guardrail shape (verified-figures-only context, never a raw DB dump) is reviewable
    end to end from the route down.
    """
    from app.ai.llm_provider import get_llm_provider
    from app.db.models import Supplier
    from app.services.negotiation_brief_service import (
        build_negotiation_brief_context,
        generate_brief,
    )

    review = await _get_review(db, review_public_id)
    supplier_result = await db.execute(select(Supplier).where(Supplier.id == review.supplier_id))
    supplier = supplier_result.scalar_one()
    lines_result = await db.execute(
        select(PriceReviewLine).where(PriceReviewLine.price_review_id == review.id)
    )
    lines = list(lines_result.scalars().all())
    summary = await price_review_service.get_summary(db, review_id=review.id)

    context = build_negotiation_brief_context(
        supplier, lines, summary.weighted_average_price_increase_pct
    )
    brief = await generate_brief(get_llm_provider(), context)
    return {"brief": brief.model_dump()}
async def export_price_review_excel(
    review_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.EXPORT_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Returns a storage path in this delivery rather than streaming bytes directly - swapping to a
    StreamingResponse/FileResponse once this is running against a real ASGI server is a route
    signature change, not a logic change; export_price_review itself (the function that matters)
    is already proven in tests_pure/test_excel_export.py.
    """
    review = await _get_review(db, review_public_id)
    result = await db.execute(
        select(PriceReviewLine).where(PriceReviewLine.price_review_id == review.id)
    )
    lines = list(result.scalars().all())
    export_lines = [
        ExportLine(
            old_supplier_sku=l.old_supplier_sku, old_description=l.old_description,
            old_pack_raw=l.old_pack_raw, old_price=l.old_price,
            new_supplier_sku=l.new_supplier_sku, new_description=l.new_description,
            new_pack_raw=l.new_pack_raw, new_price=l.new_price,
            normalized_old_price=l.old_normalized_price, normalized_new_price=l.new_normalized_price,
            change_amount=l.absolute_change, change_pct=l.percentage_change,
            historical_volume=l.historical_quantity, annual_volume=l.annual_quantity,
            annual_impact=l.annual_impact, margin_impact=l.annual_margin_impact,
            match_confidence=l.match_confidence, pack_changed=l.pack_changed,
            risk=l.risk_classification, movement_type=l.movement_type or "review_required",
            buyer_decision=l.buyer_decision, target_price=l.target_price,
            potential_cost_avoidance=l.potential_cost_avoidance,
        )
        for l in lines
    ]
    summary = await price_review_service.get_summary(db, review_id=review.id)
    output_path = Path(f"/tmp/procureiq-exports/{review.public_id}.xlsx")
    export_summary = ExportSummary(
        supplier_name=str(review.supplier_id), effective_date=str(review.effective_date),
        total_previous_skus=summary.total_previous_skus, total_new_skus=summary.total_new_skus,
        matched_skus=summary.matched_skus, new_skus=summary.new_skus,
        discontinued_skus=summary.discontinued_skus, increasing_skus=summary.increasing_skus,
        decreasing_skus=summary.decreasing_skus, unchanged_skus=summary.unchanged_skus,
        pack_changes=summary.pack_changes,
        weighted_average_price_increase_pct=summary.weighted_average_price_increase_pct,
        annual_cost_impact=summary.annual_cost_impact,
        products_requiring_manual_review=summary.products_requiring_manual_review,
    )
    saved_path = export_price_review(export_lines, export_summary, output_path)
    return {"export_path": str(saved_path)}
