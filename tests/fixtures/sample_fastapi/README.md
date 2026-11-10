# Sample FastAPI Store API

This sample FastAPI project handles order processing and customer discount calculations.

## Business Rules
- Orders must contain at least one item or positive total amount.
- Discounts cannot exceed 50% of the total order amount under any circumstances.
- Standard customer tier receives a default 5% discount on orders exceeding $100.
- VIP customer tier receives a default 15% discount on orders exceeding $100.

## Architecture
- API endpoints are mounted under `/orders`.
- The `DiscountService` provides business rule validation and discount computation.
