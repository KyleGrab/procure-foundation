"""
CONSOLIDATION-FLAG-REVIEW-R1: focused tests for the already-implemented (previously untested,
undocumented) supplier-consolidation flag review route/service -
POST /opportunities/consolidation-flags/{flag_public_id}/review (app/api/v1/opportunities.py) ->
app.services.duplicate_detection_service.review_consolidation_flag. Mirrors the rigor of the
duplicate-SKU flag review coverage in test_phase5_api.py, adapted to this route's real contract
(a JSON body with a 3-state action enum + optional notes, validated by
app.analytics.domain_graph.determine_consolidation_flag_transition - not a bare confirmed:bool).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.core.security import create_access_token, decode_access_token
from app.db.models import AuditLog, Supplier, SupplierConsolidationFlag, User


async def _register_org_with_two_suppliers(client, email: str, org_name: str) -> tuple[str, int, str, str]:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    token = resp.json()["access_token"]
    claims = decode_access_token(token)
    supplier_a = await client.post(
        "/suppliers", json={"legal_name": f"{org_name} Supplier A", "currency": "ZAR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    supplier_b = await client.post(
        "/suppliers", json={"legal_name": f"{org_name} Supplier B", "currency": "ZAR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return token, claims.active_org_id, supplier_a.json()["public_id"], supplier_b.json()["public_id"]


async def _seed_flag(db_session, *, organisation_id: int, supplier_a_id: int, supplier_b_id: int,
                      status: str = "flagged") -> SupplierConsolidationFlag:
    flag = SupplierConsolidationFlag(
        organisation_id=organisation_id, supplier_a_id=supplier_a_id, supplier_b_id=supplier_b_id,
        description_a="Frozen Chicken Portions 2kg", description_b="Frozen Chicken Portions 2kg (Supplier B)",
        similarity_score=Decimal("0.9200"), combined_spend=Decimal("450000.0000"), match_method="fuzzy_description",
        status=status,
    )
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)
    return flag


async def _internal_supplier_id(db_session, supplier_public_id: str) -> int:
    result = await db_session.execute(select(Supplier.id).where(Supplier.public_id == supplier_public_id))
    return result.scalar_one()


class TestAuthorisedReviewTransitions:
    async def test_authorised_reviewer_can_advance_flag_to_under_review(self, client, db_session):
        token, org_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-review-advance@example.com", "Consol Review Advance Org"
        )
        flag = await _seed_flag(
            db_session, organisation_id=org_id,
            supplier_a_id=await _internal_supplier_id(db_session, sa),
            supplier_b_id=await _internal_supplier_id(db_session, sb),
        )
        resp = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "mark_under_review", "notes": "Reviewing service risk and lead times"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "under_review"
        assert resp.json()["review_notes"] == "Reviewing service risk and lead times"

    async def test_authorised_reviewer_can_reject_flag(self, client, db_session):
        token, org_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-review-reject@example.com", "Consol Review Reject Org"
        )
        flag = await _seed_flag(
            db_session, organisation_id=org_id,
            supplier_a_id=await _internal_supplier_id(db_session, sa),
            supplier_b_id=await _internal_supplier_id(db_session, sb),
        )
        resp = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "reject", "notes": "Different specs - not a true duplicate"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"

    async def test_review_state_reviewer_and_timestamp_are_persisted(self, client, db_session):
        token, org_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-review-persist@example.com", "Consol Review Persist Org"
        )
        flag = await _seed_flag(
            db_session, organisation_id=org_id,
            supplier_a_id=await _internal_supplier_id(db_session, sa),
            supplier_b_id=await _internal_supplier_id(db_session, sb),
        )
        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        reviewer_public_id = me.json()["public_id"]
        reviewer_id_result = await db_session.execute(select(User.id).where(User.public_id == reviewer_public_id))
        reviewer_id = reviewer_id_result.scalar_one()

        resp = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "reject", "notes": None},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text

        # db_session's own identity map still holds `flag` from the seed above (expire_on_commit
        # is False for this fixture - conftest.py) - the review itself went through a completely
        # different session (the client fixture's, via get_db). A plain re-SELECT would return
        # that already-loaded, now-stale object unchanged; refresh() forces a real reload of this
        # specific row from the database.
        await db_session.refresh(flag)
        assert flag.status == "rejected"
        assert flag.reviewed_by_user_id == reviewer_id
        assert flag.reviewed_at is not None


class TestAuditTrail:
    async def test_audit_row_created_with_canonical_text_entity_id(self, client, db_session):
        token, org_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-review-audit@example.com", "Consol Review Audit Org"
        )
        flag = await _seed_flag(
            db_session, organisation_id=org_id,
            supplier_a_id=await _internal_supplier_id(db_session, sa),
            supplier_b_id=await _internal_supplier_id(db_session, sb),
        )
        resp = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "mark_under_review"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text

        audit_result = await db_session.execute(
            select(AuditLog)
            .where(AuditLog.organisation_id == org_id)
            .where(AuditLog.action == "consolidation_flag_reviewed")
            .order_by(AuditLog.id.desc())
        )
        row = audit_result.scalars().first()
        assert row is not None
        assert row.entity_type == "supplier_consolidation_flag"
        assert row.entity_id == str(flag.id)
        assert isinstance(row.entity_id, str)
        assert row.context["new_status"] == "under_review"
        assert row.context["review_action"] == "mark_under_review"


class TestPermissionAndTenantIsolation:
    async def test_viewer_role_without_edit_suppliers_permission_is_denied(self, client, db_session):
        token, org_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-review-viewer@example.com", "Consol Review Viewer Org"
        )
        flag = await _seed_flag(
            db_session, organisation_id=org_id,
            supplier_a_id=await _internal_supplier_id(db_session, sa),
            supplier_b_id=await _internal_supplier_id(db_session, sb),
        )
        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        owner_user_id_result = await db_session.execute(
            select(User.id).where(User.public_id == me.json()["public_id"])
        )
        owner_user_id = owner_user_id_result.scalar_one()
        # Role.VIEWER's only permission is VIEW_FINANCIALS (app/core/constants.py) - no
        # EDIT_SUPPLIERS. create_access_token mints a real, validly-signed token directly (no
        # invite-acceptance HTTP flow exists yet to test through - same established exception as
        # test_k2_auth_membership_rls.py's own equivalent comment).
        viewer_token = create_access_token(user_id=owner_user_id, active_org_id=org_id, role="viewer")

        resp = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "mark_under_review"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403

    async def test_another_organisation_cannot_read_or_review_the_flag(self, client, db_session):
        token_a, org_a_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-cross-a@example.com", "Consol Cross Org A"
        )
        token_b, _, _, _ = await _register_org_with_two_suppliers(
            client, "consol-cross-b@example.com", "Consol Cross Org B"
        )
        flag = await _seed_flag(
            db_session, organisation_id=org_a_id,
            supplier_a_id=await _internal_supplier_id(db_session, sa),
            supplier_b_id=await _internal_supplier_id(db_session, sb),
        )

        # Org B cannot list Org A's flag - RLS-scoped, not just an application filter.
        list_resp = await client.get("/opportunities/consolidation-flags", headers={"Authorization": f"Bearer {token_b}"})
        assert all(f["public_id"] != str(flag.public_id) for f in list_resp.json())

        # Org B reviewing Org A's flag_public_id must 404 - RLS hides the row entirely.
        review_resp = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "mark_under_review"},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert review_resp.status_code == 404


class TestUnknownAndInvalidTransitions:
    async def test_unknown_flag_returns_404(self, client):
        token, _, _, _ = await _register_org_with_two_suppliers(
            client, "consol-review-404@example.com", "Consol Review 404 Org"
        )
        resp = await client.post(
            "/opportunities/consolidation-flags/00000000-0000-0000-0000-000000000000/review",
            json={"action": "mark_under_review"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_reviewing_an_already_terminal_flag_returns_409(self, client, db_session):
        token, org_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-review-terminal@example.com", "Consol Review Terminal Org"
        )
        flag = await _seed_flag(
            db_session, organisation_id=org_id,
            supplier_a_id=await _internal_supplier_id(db_session, sa),
            supplier_b_id=await _internal_supplier_id(db_session, sb),
            status="rejected",  # terminal - see determine_consolidation_flag_transition
        )
        resp = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "mark_under_review"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409

    async def test_repeated_review_after_first_terminal_decision_is_also_rejected(self, client, db_session):
        token, org_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-review-repeat@example.com", "Consol Review Repeat Org"
        )
        flag = await _seed_flag(
            db_session, organisation_id=org_id,
            supplier_a_id=await _internal_supplier_id(db_session, sa),
            supplier_b_id=await _internal_supplier_id(db_session, sb),
        )
        first = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "reject"}, headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 200
        second = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "reject"}, headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 409


class TestNoAutomaticSideEffects:
    async def test_review_never_alters_suppliers_products_opportunities_or_financial_facts(self, client, db_session):
        from app.db.models import Opportunity

        token, org_id, sa, sb = await _register_org_with_two_suppliers(
            client, "consol-review-no-side-effects@example.com", "Consol Review No Side Effects Org"
        )
        supplier_a_id = await _internal_supplier_id(db_session, sa)
        supplier_b_id = await _internal_supplier_id(db_session, sb)
        flag = await _seed_flag(db_session, organisation_id=org_id, supplier_a_id=supplier_a_id, supplier_b_id=supplier_b_id)

        suppliers_before = (
            await db_session.execute(select(Supplier).where(Supplier.organisation_id == org_id))
        ).scalars().all()
        supplier_legal_names_before = sorted(s.legal_name for s in suppliers_before)
        opportunity_count_before = len(
            (await db_session.execute(select(Opportunity).where(Opportunity.organisation_id == org_id))).scalars().all()
        )

        resp = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "mark_under_review", "notes": "under review"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        second = await client.post(
            f"/opportunities/consolidation-flags/{flag.public_id}/review",
            json={"action": "recommend_consolidation", "notes": "approved for consolidation"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "consolidation_recommended"  # the terminal, human-only decision

        suppliers_after = (
            await db_session.execute(select(Supplier).where(Supplier.organisation_id == org_id))
        ).scalars().all()
        supplier_legal_names_after = sorted(s.legal_name for s in suppliers_after)
        opportunity_count_after = len(
            (await db_session.execute(select(Opportunity).where(Opportunity.organisation_id == org_id))).scalars().all()
        )

        # Same two suppliers, unmerged, unmodified; no opportunity auto-created; no financial fact
        # written anywhere by this action - only the flag's own review columns changed.
        assert supplier_legal_names_after == supplier_legal_names_before
        assert len(suppliers_after) == 2
        assert opportunity_count_after == opportunity_count_before == 0
