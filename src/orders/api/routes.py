from fastapi import APIRouter

from orders.api.health import router as health_router
from orders.api.orders import router as orders_router

router = APIRouter()
router.include_router(health_router)
router.include_router(orders_router)
