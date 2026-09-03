from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class DuplicateSkuFlag(Base, TenantScopedMixin):
    """
    Spec Section 107: likely-duplicate products within one supplier's own SKU list, found by
    app.matching.scorer (Phase 2's engine, reused - see docs/phase5-opportunity-engine-plan.md
    §2.3). References free-text SKU/description pairs, not FKs to a product table (none exists -
    same reasoning as every phase since Phase 2). Human confirmation required before anything
    downstream treats two SKUs as the same, same never-silently-merge principle as product
    matching itself.
    """

    __tablename__ = "duplicate_sku_flags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)

    sku_a: Mapped[str | None] = mapped_column(String(128))
    description_a: Mapped[str] = mapped_column(String(512), nullable=False)
    sku_b: Mapped[str | None] = mapped_column(String(128))
    description_b: Mapped[str] = mapped_column(String(512), nullable=False)

    similarity_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="flagged")
    # 'flagged' | 'confirmed_duplicate' | 'rejected'
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupplierConsolidationFlag(Base, TenantScopedMixin):
    """
    Spec Section 22: equivalent items bought from multiple suppliers, fragmenting spend and
    negotiating leverage. A flag, never an auto-generated opportunity or recommendation - spec
    §22's explicit instruction that service risk, geographic coverage, supply resilience, and
    lead times must be weighed by a human before consolidation is even proposed as an idea.
    """

    __tablename__ = "supplier_consolidation_flags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_a_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    supplier_b_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)

    description_a: Mapped[str] = mapped_column(String(512), nullable=False)
    description_b: Mapped[str] = mapped_column(String(512), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    combined_spend: Mapped[float | None] = mapped_column(Numeric(18, 4))
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'exact_sku' | 'exact_barcode' | 'exact_normalized_description' | 'fuzzy_description' |
    # 'unmatched' (app.matching.scorer.MatchMethod) | 'unknown' (rows predating this column -
    # migration 0012 backfilled honestly rather than guessing which real method applied).

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="flagged")
    # 'flagged' | 'under_review' | 'consolidation_recommended' | 'rejected' - the human decision,
    # never set by the flagging process itself. Transitions validated by
    # app.analytics.domain_graph.determine_consolidation_flag_transition before any write here.
    review_notes: Mapped[str | None] = mapped_column(String(2048))
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
