"""Price transformation and anomaly detection.

All price arithmetic uses Decimal to avoid floating-point rounding errors
in financial data.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple


class PriceResult(NamedTuple):
    initial_price: Decimal | None
    price: Decimal | None
    price_per_unit: Decimal | None
    price_drop: Decimal
    price_drop_pct: Decimal
    price_is_anomaly: bool


_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TWO_DP = Decimal("0.01")


def transform(
    initial_price: Decimal | None,
    final_price: Decimal | None,
    quantity: int,
    price_min: float,
    price_max: float,
) -> PriceResult:
    """Compute all price-derived fields for a single listing."""
    qty = max(quantity, 1)

    price_drop = _ZERO
    price_drop_pct = _ZERO
    price_per_unit: Decimal | None = None
    price_is_anomaly = False

    if final_price is not None:
        price_per_unit = (final_price / qty).quantize(_TWO_DP, rounding=ROUND_HALF_UP)

        if initial_price is not None and initial_price > _ZERO:
            raw_drop = initial_price - final_price
            price_drop = max(raw_drop, _ZERO).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
            price_drop_pct = (price_drop / initial_price * _HUNDRED).quantize(
                _TWO_DP, rounding=ROUND_HALF_UP
            )

        price_is_anomaly = (
            final_price <= Decimal(str(price_min))
            or final_price > Decimal(str(price_max))
        )

    return PriceResult(
        initial_price=initial_price,
        price=final_price,
        price_per_unit=price_per_unit,
        price_drop=price_drop,
        price_drop_pct=price_drop_pct,
        price_is_anomaly=price_is_anomaly,
    )
