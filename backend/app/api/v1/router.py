from fastapi import APIRouter

from app.api.v1 import (
    ai_copilot,
    auth,
    canvas,
    contracts,
    dashboard,
    goods_receipts,
    health,
    inventory,
    logistics,
    opportunities,
    organizations,
    price_reviews,
    purchase_invoices,
    purchase_orders,
    purchase_transactions,
    rebates,
    savings_register,
    spend_analytics,
    suppliers,
    treasury,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(users.router)
api_router.include_router(suppliers.router)
api_router.include_router(price_reviews.router)
api_router.include_router(contracts.router)
api_router.include_router(rebates.router)
api_router.include_router(purchase_transactions.router)
api_router.include_router(purchase_orders.router)
api_router.include_router(purchase_invoices.router)
api_router.include_router(goods_receipts.router)
api_router.include_router(spend_analytics.router)
api_router.include_router(opportunities.router)
api_router.include_router(savings_register.router)
api_router.include_router(ai_copilot.router)
api_router.include_router(dashboard.router)
api_router.include_router(canvas.router)
api_router.include_router(inventory.router)
api_router.include_router(logistics.router)
api_router.include_router(treasury.router)
