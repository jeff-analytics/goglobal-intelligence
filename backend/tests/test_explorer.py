from app.intelligence import market_quadrants, pareto_frontier, standout_markets


def test_pareto_frontier_non_weighted():
    rows = [
        {"market": "A", "imports": 100, "cagr": 0.10, "coverage": 1.0},
        {"market": "B", "imports": 80, "cagr": 0.05, "coverage": 0.8},
        {"market": "C", "imports": 60, "cagr": 0.20, "coverage": 1.0},
    ]
    f = pareto_frontier(rows)
    assert "A" in f
    assert "C" in f
    assert "B" not in f


def test_market_quadrants_uses_sample_medians():
    rows = [
        {"market": "A", "imports": 100, "cagr": 0.20},
        {"market": "B", "imports": 80, "cagr": 0.01},
        {"market": "C", "imports": 20, "cagr": 0.30},
        {"market": "D", "imports": 10, "cagr": -0.10},
    ]
    q = market_quadrants(rows)
    assert q["A"] == "HIGH_SCALE_HIGH_GROWTH"
    assert q["D"] == "SMALLER_LOWER_GROWTH"


def test_standouts_use_observed_metrics():
    rows = [
        {"market": "A", "imports": 100, "cagr": 0.1, "origin_share": 0.2, "coverage": 1.0, "hhi": 0.3},
        {"market": "B", "imports": 80, "cagr": 0.2, "origin_share": 0.4, "coverage": 0.8, "hhi": 0.2},
    ]
    s = {x["type"]: x["market"] for x in standout_markets(rows)}
    assert s["largest_import_market"] == "A"
    assert s["fastest_3y_growth"] == "B"
    assert s["most_diversified_supply"] == "B"
