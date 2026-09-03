from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class PriceReview(Base, TenantScopedMixin):
    """The review itself - one per supplier price comparison exercise (spec Section 1)."""

    __tablename__ = "price_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ZAR")
    price_basis: Mapped[str] = mapped_column(String(16), nullable=False, default="tax_exclusive")

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceReviewFile(Base, TenantScopedMixin):
    """Uploaded old/new price list files (spec Section 2). checksum + price_review_id unique
    constraint is what implements 'prevent accidental duplicate processing of the same file.'"""

    __tablename__ = "price_review_files"
    __table_args__ = (
        # No two files with the same checksum can be processed twice against the same review.
        # See migration 0002 for the actual UniqueConstraint (kept there so Alembic owns naming).
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    price_review_id: Mapped[int] = mapped_column(ForeignKey("price_reviews.id"), nullable=False)

    file_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'previous' | 'new'
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int | None] = mapped_column()
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Set once the user confirms the mapping (spec Section 3 - never auto-applied). staged_rows
    # holds the mapped+validated rows so /match can read both files' staged data without
    # re-parsing the source file a second time - the same staging-before-use shape as
    # ContractExtraction (ADR-004), applied here to file-parsing rather than AI extraction.
    column_mapping: Mapped[dict | None] = mapped_column(JSONB)
    staged_rows: Mapped[list | None] = mapped_column(JSONB)


class PriceReviewMappingTemplate(Base, TenantScopedMixin):
    """Saved column mappings per supplier (spec Section 3) - so the next upload from the same
    supplier doesn't need remapping from scratch."""

    __tablename__ = "price_review_mapping_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    column_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class PriceReviewLine(Base, TenantScopedMixin):
    """
    The core review-line entity (spec Sections 12, 19, 20, 22-24) - deliberately one wide table
    rather than several joined ones, matching the "Main Analysis Table" the spec describes as a
    single row per SKU pairing. See docs/phase2-price-review-plan.md Section 2.3 for the module
    layout this sits in.
    """

    __tablename__ = "price_review_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    price_review_id: Mapped[int] = mapped_column(ForeignKey("price_reviews.id"), nullable=False)

    # --- old-list side ---
    old_supplier_sku: Mapped[str | None] = mapped_column(String(128))
    old_description: Mapped[str | None] = mapped_column(String(512))
    old_pack_raw: Mapped[str | None] = mapped_column(String(128))
    old_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    old_normalized_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    old_normalized_base_unit: Mapped[str | None] = mapped_column(String(8))
    old_source_row_ref: Mapped[dict | None] = mapped_column(JSONB)  # {file_id, row_number}

    # --- new-list side ---
    new_supplier_sku: Mapped[str | None] = mapped_column(String(128))
    new_description: Mapped[str | None] = mapped_column(String(512))
    new_pack_raw: Mapped[str | None] = mapped_column(String(128))
    new_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    new_normalized_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    new_normalized_base_unit: Mapped[str | None] = mapped_column(String(8))
    new_source_row_ref: Mapped[dict | None] = mapped_column(JSONB)

    # --- matching (spec Section 8-11) ---
    match_status: Mapped[str] = mapped_column(String(32), nullable=False)  # matched|new_product|discontinued|review_required
    match_method: Mapped[str | None] = mapped_column(String(32))
    match_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    match_confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    match_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- price movement (spec Section 12, analytics-methodology.md) ---
    movement_type: Mapped[str | None] = mapped_column(String(32))
    absolute_change: Mapped[float | None] = mapped_column(Numeric(18, 4))
    percentage_change: Mapped[float | None] = mapped_column(Numeric(9, 6))
    pack_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_classification: Mapped[str | None] = mapped_column(String(16))
    comparison_basis: Mapped[str | None] = mapped_column(String(16))  # 'normalized'|'raw'|'unit_mismatch'

    # --- volume (spec Section 13; manual entry in this phase - see ADR-008) ---
    historical_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4))
    annual_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4))
    quantity_source: Mapped[str | None] = mapped_column(String(32))  # 'manual' | 'purchase_history'
    quantity_confidence: Mapped[str | None] = mapped_column(String(16))  # 'low'|'medium'|'high'
    historical_spend: Mapped[float | None] = mapped_column(Numeric(18, 4))
    annual_impact: Mapped[float | None] = mapped_column(Numeric(18, 4))

    # --- margin (spec Section 17-18) ---
    selling_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    old_margin_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))
    new_margin_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))
    margin_movement_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))
    annual_margin_impact: Mapped[float | None] = mapped_column(Numeric(18, 4))

    # --- buyer workflow (spec Section 22-24) ---
    buyer_decision: Mapped[str | None] = mapped_column(String(16))  # accept|challenge|negotiate|investigate|ignore
    buyer_decision_notes: Mapped[str | None] = mapped_column(String(2048))
    buyer_decision_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    buyer_decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    target_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    potential_cost_avoidance: Mapped[float | None] = mapped_column(Numeric(18, 4))
    final_negotiated_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    actual_cost_avoidance: Mapped[float | None] = mapped_column(Numeric(18, 4))
