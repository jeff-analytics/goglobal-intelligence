from __future__ import annotations

from app.advanced_analytics import (
    analyze_trade_network,
    non_dominated_sort,
    optimize_resource_allocation,
    simulate_profit_uncertainty,
)


def test_non_dominated_sort_builds_multiple_fronts_and_explains_dominance():
    rows = [
        {"market": "DE", "demand": 100, "margin": .24, "risk": .30},
        {"market": "NL", "demand": 90, "margin": .28, "risk": .22},
        {"market": "FR", "demand": 80, "margin": .20, "risk": .35},
        {"market": "GB", "demand": 120, "margin": .18, "risk": .42},
    ]
    result = non_dominated_sort(rows, [
        {"key": "demand", "direction": "max"},
        {"key": "margin", "direction": "max"},
        {"key": "risk", "direction": "min"},
    ])
    assert set(result["frontier"]) == {"DE", "NL", "GB"}
    fr = next(r for r in result["ranked"] if r["market"] == "FR")
    assert fr["pareto_rank"] > 1
    assert fr["explanation"]["dominated_by"] in {"DE", "NL"}


def test_lhs_profit_simulation_returns_probabilities_quantiles_and_sobol():
    result = simulate_profit_uncertainty(
        baseline={
            "selling_price": 100.0,
            "factory_cost": 40.0,
            "packaging_cost": 2.0,
            "freight_cost": 10.0,
            "fulfillment_cost": 3.0,
            "duty_rate": .05,
            "tax_rate": .10,
            "platform_fee_rate": .12,
        },
        variable_specs=[
            {"name": "selling_price", "distribution": "triangular", "low": 85, "high": 115, "mode": 100},
            {"name": "factory_cost", "distribution": "uniform", "low": 36, "high": 48},
            {"name": "freight_cost", "distribution": "uniform", "low": 7, "high": 16},
        ],
        sample_count=1024,
        method="lhs",
        sobol_base_n=256,
        seed=7,
        target_margin_rate=.20,
    )
    assert result["sample_count"] == 1024
    assert 0 <= result["margin"]["loss_probability"] <= 1
    assert 0 <= result["margin"]["target_margin_probability"] <= 1
    assert result["margin"]["p10"] <= result["margin"]["p50"] <= result["margin"]["p90"]
    assert len(result["sobol"]) == 3
    assert result["sobol"][0]["ST"] >= 0
    assert len(result["histogram"]) == 28


def test_milp_robust_allocation_respects_budget_caps_and_mandatory_rule():
    opportunities = [
        {"project_id": 1, "product": "A", "market": "DE", "return_rate": .50, "revenue_rate": 1.5, "uncertainty": .10, "risk_score": .25, "mandatory": True},
        {"project_id": 1, "product": "A", "market": "FR", "return_rate": .42, "revenue_rate": 1.42, "uncertainty": .08, "risk_score": .22},
        {"project_id": 2, "product": "B", "market": "US", "return_rate": .65, "revenue_rate": 1.65, "uncertainty": .30, "risk_score": .80},
        {"project_id": 2, "product": "B", "market": "NL", "return_rate": .37, "revenue_rate": 1.37, "uncertainty": .05, "risk_score": .18},
    ]
    result = optimize_resource_allocation(
        opportunities=opportunities,
        total_budget=1_000_000,
        objective="robust_profit",
        gamma=2,
        market_cap_ratio=.45,
        product_cap_ratio=.60,
        high_risk_cap_ratio=.20,
        high_risk_threshold=.65,
        min_markets=2,
        min_allocation=50_000,
        reserve_ratio=.10,
    )
    assert result["budget_used"] <= 900_000 + 1e-4
    assert len({a["market"] for a in result["allocations"]}) >= 2
    assert any(a["product_id"] == "1" and a["market"] == "DE" for a in result["allocations"])
    assert result["robust_profit_lower_bound"] <= result["nominal_profit"] + 1e-4
    assert result["market_allocations"].get("US", 0) <= 180_000 + 1e-4
    assert len(result["opportunity_decisions"]) == 4


def test_trade_network_returns_concentration_centrality_and_removal_stress():
    blocks = [
        {"market": "DE", "suppliers": [
            {"partner_iso3": "CN", "partner_name": "China", "trade_value": 70},
            {"partner_iso3": "VN", "partner_name": "Viet Nam", "trade_value": 20},
            {"partner_iso3": "TR", "partner_name": "Türkiye", "trade_value": 10},
        ]},
        {"market": "FR", "suppliers": [
            {"partner_iso3": "CN", "partner_name": "China", "trade_value": 40},
            {"partner_iso3": "VN", "partner_name": "Viet Nam", "trade_value": 35},
            {"partner_iso3": "IN", "partner_name": "India", "trade_value": 25},
        ]},
    ]
    result = analyze_trade_network(blocks)
    assert result["summary"]["markets"] == 2
    assert result["summary"]["suppliers"] == 4
    de = next(r for r in result["markets"] if r["market"] == "DE")
    assert abs(de["top1_share"] - .70) < 1e-6
    assert de["hhi"] > .5
    cn = next(s for s in result["suppliers"] if s["code"] == "CN")
    assert cn["market_reach"] == 2
    assert "betweenness" in cn
    assert result["stress_curve"][0]["remaining_observed_trade_share"] < 1
