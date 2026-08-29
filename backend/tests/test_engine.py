from app.engine import calculate_pricing
from app.schemas import PricingRequest


def test_target_price_above_break_even():
    result = calculate_pricing(PricingRequest(
        factory_cost=12,
        packaging_cost=0.6,
        freight_cost=2.5,
        duty_rate=0.05,
        tax_rate=0.08,
        fulfillment_cost=3.1,
        platform_fee_rate=0.12,
        target_margin_rate=0.25,
        listing_median=34.5,
    ))
    assert result.target_price > result.break_even_price
    assert result.premium_to_listing_median is not None


def test_invalid_fee_plus_margin():
    import pytest
    with pytest.raises(ValueError):
        calculate_pricing(PricingRequest(
            factory_cost=1,
            platform_fee_rate=0.7,
            target_margin_rate=0.3,
        ))
