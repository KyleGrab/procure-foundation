"""
Tests for app/analytics/canvas_lens.py (Lens 1: Procurement, Lens 3: Warehouse/Inventory).
Written before the implementation. Pure - no DB, no framework.
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.analytics.canvas_lens import (
    ContractRenewalInput,
    InventorySummaryInput,
    LocationInput,
    ManagementSummaryInput,
    NodeStatus,
    SupplierSpendInput,
    build_inventory_lens_graph,
    build_management_lens_graph,
    build_procurement_lens_graph,
)


class TestProcurementLensGraph(unittest.TestCase):
    def _suppliers(self):
        return [
            SupplierSpendInput(id=1, public_id="sup-a", name="Cape Valley Foods", category="Fresh Produce", total_spend=Decimal("500000")),
            SupplierSpendInput(id=2, public_id="sup-b", name="Karoo Dry Goods", category="Fresh Produce", total_spend=Decimal("200000")),
            SupplierSpendInput(id=3, public_id="sup-c", name="Southern Packaging", category="Packaging", total_spend=Decimal("100000")),
        ]

    def test_suppliers_connect_to_their_category_node(self):
        graph = build_procurement_lens_graph(
            self._suppliers(), aggregate_leakage=Decimal("0"), contract_renewals=[],
        )
        category_node_ids = {n.id for n in graph.nodes if n.node_type == "category"}
        self.assertEqual(category_node_ids, {"category:Fresh Produce", "category:Packaging"})
        # Two suppliers share "Fresh Produce" - one category node, two edges into it, not two nodes.
        edges_into_fresh_produce = [e for e in graph.edges if e.target_id == "category:Fresh Produce"]
        self.assertEqual(len(edges_into_fresh_produce), 2)

    def test_category_metric_is_sum_of_its_suppliers_spend(self):
        graph = build_procurement_lens_graph(
            self._suppliers(), aggregate_leakage=Decimal("0"), contract_renewals=[],
        )
        fresh_produce = next(n for n in graph.nodes if n.id == "category:Fresh Produce")
        self.assertEqual(fresh_produce.metric_value, Decimal("700000"))  # 500000 + 200000

    def test_suppliers_with_no_category_are_bucketed_not_dropped(self):
        suppliers = [SupplierSpendInput(id=1, public_id="sup-a", name="Uncategorised Co", category=None, total_spend=Decimal("1000"))]
        graph = build_procurement_lens_graph(suppliers, aggregate_leakage=Decimal("0"), contract_renewals=[])
        self.assertIn("category:Uncategorised", {n.id for n in graph.nodes})

    def test_leakage_node_status_is_critical_when_positive(self):
        graph = build_procurement_lens_graph(self._suppliers(), aggregate_leakage=Decimal("15000"), contract_renewals=[])
        leakage_node = next(n for n in graph.nodes if n.node_type == "rebate_leakage")
        self.assertEqual(leakage_node.status, NodeStatus.CRITICAL)

    def test_leakage_node_status_is_positive_when_zero(self):
        graph = build_procurement_lens_graph(self._suppliers(), aggregate_leakage=Decimal("0"), contract_renewals=[])
        leakage_node = next(n for n in graph.nodes if n.node_type == "rebate_leakage")
        self.assertEqual(leakage_node.status, NodeStatus.POSITIVE)

    def test_every_category_node_connects_to_the_single_leakage_node(self):
        graph = build_procurement_lens_graph(self._suppliers(), aggregate_leakage=Decimal("5000"), contract_renewals=[])
        leakage_edges = [e for e in graph.edges if e.target_id == "rebate_leakage"]
        self.assertEqual(len(leakage_edges), 2)  # one per category node (Fresh Produce, Packaging)

    def test_contract_renewal_node_connects_to_its_supplier_not_its_category(self):
        renewals = [ContractRenewalInput(
            contract_public_id="con-1", supplier_id=1, title="Cape Valley annual supply agreement",
            expiry_date=date(2026, 3, 1), status="expiring_soon",
        )]
        graph = build_procurement_lens_graph(self._suppliers(), aggregate_leakage=Decimal("0"), contract_renewals=renewals)
        renewal_edges = [e for e in graph.edges if e.source_id == "sup-a" and "contract:" in e.target_id]
        self.assertEqual(len(renewal_edges), 1)

    def test_empty_suppliers_gives_empty_graph_not_error(self):
        graph = build_procurement_lens_graph([], aggregate_leakage=Decimal("0"), contract_renewals=[])
        self.assertEqual(graph.nodes, [])
        self.assertEqual(graph.edges, [])


class TestInventoryLensGraph(unittest.TestCase):
    def test_location_aging_node_status_critical_when_any_item_expired(self):
        locations = [LocationInput(id=1, public_id="loc-a", name="Cape Town DC")]
        summaries = [
            InventorySummaryInput(location_id=1, description="Item A", expiry_status="expired", last_movement_days=5),
            InventorySummaryInput(location_id=1, description="Item B", expiry_status="healthy", last_movement_days=5),
        ]
        graph = build_inventory_lens_graph(locations, summaries, stale_threshold_days=60)
        aging_node = next(n for n in graph.nodes if n.node_type == "inventory_aging")
        self.assertEqual(aging_node.status, NodeStatus.CRITICAL)

    def test_location_aging_node_status_warning_when_stale_but_nothing_expired(self):
        locations = [LocationInput(id=1, public_id="loc-a", name="Cape Town DC")]
        summaries = [
            InventorySummaryInput(location_id=1, description="Item A", expiry_status="healthy", last_movement_days=90),
        ]
        graph = build_inventory_lens_graph(locations, summaries, stale_threshold_days=60)
        aging_node = next(n for n in graph.nodes if n.node_type == "inventory_aging")
        self.assertEqual(aging_node.status, NodeStatus.WARNING)

    def test_location_aging_node_status_positive_when_all_healthy_and_fresh(self):
        locations = [LocationInput(id=1, public_id="loc-a", name="Cape Town DC")]
        summaries = [
            InventorySummaryInput(location_id=1, description="Item A", expiry_status="healthy", last_movement_days=5),
        ]
        graph = build_inventory_lens_graph(locations, summaries, stale_threshold_days=60)
        aging_node = next(n for n in graph.nodes if n.node_type == "inventory_aging")
        self.assertEqual(aging_node.status, NodeStatus.POSITIVE)

    def test_configurable_stale_threshold_is_actually_applied(self):
        locations = [LocationInput(id=1, public_id="loc-a", name="Cape Town DC")]
        summaries = [InventorySummaryInput(location_id=1, description="Item A", expiry_status="healthy", last_movement_days=45)]
        warning = build_inventory_lens_graph(locations, summaries, stale_threshold_days=30)
        positive = build_inventory_lens_graph(locations, summaries, stale_threshold_days=60)
        self.assertEqual(next(n for n in warning.nodes if n.node_type == "inventory_aging").status, NodeStatus.WARNING)
        self.assertEqual(next(n for n in positive.nodes if n.node_type == "inventory_aging").status, NodeStatus.POSITIVE)

    def test_location_with_no_inventory_data_still_gets_a_node(self):
        locations = [LocationInput(id=1, public_id="loc-a", name="Empty Warehouse")]
        graph = build_inventory_lens_graph(locations, [], stale_threshold_days=60)
        self.assertIn("loc-a", {n.id for n in graph.nodes})
        # No aging node for a location with zero summary rows - nothing to summarize honestly.
        aging_nodes = [n for n in graph.nodes if n.node_type == "inventory_aging"]
        self.assertEqual(aging_nodes, [])

    def test_empty_locations_gives_empty_graph_not_error(self):
        graph = build_inventory_lens_graph([], [], stale_threshold_days=60)
        self.assertEqual(graph.nodes, [])
        self.assertEqual(graph.edges, [])


class TestManagementLensGraph(unittest.TestCase):
    def _summary(self, **overrides):
        defaults = dict(
            gross_revenue=Decimal("1000000"), cogs=Decimal("650000"),
            warehouse_abc_cost=Decimal("40000"), logistics_cost=Decimal("60000"),
            net_margin=Decimal("250000"),
            dso=Decimal("50.0"), dio=Decimal("57.1"), dpo=Decimal("42.9"), ccc=Decimal("64.2"),
            dso_variance=Decimal("2.0"), dio_variance=Decimal("-1.5"), dpo_variance=Decimal("0.5"),
        )
        defaults.update(overrides)
        return ManagementSummaryInput(**defaults)

    def test_fixed_node_chain_is_present(self):
        graph = build_management_lens_graph(self._summary())
        node_ids = {n.id for n in graph.nodes}
        self.assertEqual(
            node_ids,
            {"gross_revenue", "cogs", "warehouse_abc", "logistics_cts", "net_profitability",
             "working_capital_summary", "node-dso", "node-dio", "node-dpo", "node-ccc"},
        )

    def test_ccc_node_value_is_dio_plus_dso_minus_dpo(self):
        graph = build_management_lens_graph(self._summary())
        ccc_node = next(n for n in graph.nodes if n.id == "node-ccc")
        self.assertEqual(ccc_node.details["total_ccc_days"], "64.2")

    def test_dio_dso_dpo_nodes_carry_formula_and_variance(self):
        graph = build_management_lens_graph(self._summary())
        dso_node = next(n for n in graph.nodes if n.id == "node-dso")
        self.assertIn("formula", dso_node.details)
        self.assertEqual(dso_node.details["variance_vs_prior"], "2.0")

    def test_negative_net_margin_makes_profitability_node_critical(self):
        graph = build_management_lens_graph(self._summary(net_margin=Decimal("-5000")))
        node = next(n for n in graph.nodes if n.id == "net_profitability")
        self.assertEqual(node.status, NodeStatus.CRITICAL)

    def test_dio_dso_dpo_edges_fan_into_ccc(self):
        graph = build_management_lens_graph(self._summary())
        ccc_edges = {e.source_id for e in graph.edges if e.target_id == "node-ccc"}
        self.assertEqual(ccc_edges, {"node-dio", "node-dso", "node-dpo"})

    def test_none_working_capital_metrics_dont_crash_and_show_no_data(self):
        graph = build_management_lens_graph(self._summary(dso=None, dio=None, dpo=None, ccc=None))
        ccc_node = next(n for n in graph.nodes if n.id == "node-ccc")
        self.assertIsNone(ccc_node.details["total_ccc_days"])


if __name__ == "__main__":
    unittest.main()
