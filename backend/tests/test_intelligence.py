from app.intelligence import reverse_cost, decision_case


def test_reverse_cost_solves_max_factory_cost():
    r=reverse_cost(target_selling_price=100,packaging_cost=5,freight_cost=5,platform_fee_rate=.1,target_margin_rate=.2)
    assert round(r["max_landed_cost_before_platform"],2)==70
    assert round(r["max_factory_cost"],2)==60


def test_decision_case_does_not_invent_go_no_go_score():
    d=decision_case(market="US",snapshot=None,cost_ready=False)
    assert d["status"]=="INSUFFICIENT_EVIDENCE"
    assert "score" not in d


def test_decision_case_accepts_pricing_result_model():
    from app.engine import calculate_pricing
    from app.schemas import PricingRequest

    pricing = calculate_pricing(PricingRequest(
        factory_cost=10,
        duty_rate=0.05,
        tax_rate=0.20,
        platform_fee_rate=0.10,
        target_margin_rate=0.20,
    ))
    snapshot = {
        "trade": {
            "latest_total_imports": 1_000_000,
            "latest_imports_from_origin": 200_000,
            "world_metrics": {"latest_value": 1_000_000},
        },
        "suppliers": {"supplier_count": 3},
        "tariff": {"rate": 5},
        "fx": {"rate": 1.2},
    }
    case = decision_case(
        market="UK",
        snapshot=snapshot,
        pricing=pricing,
        benchmark={"median": 25},
        cost_ready=True,
    )
    assert case["economics"]["required_price"] == pricing.target_price
    assert case["economics"]["within_median"] is True
