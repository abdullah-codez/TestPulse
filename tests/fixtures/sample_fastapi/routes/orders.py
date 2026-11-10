"""FastAPI order routes with dependency injection and business service calls."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from tests.fixtures.sample_fastapi.models.order import OrderCreate, OrderResponse
from tests.fixtures.sample_fastapi.services.discount_service import DiscountService

router = APIRouter(prefix="/orders", tags=["orders"])

# In-memory storage for test fixture
_ORDER_DB: dict[int, dict[str, Any]] = {}
_ORDER_COUNTER = 1


def get_discount_service() -> DiscountService:
    """FastAPI dependency provider for DiscountService."""
    return DiscountService()


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_in: OrderCreate,
    discount_svc: DiscountService = Depends(get_discount_service),
) -> OrderResponse:
    """Creates a new order, calculates discounts, and stores the record."""
    global _ORDER_COUNTER

    discount_amount = discount_svc.calculate_discount(
        total_amount=order_in.total_amount,
        customer_tier=order_in.customer_tier,
        is_first_order=order_in.is_first_order,
    )
    final_amount = max(0.0, order_in.total_amount - discount_amount)

    order_id = _ORDER_COUNTER
    _ORDER_COUNTER += 1

    record = {
        "order_id": order_id,
        "customer_id": order_in.customer_id,
        "total_amount": order_in.total_amount,
        "discount_amount": discount_amount,
        "final_amount": final_amount,
        "created_at": datetime.now(UTC),
    }
    _ORDER_DB[order_id] = record

    return OrderResponse(**record)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_by_id(order_id: int) -> OrderResponse:
    """Retrieves an existing order by ID or raises 404."""
    if order_id not in _ORDER_DB:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found",
        )
    return OrderResponse(**_ORDER_DB[order_id])
