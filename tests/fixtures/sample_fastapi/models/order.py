"""Order domain and data models for sample FastAPI fixture."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class OrderItem(BaseModel):
    item_id: str
    name: str
    price: float = Field(gt=0)
    quantity: int = Field(gt=0, default=1)


class OrderCreate(BaseModel):
    customer_id: str
    customer_tier: str = "standard"
    is_first_order: bool = False
    items: list[OrderItem] = []
    total_amount: float = Field(ge=0)


class OrderResponse(BaseModel):
    order_id: int
    customer_id: str
    total_amount: float
    discount_amount: float
    final_amount: float
    created_at: datetime


class OrderModel:
    """Mock database ORM representation of an Order."""

    def __init__(
        self,
        order_id: int,
        customer_id: str,
        total_amount: float,
        discount_amount: float,
        final_amount: float,
    ) -> None:
        self.order_id = order_id
        self.customer_id = customer_id
        self.total_amount = total_amount
        self.discount_amount = discount_amount
        self.final_amount = final_amount
        self.created_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "customer_id": self.customer_id,
            "total_amount": self.total_amount,
            "discount_amount": self.discount_amount,
            "final_amount": self.final_amount,
            "created_at": self.created_at,
        }
