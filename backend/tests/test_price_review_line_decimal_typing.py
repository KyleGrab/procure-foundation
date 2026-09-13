"""
BACKEND-PRICE-REVIEW-DECIMAL-TYPING-R1: proves PriceReviewLine's NUMERIC(18,4)/(9,6)/(5,4)
columns round-trip through a real Postgres connection as `Decimal`, not `float`, and that
calculate_line_movement's existing business behaviour (exact 4-decimal arithmetic, None-stays-None
for unavailable inputs, zero-old-price percentage contract) is unchanged by the annotation-only
retype in app/db/models/price_review.py.

Neither existing price-review test file (test_price_review_tenant_isolation.py,
api/test_price_review_read_supplier_public_id.py) exercises PriceReviewLine's numeric fields or
calculate_line_movement at all - both only touch the parent PriceReview row. This file is the
first real coverage of that behaviour, using the same admin `db_session` fixture pattern as
tests/conftest.py's own p03_seed (raw ORM writes; RLS is irrelevant to what's being proven here).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import Organisation, PriceReview, PriceReviewLine, Supplier, User
from app.schemas.price_review import PriceReviewLineRead
from app.services.price_review_service import calculate_line_movement


@pytest.fixture
async def price_review_seed(db_session):
    """One organisation/user/supplier/review, committed - enough FK scaffolding for
    PriceReviewLine rows. Mirrors p03_seed's minimal-valid-row approach."""
    org = Organisation(name="Decimal Typing Test Org", default_currency="ZAR", country="ZA")
    db_session.add(org)
    await db_session.flush()

    user = User(
        first_name="Decimal", last_name="Typing", email=f"decimal-typing-{uuid.uuid4()}@procureiq.local",
        password_hash="not-a-real-hash-seed-only", verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    supplier = Supplier(organisation_id=org.id, legal_name="Decimal Typing Test Supplier")
    db_session.add(supplier)
    await db_session.flush()

    review = PriceReview(
        organisation_id=org.id, supplier_id=supplier.id, created_by_user_id=user.id,
        status="draft", currency="ZAR", price_basis="tax_exclusive",
    )
    db_session.add(review)
    await db_session.flush()
    await db_session.commit()
    return org, user, review


async def _make_line(db_session, review, **overrides) -> PriceReviewLine:
    defaults = {
        "organisation_id": review.organisation_id, "price_review_id": review.id,
        "match_status": "matched", "pack_changed": False,
    }
    defaults.update(overrides)
    line = PriceReviewLine(**defaults)
    db_session.add(line)
    await db_session.flush()
    await db_session.commit()
    return line


async def _refetch(db_session, line_id: int) -> PriceReviewLine:
    """Forces a real read back from Postgres rather than reusing the in-memory object the test
    itself constructed - db_session is expire_on_commit=False, so without this, `line.old_price`
    would just be the Python Decimal the test already passed in, proving nothing about what the
    driver actually returns for a NUMERIC column."""
    db_session.expire_all()
    result = await db_session.execute(select(PriceReviewLine).where(PriceReviewLine.id == line_id))
    return result.scalar_one()


async def test_persisted_numeric_price_returns_as_decimal_not_float(db_session, price_review_seed):
    _org, _user, review = price_review_seed
    line = await _make_line(
        db_session, review,
        old_price=Decimal("10.1000"), new_price=Decimal("12.3456"),
        match_confidence=Decimal("0.9500"), annual_quantity=Decimal("1000.0000"),
    )

    fetched = await _refetch(db_session, line.id)

    assert isinstance(fetched.old_price, Decimal)
    assert not isinstance(fetched.old_price, float)
    assert fetched.old_price == Decimal("10.1000")
    assert isinstance(fetched.new_price, Decimal)
    assert isinstance(fetched.match_confidence, Decimal)
    assert isinstance(fetched.annual_quantity, Decimal)


async def test_four_decimal_price_movement_is_exact_not_float_imprecise(db_session, price_review_seed):
    """old=10.1000, new=12.3456 is chosen because (12.3456 - 10.1000) is exactly representable in
    Decimal but not in binary float - float arithmetic here would produce 2.2455999999999... The
    absolute_change must come back as the literal Decimal("2.2456")."""
    _org, _user, review = price_review_seed
    line = await _make_line(
        db_session, review, old_price=Decimal("10.1000"), new_price=Decimal("12.3456"),
    )
    fetched = await _refetch(db_session, line.id)

    calculate_line_movement(fetched)

    assert fetched.absolute_change == Decimal("2.2456")
    assert isinstance(fetched.absolute_change, Decimal)
    assert fetched.comparison_basis == "raw"


async def test_nullable_price_inputs_remain_none_not_zeroed(db_session, price_review_seed):
    """cmp_old is None (old_price never set) -> calculate_line_movement's early-exit branch must
    leave absolute_change/percentage_change unset (None), never fabricate 0, 0.0, Decimal('0'),
    NaN, or a percentage."""
    _org, _user, review = price_review_seed
    line = await _make_line(
        db_session, review, old_price=None, new_price=Decimal("12.3456"),
    )
    fetched = await _refetch(db_session, line.id)
    assert fetched.old_price is None

    calculate_line_movement(fetched)

    assert fetched.absolute_change is None
    assert fetched.percentage_change is None


async def test_unit_mismatch_also_leaves_change_fields_none(db_session, price_review_seed):
    """old_normalized_price set but new_normalized_price missing -> determine_comparison_basis
    returns 'unit_mismatch', whose branch explicitly sets absolute_change/percentage_change to
    None rather than comparing incompatible units."""
    _org, _user, review = price_review_seed
    line = await _make_line(
        db_session, review,
        old_price=Decimal("10.0000"), new_price=Decimal("11.0000"),
        old_normalized_price=Decimal("5.0000"), old_normalized_base_unit="kg",
        new_normalized_price=None, new_normalized_base_unit=None,
    )
    fetched = await _refetch(db_session, line.id)

    calculate_line_movement(fetched)

    assert fetched.comparison_basis == "unit_mismatch"
    assert fetched.absolute_change is None
    assert fetched.percentage_change is None
    assert fetched.movement_type == "review_required"
    assert fetched.risk_classification == "unclassified"


async def test_zero_old_price_percentage_change_stays_none_not_invented(db_session, price_review_seed):
    """Established contract (calculate_percentage_change): a zero old_price yields
    percentage_change = None, never 0%, never an inflated/undefined percentage. absolute_change is
    still computed - only the percentage is undefined."""
    _org, _user, review = price_review_seed
    line = await _make_line(
        db_session, review, old_price=Decimal("0.0000"), new_price=Decimal("5.0000"),
    )
    fetched = await _refetch(db_session, line.id)

    calculate_line_movement(fetched)

    assert fetched.absolute_change == Decimal("5.0000")
    assert fetched.percentage_change is None


async def test_line_read_schema_serialization_unchanged(db_session, price_review_seed):
    """PriceReviewLineRead.model_validate(line) is the exact call GET /{review}/lines uses
    (app/api/v1/price_reviews.py). Proves the retype didn't change the public response shape:
    same field names, Decimal values still serialize (as JSON numbers, matching the established
    contract), and None fields still serialize as null rather than 0."""
    _org, _user, review = price_review_seed
    line = await _make_line(
        db_session, review,
        old_price=Decimal("10.1000"), new_price=Decimal("12.3456"),
        annual_quantity=None, target_price=None,
    )
    fetched = await _refetch(db_session, line.id)
    calculate_line_movement(fetched)

    schema = PriceReviewLineRead.model_validate(fetched)
    payload = schema.model_dump(mode="json")

    assert payload["old_price"] == "10.1000"
    assert payload["new_price"] == "12.3456"
    assert payload["absolute_change"] == "2.2456"
    assert payload["annual_quantity"] is None
    assert payload["target_price"] is None
    assert set(payload.keys()) == {
        "public_id", "old_supplier_sku", "old_description", "old_pack_raw", "old_price",
        "new_supplier_sku", "new_description", "new_pack_raw", "new_price", "match_status",
        "match_method", "match_confidence", "movement_type", "absolute_change",
        "percentage_change", "pack_changed", "comparison_basis", "risk_classification",
        "annual_quantity", "quantity_source", "quantity_confidence", "annual_impact",
        "buyer_decision", "target_price", "potential_cost_avoidance", "final_negotiated_price",
        "actual_cost_avoidance",
    }
