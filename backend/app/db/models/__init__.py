"""
Import every model here so Alembic's autogenerate (env.py) and Base.metadata see the full
schema. A model that isn't imported here is invisible to migrations - a common footgun.
"""
from app.db.models.audit_log import AuditLog
from app.db.models.contract import Contract, ContractAlert, ContractExtraction
from app.db.models.financial_amount_events import (
    FinancialAmountEvidence,
    FinancialAmountStatusEvent,
)
from app.db.models.goods_receipt import GoodsReceipt, GoodsReceiptLine
from app.db.models.inventory import InventorySnapshot
from app.db.models.inventory_reconciliation import (
    InventoryReconciliation,
    InventoryReconciliationBridge,
)
from app.db.models.location import Location
from app.db.models.management_accounting import (
    AgingLedgerSnapshot,
    CostAllocationRule,
    CostToServeLedger,
    WorkingCapitalSnapshot,
)
from app.db.models.membership import OrganisationMembership
from app.db.models.opportunity import Opportunity
from app.db.models.opportunity_flags import DuplicateSkuFlag, SupplierConsolidationFlag
from app.db.models.organisation_settings import OrganisationSetting
from app.db.models.organization import Organisation
from app.db.models.price_review import (
    PriceReview,
    PriceReviewFile,
    PriceReviewLine,
    PriceReviewMappingTemplate,
)
from app.db.models.purchase_invoice import PurchaseInvoice, PurchaseInvoiceLine
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.db.models.purchase_transaction import PurchaseTransaction
from app.db.models.rebate import RebateAgreement, RebateAlert, RebatePeriodActual
from app.db.models.refresh_token import RefreshToken
from app.db.models.route_profitability import RouteProfitabilitySnapshot
from app.db.models.supplier import Supplier
from app.db.models.treasury import FXTransactionSnapshot
from app.db.models.user import User

__all__ = [
    "AgingLedgerSnapshot",
    "AuditLog",
    "Contract",
    "ContractAlert",
    "ContractExtraction",
    "CostAllocationRule",
    "CostToServeLedger",
    "DuplicateSkuFlag",
    "FXTransactionSnapshot",
    "FinancialAmountEvidence",
    "FinancialAmountStatusEvent",
    "GoodsReceipt",
    "GoodsReceiptLine",
    "InventoryReconciliation",
    "InventoryReconciliationBridge",
    "InventorySnapshot",
    "Location",
    "Opportunity",
    "Organisation",
    "OrganisationMembership",
    "OrganisationSetting",
    "PriceReview",
    "PriceReviewFile",
    "PriceReviewLine",
    "PriceReviewMappingTemplate",
    "PurchaseInvoice",
    "PurchaseInvoiceLine",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "PurchaseTransaction",
    "RebateAgreement",
    "RebateAlert",
    "RebatePeriodActual",
    "RefreshToken",
    "RouteProfitabilitySnapshot",
    "Supplier",
    "SupplierConsolidationFlag",
    "User",
    "WorkingCapitalSnapshot",
]
