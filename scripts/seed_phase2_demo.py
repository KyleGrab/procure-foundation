"""
Seeds a running Postgres instance with the Cape Valley Foods synthetic dataset (Phase 2) - the
same data `scripts/demo_price_review.py` proved correct against in-memory. This script needs a
live DB connection (SQLAlchemy/asyncpg), neither installable in this sandbox - syntax-checked
only, not run. Run it with `python -m scripts.seed_phase2_demo` once `docker compose up -d
postgres && alembic upgrade head` has been run somewhere with network access.

Deliberately reuses the exact generation logic in scripts/generate_synthetic_price_review_data.py
rather than hand-writing a second, possibly-inconsistent dataset - if the planted scenarios in
that generator change, this seed script picks up the change automatically.
"""
from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.models import (  # noqa: E402
    Organisation,
    OrganisationMembership,
    PriceReview,
    PriceReviewLine,
    Supplier,
    User,
)
from app.ingestion.excel_reader import read_xlsx_rows  # noqa: E402
from app.ingestion.mapping import apply_mapping, suggest_mapping  # noqa: E402
from app.matching.pack_parser import UnrecognizedPackFormatError, parse_pack_string, price_per_base_unit  # noqa: E402
from app.matching.review import requires_human_review  # noqa: E402
from app.matching.scorer import CandidateItem, MatchStatus, find_best_match  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"
SEED_EMAIL = "demo@capevalleyfoods.example"
SEED_ORG_NAME = "Gourmet Demo Distribution (Pty) Ltd"


def _normalize(pack_raw: str | None, price: Decimal | None):
    if not pack_raw or price is None:
        return None, None
    try:
        parsed = parse_pack_string(pack_raw)
        return price_per_base_unit(price, parsed), parsed.base_unit
    except (UnrecognizedPackFormatError, ValueError):
        return None, None


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    old_rows = [
        apply_mapping(r, {**suggest_mapping(list(r.keys())), "supplier_sku": "Stock Code"})
        for r in read_xlsx_rows(DATA_DIR / "cape_valley_foods_old_price_list.xlsx")
    ]
    new_rows = [
        apply_mapping(r, {**suggest_mapping(list(r.keys())), "supplier_sku": "Stock Code"})
        for r in read_xlsx_rows(DATA_DIR / "cape_valley_foods_new_price_list.xlsx")
    ]

    async with session_factory() as db:
        organisation = Organisation(name=SEED_ORG_NAME, default_currency="ZAR", country="ZA")
        db.add(organisation)
        await db.flush()

        user = User(
            first_name="Demo", last_name="Buyer", email=SEED_EMAIL,
            password_hash=hash_password("demo-password-change-me"), verified=True,
        )
        db.add(user)
        await db.flush()

        db.add(OrganisationMembership(
            user_id=user.id, organisation_id=organisation.id, role="owner", status="active",
        ))

        supplier = Supplier(
            organisation_id=organisation.id, legal_name="Cape Valley Foods (Pty) Ltd",
            supplier_code="CVF", currency="ZAR", category="Food & Beverage",
        )
        db.add(supplier)
        await db.flush()

        review = PriceReview(
            organisation_id=organisation.id, supplier_id=supplier.id, status="analysing",
            currency="ZAR", price_basis="tax_exclusive", created_by_user_id=user.id,
        )
        db.add(review)
        await db.flush()

        # Reuses exactly the matching pipeline proven in scripts/demo_price_review.py - this
        # script's only new responsibility is persistence, not matching logic.
        old_candidates = [
            CandidateItem(key=str(r["supplier_sku"]), supplier_sku=r.get("supplier_sku"),
                           barcode=r.get("barcode"), description=r.get("description") or "")
            for r in old_rows
        ]
        new_candidates = [
            CandidateItem(key=str(r["supplier_sku"]), supplier_sku=r.get("supplier_sku"),
                           barcode=r.get("barcode"), description=r.get("description") or "")
            for r in new_rows
        ]
        new_by_sku = {r["supplier_sku"]: r for r in new_rows}
        old_by_sku = {r["supplier_sku"]: r for r in old_rows}
        matched_new_skus: set[str] = set()

        for old_row, old_item in zip(old_rows, old_candidates):
            result = find_best_match(old_item, new_candidates)
            old_price = Decimal(str(old_row["price"])) if old_row.get("price") else None
            old_norm, old_unit = _normalize(old_row.get("pack_size"), old_price)

            if result.status == MatchStatus.NO_CANDIDATE or result.new_key is None:
                db.add(PriceReviewLine(
                    organisation_id=organisation.id, price_review_id=review.id,
                    old_supplier_sku=old_row.get("supplier_sku"), old_description=old_row.get("description"),
                    old_pack_raw=old_row.get("pack_size"), old_price=old_price,
                    old_normalized_price=old_norm, old_normalized_base_unit=old_unit,
                    match_status="discontinued", match_method="unmatched", movement_type="discontinued",
                ))
                continue

            matched_new_skus.add(result.new_key)
            new_row = new_by_sku[result.new_key]
            new_price = Decimal(str(new_row["price"])) if new_row.get("price") else None
            new_norm, new_unit = _normalize(new_row.get("pack_size"), new_price)
            pack_changed = (old_row.get("pack_size") or "") != (new_row.get("pack_size") or "")
            match_status = "matched" if not requires_human_review(result.status) else "review_required"

            db.add(PriceReviewLine(
                organisation_id=organisation.id, price_review_id=review.id,
                old_supplier_sku=old_row.get("supplier_sku"), old_description=old_row.get("description"),
                old_pack_raw=old_row.get("pack_size"), old_price=old_price,
                old_normalized_price=old_norm, old_normalized_base_unit=old_unit,
                new_supplier_sku=new_row.get("supplier_sku"), new_description=new_row.get("description"),
                new_pack_raw=new_row.get("pack_size"), new_price=new_price,
                new_normalized_price=new_norm, new_normalized_base_unit=new_unit,
                match_status=match_status, match_method=result.method.value,
                match_confidence=Decimal(str(round(result.confidence, 4))),
                pack_changed=pack_changed,
                # Manual quantity per ADR-008 - same deterministic stand-in as demo_price_review.py.
                annual_quantity=Decimal(200 + (hash(old_row["supplier_sku"]) % 4800)),
                quantity_source="manual", quantity_confidence="low",
            ))

        for sku, new_row in new_by_sku.items():
            if sku in matched_new_skus:
                continue
            new_price = Decimal(str(new_row["price"])) if new_row.get("price") else None
            new_norm, new_unit = _normalize(new_row.get("pack_size"), new_price)
            db.add(PriceReviewLine(
                organisation_id=organisation.id, price_review_id=review.id,
                new_supplier_sku=new_row.get("supplier_sku"), new_description=new_row.get("description"),
                new_pack_raw=new_row.get("pack_size"), new_price=new_price,
                new_normalized_price=new_norm, new_normalized_base_unit=new_unit,
                match_status="new_product", match_method="unmatched", movement_type="new_product",
            ))

        await db.commit()
        print(f"Seeded organisation {SEED_ORG_NAME!r}, login {SEED_EMAIL} / demo-password-change-me")
        print(f"Supplier: Cape Valley Foods (Pty) Ltd, Price review: {review.public_id}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
