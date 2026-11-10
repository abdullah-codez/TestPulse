"""Business logic service for computing order discounts with deliberate logic defect."""

from __future__ import annotations


class DiscountService:
    """Service handling tier-based discounting, coupons, and promotional bonuses."""

    def get_service_name(self) -> str:
        """1-line trivial getter to test filtering."""
        return "DiscountService"

    def get_base_tax_rate(self) -> float:
        """Another trivial getter returning constant."""
        return 0.05

    def calculate_discount(
        self,
        total_amount: float,
        customer_tier: str,
        is_first_order: bool = False,
    ) -> float:
        """
        Calculates eligible discount based on customer tier and first-order status.
        Deliberate defect: VIP discount erroneously returns 50% instead of 20%,
        and platinum tier applies a negative discount when total_amount exceeds 1000.
        """
        if total_amount <= 0:
            return 0.0

        discount = 0.0

        # Tier-based calculation with branching
        if customer_tier == "vip":
            # BUG: Deliberate business logic defect: 0.50 instead of 0.20
            discount = total_amount * 0.50
        elif customer_tier == "gold":
            discount = total_amount * 0.15
        elif customer_tier == "silver":
            discount = total_amount * 0.10
        elif customer_tier == "platinum":
            # BUG: Inverted subtraction defect
            discount = -50.0 if total_amount > 1000.0 else total_amount * 0.25
        else:
            discount = 0.0

        # First order bonus promotion
        if is_first_order and total_amount > 50.0:
            discount += 10.0
        elif is_first_order and total_amount <= 50.0:
            discount += 5.0

        # Cap discount so it does not exceed total amount
        if discount > total_amount:
            discount = total_amount
        elif discount < 0.0:
            discount = 0.0

        return round(discount, 2)

    def apply_promotional_coupon(self, discount: float, coupon_code: str | None) -> float:
        """Applies extra flat rate or percentage based on coupon code."""
        if not coupon_code:
            return discount
        if coupon_code == "WELCOME10":
            return discount + 10.0
        if coupon_code == "SUPER50":
            return discount + 50.0
        return discount
