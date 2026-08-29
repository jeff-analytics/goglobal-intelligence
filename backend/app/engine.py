from __future__ import annotations

from .schemas import PricingRequest, PricingResult


def calculate_pricing(req: PricingRequest) -> PricingResult:
    base_cost = req.factory_cost + req.packaging_cost + req.freight_cost + req.fulfillment_cost
    duty_cost = base_cost * req.duty_rate
    taxable_base = base_cost + duty_cost
    tax_cost = taxable_base * req.tax_rate
    landed = taxable_base + tax_cost

    # Platform fee is modeled as a percentage of selling price.
    # P - platform_rate*P = landed at break-even.
    fee_factor = 1 - req.platform_fee_rate
    break_even = landed / fee_factor

    # Target contribution margin is also a percentage of selling price.
    # P - platform_rate*P - landed = target_margin*P.
    if req.platform_fee_rate + req.target_margin_rate >= 1:
        raise ValueError("platform_fee_rate + target_margin_rate must be below 1")
    target_factor = 1 - req.platform_fee_rate - req.target_margin_rate
    target_price = landed / target_factor

    margin_at_median = None
    premium = None
    if req.listing_median is not None and req.listing_median > 0:
        platform_fee = req.listing_median * req.platform_fee_rate
        margin_at_median = (req.listing_median - platform_fee - landed) / req.listing_median
        premium = (target_price / req.listing_median) - 1

    components = {
        "Factory Cost": req.factory_cost,
        "Packaging": req.packaging_cost,
        "Freight": req.freight_cost,
        "Duty": duty_cost,
        "Tax": tax_cost,
        "Fulfillment": req.fulfillment_cost,
    }
    total = sum(components.values()) or 1.0
    shares = {name: round(value / total, 4) for name, value in components.items()}

    return PricingResult(
        pre_tax_cost=round(base_cost, 4),
        duty_cost=round(duty_cost, 4),
        tax_cost=round(tax_cost, 4),
        landed_cost_before_platform=round(landed, 4),
        break_even_price=round(break_even, 4),
        target_price=round(target_price, 4),
        margin_at_listing_median=None if margin_at_median is None else round(margin_at_median, 4),
        premium_to_listing_median=None if premium is None else round(premium, 4),
        driver_shares=shares,
    )
