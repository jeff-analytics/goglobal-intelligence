from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from scipy.stats import norm, qmc, triang


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if text.endswith("%"):
                text = text[:-1].strip()
            value = text
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# 1) Multi-objective market screening: fast non-dominated sorting + crowding
# ---------------------------------------------------------------------------


def _dominates(a: dict[str, Any], b: dict[str, Any], objectives: list[dict[str, str]]) -> bool:
    weakly_better = True
    strictly_better = False
    for obj in objectives:
        key = obj["key"]
        direction = obj.get("direction", "max")
        av, bv = _num(a.get(key)), _num(b.get(key))
        if av is None or bv is None:
            return False
        if direction == "min":
            if av > bv:
                weakly_better = False
                break
            if av < bv:
                strictly_better = True
        else:
            if av < bv:
                weakly_better = False
                break
            if av > bv:
                strictly_better = True
    return weakly_better and strictly_better


def _crowding_distance(front: list[dict[str, Any]], objectives: list[dict[str, str]]) -> dict[str, float | None]:
    if not front:
        return {}
    distance = {str(r.get("market")): 0.0 for r in front}
    if len(front) <= 2:
        return {str(r.get("market")): None for r in front}
    for obj in objectives:
        key = obj["key"]
        ordered = sorted(front, key=lambda r: float(r[key]))
        lo = float(ordered[0][key]); hi = float(ordered[-1][key])
        distance[str(ordered[0]["market"])] = math.inf
        distance[str(ordered[-1]["market"])] = math.inf
        span = hi - lo
        if abs(span) < 1e-12:
            continue
        for i in range(1, len(ordered) - 1):
            code = str(ordered[i]["market"])
            if math.isinf(distance[code]):
                continue
            prev_v = float(ordered[i - 1][key]); next_v = float(ordered[i + 1][key])
            distance[code] += abs(next_v - prev_v) / span
    return {k: (None if math.isinf(v) else round(v, 6)) for k, v in distance.items()}


def non_dominated_sort(
    rows: list[dict[str, Any]],
    objectives: list[dict[str, str]],
) -> dict[str, Any]:
    if len(objectives) < 2:
        raise ValueError("Pareto screening requires at least two objectives.")
    usable: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for row in rows:
        missing = [o["key"] for o in objectives if _num(row.get(o["key"])) is None]
        item = dict(row)
        item["missing_objectives"] = missing
        (incomplete if missing else usable).append(item)

    dominates_set: list[list[int]] = [[] for _ in usable]
    domination_count = [0 for _ in usable]
    fronts_idx: list[list[int]] = [[]]
    for p, rp in enumerate(usable):
        for q, rq in enumerate(usable):
            if p == q:
                continue
            if _dominates(rp, rq, objectives):
                dominates_set[p].append(q)
            elif _dominates(rq, rp, objectives):
                domination_count[p] += 1
        if domination_count[p] == 0:
            fronts_idx[0].append(p)

    rank = 1
    while rank - 1 < len(fronts_idx) and fronts_idx[rank - 1]:
        next_front: list[int] = []
        for p in fronts_idx[rank - 1]:
            for q in dominates_set[p]:
                domination_count[q] -= 1
                if domination_count[q] == 0:
                    next_front.append(q)
        if next_front:
            fronts_idx.append(next_front)
        rank += 1

    fronts: list[list[dict[str, Any]]] = []
    market_rank: dict[str, int] = {}
    crowding: dict[str, float | None] = {}
    for idx, front_idx in enumerate(fronts_idx, start=1):
        if not front_idx:
            continue
        front = [usable[i] for i in front_idx]
        fronts.append(front)
        crowding.update(_crowding_distance(front, objectives))
        for r in front:
            market_rank[str(r["market"])] = idx

    explanations: dict[str, dict[str, Any]] = {}
    for row in usable:
        market = str(row["market"])
        dominators = [other for other in usable if other is not row and _dominates(other, row, objectives)]
        best = None
        if dominators:
            # Pick the dominator with the largest count of strict improvements;
            # the rule is only for explanation and never affects Pareto rank.
            def strength(other: dict[str, Any]) -> tuple[int, float]:
                count = 0; magnitude = 0.0
                for obj in objectives:
                    key = obj["key"]; direction = obj.get("direction", "max")
                    a = float(other[key]); b = float(row[key])
                    delta = (a - b) if direction == "max" else (b - a)
                    if delta > 0:
                        count += 1; magnitude += abs(delta) / (abs(b) + 1e-9)
                return count, magnitude
            best = max(dominators, key=strength)
        if best is None:
            explanations[market] = {
                "status": "frontier" if market_rank.get(market) == 1 else "non_dominated_in_front",
                "summary": "No observed market weakly dominates this market across every selected objective.",
                "dominated_by": None,
                "comparisons": [],
            }
        else:
            comparisons = []
            for obj in objectives:
                key = obj["key"]; direction = obj.get("direction", "max")
                comparisons.append({
                    "key": key,
                    "direction": direction,
                    "market_value": row.get(key),
                    "dominator_value": best.get(key),
                    "strictly_better": (float(best[key]) > float(row[key])) if direction == "max" else (float(best[key]) < float(row[key])),
                })
            explanations[market] = {
                "status": "dominated",
                "summary": f"{best.get('market')} weakly outperforms this market on all selected objectives and is strictly better on at least one.",
                "dominated_by": best.get("market"),
                "comparisons": comparisons,
            }

    ranked = []
    for row in usable:
        market = str(row["market"])
        ranked.append({**row, "pareto_rank": market_rank.get(market), "crowding_distance": crowding.get(market), "explanation": explanations.get(market)})
    ranked.sort(key=lambda r: (r.get("pareto_rank") or 10**9, -(r.get("crowding_distance") or 0)))
    return {
        "objectives": objectives,
        "fronts": [[str(r.get("market")) for r in front] for front in fronts],
        "frontier": [str(r.get("market")) for r in (fronts[0] if fronts else [])],
        "ranked": ranked,
        "incomplete": incomplete,
        "method": "NSGA-II-style fast non-dominated sorting on finite market alternatives with normalized crowding distance; no weighted composite score.",
    }


# ---------------------------------------------------------------------------
# 2) Uncertainty simulation: MC / LHS + Sobol pick-freeze sensitivity
# ---------------------------------------------------------------------------


@dataclass
class VariableSpec:
    name: str
    distribution: str
    low: float
    high: float
    mode: float | None = None
    mean: float | None = None
    std: float | None = None


def _transform_unit(u: np.ndarray, spec: VariableSpec) -> np.ndarray:
    dist = spec.distribution.lower()
    lo, hi = float(spec.low), float(spec.high)
    if hi < lo:
        lo, hi = hi, lo
    if abs(hi - lo) < 1e-15:
        return np.full_like(u, lo, dtype=float)
    if dist == "triangular":
        mode = spec.mode if spec.mode is not None else (lo + hi) / 2
        c = min(1.0, max(0.0, (float(mode) - lo) / (hi - lo)))
        return triang.ppf(np.clip(u, 1e-9, 1 - 1e-9), c=c, loc=lo, scale=hi - lo)
    if dist == "normal":
        mean = float(spec.mean if spec.mean is not None else (lo + hi) / 2)
        std = float(spec.std if spec.std is not None else max((hi - lo) / 6, 1e-9))
        values = norm.ppf(np.clip(u, 1e-7, 1 - 1e-7), loc=mean, scale=std)
        return np.clip(values, lo, hi)
    return lo + np.asarray(u, dtype=float) * (hi - lo)


def _evaluate_profit(baseline: dict[str, float], specs: list[VariableSpec], samples: np.ndarray) -> dict[str, np.ndarray]:
    n = samples.shape[0]
    values = {k: np.full(n, float(v), dtype=float) for k, v in baseline.items()}
    for j, spec in enumerate(specs):
        values[spec.name] = _transform_unit(samples[:, j], spec)

    price = np.maximum(values.get("selling_price", np.zeros(n)), 1e-9)
    factory = np.maximum(values.get("factory_cost", np.zeros(n)), 0)
    packaging = np.maximum(values.get("packaging_cost", np.zeros(n)), 0)
    freight = np.maximum(values.get("freight_cost", np.zeros(n)), 0)
    fulfillment = np.maximum(values.get("fulfillment_cost", np.zeros(n)), 0)
    duty = np.clip(values.get("duty_rate", np.zeros(n)), 0, 0.999)
    tax = np.clip(values.get("tax_rate", np.zeros(n)), 0, 0.999)
    fee = np.clip(values.get("platform_fee_rate", np.zeros(n)), 0, 0.999)

    base_cost = factory + packaging + freight + fulfillment
    duty_cost = base_cost * duty
    tax_cost = (base_cost + duty_cost) * tax
    landed = base_cost + duty_cost + tax_cost
    platform_fee = price * fee
    profit = price - platform_fee - landed
    margin = profit / price
    return {"profit": profit, "margin": margin, "landed": landed, "price": price}


def _quantiles(values: np.ndarray) -> dict[str, float]:
    qs = {"p05": .05, "p10": .10, "p25": .25, "p50": .50, "p75": .75, "p90": .90, "p95": .95}
    return {k: round(float(np.quantile(values, q)), 6) for k, q in qs.items()}


def _sobol_indices(baseline: dict[str, float], specs: list[VariableSpec], base_n: int, seed: int) -> list[dict[str, float | str]]:
    d = len(specs)
    if d == 0:
        return []
    # Generate a low-discrepancy sample over [0,1]^(2D), then use the classical
    # A/B pick-freeze construction.  Jansen's estimator is used for total effect.
    power = max(4, int(math.ceil(math.log2(max(16, base_n)))))
    sob = qmc.Sobol(d=2 * d, scramble=True, seed=seed)
    unit = sob.random_base2(power)
    if len(unit) > base_n:
        unit = unit[:base_n]
    A, B = unit[:, :d], unit[:, d:]
    yA = _evaluate_profit(baseline, specs, A)["margin"]
    yB = _evaluate_profit(baseline, specs, B)["margin"]
    variance = float(np.var(np.concatenate([yA, yB]), ddof=1))
    if variance <= 1e-16:
        return [{"name": s.name, "S1": 0.0, "ST": 0.0, "interaction_gap": 0.0} for s in specs]
    out = []
    for i, spec in enumerate(specs):
        AB = A.copy(); AB[:, i] = B[:, i]
        yAB = _evaluate_profit(baseline, specs, AB)["margin"]
        s1 = float(np.mean(yB * (yAB - yA)) / variance)
        st = float(0.5 * np.mean((yA - yAB) ** 2) / variance)
        # Finite-sample estimators can produce tiny negatives / >1 estimates.
        s1 = max(-0.05, min(1.05, s1)); st = max(0.0, min(1.2, st))
        out.append({
            "name": spec.name,
            "S1": round(s1, 6),
            "ST": round(st, 6),
            "interaction_gap": round(max(0.0, st - max(0.0, s1)), 6),
        })
    out.sort(key=lambda x: float(x["ST"]), reverse=True)
    return out


def simulate_profit_uncertainty(
    *,
    baseline: dict[str, float],
    variable_specs: list[dict[str, Any]],
    sample_count: int = 10000,
    method: str = "lhs",
    sobol_base_n: int = 512,
    seed: int = 42,
    target_margin_rate: float = 0.0,
) -> dict[str, Any]:
    specs = [VariableSpec(
        name=str(v["name"]), distribution=str(v.get("distribution") or "uniform"),
        low=float(v["low"]), high=float(v["high"]),
        mode=_num(v.get("mode")), mean=_num(v.get("mean")), std=_num(v.get("std")),
    ) for v in variable_specs]
    if not specs:
        raise ValueError("At least one uncertain variable is required.")
    n = max(256, min(int(sample_count), 100000))
    d = len(specs)
    method = str(method or "lhs").lower()
    if method == "mc":
        rng = np.random.default_rng(seed)
        unit = rng.random((n, d))
        method_label = "Monte Carlo random sampling"
    else:
        sampler = qmc.LatinHypercube(d=d, scramble=True, seed=seed, optimization="random-cd" if n <= 20000 else None)
        unit = sampler.random(n=n)
        method_label = "Latin hypercube sampling"
    result = _evaluate_profit(baseline, specs, unit)
    margin = result["margin"]; profit = result["profit"]; landed = result["landed"]
    tail_n = max(1, int(len(profit) * 0.05))
    cvar_profit_5 = float(np.mean(np.sort(profit)[:tail_n]))
    sensitivity = _sobol_indices(baseline, specs, max(64, min(int(sobol_base_n), 4096)), seed + 17)
    return {
        "sample_count": n,
        "sampling_method": method,
        "sampling_method_label": method_label,
        "seed": seed,
        "baseline": {k: round(float(v), 8) for k, v in baseline.items()},
        "variables": [v.__dict__ for v in specs],
        "margin": {
            "mean": round(float(np.mean(margin)), 6), "std": round(float(np.std(margin)), 6),
            **_quantiles(margin),
            "loss_probability": round(float(np.mean(profit < 0)), 6),
            "target_margin_probability": round(float(np.mean(margin >= float(target_margin_rate))), 6),
        },
        "profit_per_unit": {
            "mean": round(float(np.mean(profit)), 6), "std": round(float(np.std(profit)), 6),
            **_quantiles(profit), "cvar_5": round(cvar_profit_5, 6),
        },
        "landed_cost": {"mean": round(float(np.mean(landed)), 6), **_quantiles(landed)},
        "histogram": _histogram(margin, bins=28),
        "sobol": sensitivity,
        "method": "Unit economics are re-evaluated for every scenario. LHS improves coverage of the uncertainty space; Sobol first-order and total-effect indices use a scrambled low-discrepancy pick-freeze design.",
    }


def _histogram(values: np.ndarray, bins: int = 24) -> list[dict[str, float | int]]:
    counts, edges = np.histogram(values, bins=bins)
    return [{"low": round(float(edges[i]), 6), "high": round(float(edges[i + 1]), 6), "count": int(counts[i])} for i in range(len(counts))]


# ---------------------------------------------------------------------------
# 3) MILP + Bertsimas-Sim budgeted robust objective
# ---------------------------------------------------------------------------


def optimize_resource_allocation(
    *,
    opportunities: list[dict[str, Any]],
    total_budget: float,
    objective: str = "robust_profit",
    gamma: float = 2.0,
    market_cap_ratio: float = 0.35,
    product_cap_ratio: float = 0.45,
    high_risk_cap_ratio: float = 0.20,
    high_risk_threshold: float = 0.65,
    min_markets: int = 1,
    min_allocation: float = 0.0,
    reserve_ratio: float = 0.0,
) -> dict[str, Any]:
    ops = []
    for raw in opportunities:
        rate = _num(raw.get("return_rate"))
        if rate is None or raw.get("enabled") is False:
            continue
        ops.append({
            **raw,
            "product_id": str(raw.get("product_id") or raw.get("project_id") or raw.get("product") or ""),
            "market": str(raw.get("market") or "").upper(),
            "return_rate": float(rate),
            "revenue_rate": float(_num(raw.get("revenue_rate")) or 1.0),
            "uncertainty": max(0.0, float(_num(raw.get("uncertainty")) or 0.0)),
            "risk_score": min(1.0, max(0.0, float(_num(raw.get("risk_score")) or 0.0))),
            "max_allocation": _num(raw.get("max_allocation")),
            "mandatory": bool(raw.get("mandatory")),
            "prohibited": bool(raw.get("prohibited")),
        })
    if not ops:
        raise ValueError("No optimization-ready product-market opportunities are available.")
    budget = float(total_budget)
    if budget <= 0:
        raise ValueError("Total budget must be positive.")
    reserve_ratio = min(.95, max(0.0, float(reserve_ratio)))
    deployable = budget * (1 - reserve_ratio)
    gamma = min(float(len(ops)), max(0.0, float(gamma)))
    effective_min_allocation = max(float(min_allocation), deployable * 0.001) if (min_markets > 0 or any(o["mandatory"] for o in ops)) else max(0.0, float(min_allocation))
    products = sorted({o["product_id"] for o in ops})
    markets = sorted({o["market"] for o in ops})
    n = len(ops); m = len(markets)
    # x_i allocation, y_i entry binary, market z_j binary, robust eta, p_i
    ix_x = 0; ix_y = n; ix_market = 2 * n; ix_eta = 2 * n + m; ix_p = ix_eta + 1
    nv = ix_p + n
    c = np.zeros(nv)
    obj = str(objective or "robust_profit")
    if obj == "revenue":
        for i, o in enumerate(ops): c[ix_x + i] = -o["revenue_rate"]
    else:
        for i, o in enumerate(ops): c[ix_x + i] = -o["return_rate"]
        if obj == "robust_profit":
            c[ix_eta] = gamma
            for i in range(n): c[ix_p + i] = 1.0
    integrality = np.zeros(nv, dtype=int)
    integrality[ix_y:ix_y+n] = 1
    integrality[ix_market:ix_market+m] = 1
    lb = np.zeros(nv); ub = np.full(nv, np.inf)
    ub[ix_y:ix_y+n] = 1; ub[ix_market:ix_market+m] = 1
    if obj != "robust_profit":
        ub[ix_eta] = 0; ub[ix_p:ix_p+n] = 0

    constraints: list[tuple[dict[int, float], float, float]] = []
    # Budget
    constraints.append(({ix_x+i: 1.0 for i in range(n)}, 0.0, deployable))
    # Link allocations to opportunity binary and handle must/forbid.
    default_max = deployable
    for i, o in enumerate(ops):
        max_alloc = min(deployable, float(o["max_allocation"]) if o["max_allocation"] is not None else default_max)
        constraints.append(({ix_x+i: 1.0, ix_y+i: -max_alloc}, -np.inf, 0.0))
        if effective_min_allocation > 0:
            constraints.append(({ix_x+i: 1.0, ix_y+i: -effective_min_allocation}, 0.0, np.inf))
        if o["mandatory"]:
            constraints.append(({ix_y+i: 1.0}, 1.0, 1.0))
        if o["prohibited"]:
            constraints.append(({ix_y+i: 1.0}, 0.0, 0.0))
        if obj == "robust_profit":
            # p_i >= d_i*x_i - eta  -> d_i*x_i - eta - p_i <= 0
            constraints.append(({ix_x+i: o["uncertainty"], ix_eta: -1.0, ix_p+i: -1.0}, -np.inf, 0.0))

    # Product concentration
    for product in products:
        coeff = {ix_x+i: 1.0 for i,o in enumerate(ops) if o["product_id"] == product}
        constraints.append((coeff, 0.0, deployable * float(product_cap_ratio)))
    # Market concentration + market binary linking
    market_pos = {market: j for j, market in enumerate(markets)}
    for market in markets:
        ids = [i for i,o in enumerate(ops) if o["market"] == market]
        coeff = {ix_x+i: 1.0 for i in ids}
        constraints.append((coeff, 0.0, deployable * float(market_cap_ratio)))
        j = market_pos[market]
        # y_i <= z_market
        for i in ids:
            constraints.append(({ix_y+i: 1.0, ix_market+j: -1.0}, -np.inf, 0.0))
        # z_market <= sum y_i
        link = {ix_market+j: 1.0}; link.update({ix_y+i: -1.0 for i in ids})
        constraints.append((link, -np.inf, 0.0))
    if min_markets > 0:
        constraints.append(({ix_market+j: 1.0 for j in range(m)}, float(min(min_markets, m)), np.inf))
    # High-risk allocation cap
    high_ids = [i for i,o in enumerate(ops) if o["risk_score"] >= high_risk_threshold]
    if high_ids:
        constraints.append(({ix_x+i: 1.0 for i in high_ids}, 0.0, deployable * float(high_risk_cap_ratio)))

    A = lil_matrix((len(constraints), nv), dtype=float)
    low = np.full(len(constraints), -np.inf); high = np.full(len(constraints), np.inf)
    for r, (coeff, lo, hi) in enumerate(constraints):
        for idx, val in coeff.items(): A[r, idx] = val
        low[r] = lo; high[r] = hi
    result = milp(c=c, integrality=integrality, bounds=Bounds(lb, ub), constraints=LinearConstraint(A.tocsr(), low, high), options={"time_limit": 20})
    if not result.success or result.x is None:
        raise ValueError(f"Optimization did not find a feasible allocation: {result.message}")
    x = result.x
    allocations = []
    for i, o in enumerate(ops):
        amount = max(0.0, float(x[ix_x+i]))
        if amount <= max(1e-6, budget * 1e-8):
            continue
        allocations.append({
            "product_id": o["product_id"], "product": o.get("product") or o.get("title") or o["product_id"],
            "market": o["market"], "allocation": round(amount, 2),
            "return_rate": round(o["return_rate"], 6), "uncertainty": round(o["uncertainty"], 6),
            "risk_score": round(o["risk_score"], 6),
            "nominal_profit": round(amount * o["return_rate"], 2),
            "revenue": round(amount * o["revenue_rate"], 2),
        })
    used = sum(a["allocation"] for a in allocations)
    nominal_profit = sum(a["nominal_profit"] for a in allocations)
    robust_penalty = 0.0
    if obj == "robust_profit":
        robust_penalty = gamma * float(x[ix_eta]) + sum(float(x[ix_p+i]) for i in range(n))
    robust_profit = nominal_profit - robust_penalty
    by_market = defaultdict(float); by_product = defaultdict(float)
    risk_exposure = 0.0
    for a in allocations:
        by_market[a["market"]] += a["allocation"]
        by_product[a["product_id"]] += a["allocation"]
        risk_exposure += a["allocation"] * a["risk_score"]
    allocation_lookup = {(str(a["product_id"]), str(a["market"])): a for a in allocations}
    opportunity_decisions = []
    for i, o in enumerate(ops):
        key = (o["product_id"], o["market"])
        chosen = key in allocation_lookup
        if chosen:
            reason = "Selected by the optimization under the current objective and constraints."
        elif o["prohibited"]:
            reason = "Excluded by user constraint."
        elif o["return_rate"] <= 0:
            reason = "Nominal return is non-positive."
        elif obj == "robust_profit" and o["uncertainty"] >= max(0.0, o["return_rate"]):
            reason = "Downside uncertainty is large relative to nominal return under the robust objective."
        elif o["risk_score"] >= high_risk_threshold:
            reason = "Competes for the capped high-risk allocation budget."
        else:
            reason = "Not selected after budget, product and market concentration trade-offs were optimized."
        opportunity_decisions.append({
            "product_id": o["product_id"], "product": o.get("product") or o.get("title") or o["product_id"],
            "market": o["market"], "selected": chosen, "reason": reason,
            "return_rate": round(o["return_rate"], 6), "uncertainty": round(o["uncertainty"], 6), "risk_score": round(o["risk_score"], 6),
        })

    return {
        "status": "optimal" if result.status == 0 else "feasible",
        "objective": obj,
        "total_budget": round(budget, 2), "deployable_budget": round(deployable, 2),
        "budget_used": round(used, 2), "reserve": round(budget - used, 2),
        "nominal_profit": round(nominal_profit, 2), "robust_profit_lower_bound": round(robust_profit, 2),
        "robust_penalty": round(robust_penalty, 2), "gamma": float(gamma), "effective_min_allocation": round(effective_min_allocation, 2),
        "weighted_risk": round(risk_exposure / used, 6) if used else 0.0,
        "allocations": sorted(allocations, key=lambda a: a["allocation"], reverse=True),
        "opportunity_decisions": opportunity_decisions,
        "market_allocations": {k: round(v, 2) for k,v in sorted(by_market.items())},
        "product_allocations": {k: round(v, 2) for k,v in sorted(by_product.items())},
        "solver": "SciPy milp / HiGHS",
        "method": "Mixed-integer allocation with product/market/risk concentration constraints. Robust-profit mode uses a Bertsimas-Sim budgeted-uncertainty counterpart on return coefficients.",
    }


# ---------------------------------------------------------------------------
# 5) Trade-network supply risk from observed bilateral supplier edges
# ---------------------------------------------------------------------------


def analyze_trade_network(market_supplier_rows: list[dict[str, Any]], *, top_edges: int = 40) -> dict[str, Any]:
    G = nx.DiGraph()
    market_totals: dict[str, float] = defaultdict(float)
    edges_raw: list[dict[str, Any]] = []
    for block in market_supplier_rows:
        market = str(block.get("market") or "").upper()
        for supplier in block.get("suppliers") or []:
            code = str(supplier.get("partner_iso3") or supplier.get("partner_code") or supplier.get("partner_name") or "").upper()
            if not market or not code or code == market:
                continue
            value = _num(supplier.get("trade_value"))
            if value is None or value <= 0:
                continue
            name = str(supplier.get("partner_name") or code)
            G.add_node(code, node_type="supplier", label=name)
            G.add_node(market, node_type="market", label=str(block.get("label") or market))
            if G.has_edge(code, market):
                G[code][market]["weight"] += value
            else:
                G.add_edge(code, market, weight=value)
            market_totals[market] += value
            edges_raw.append({"source": code, "source_name": name, "target": market, "value": value})
    if G.number_of_edges() == 0:
        return {"nodes": [], "edges": [], "markets": [], "suppliers": [], "summary": {"nodes": 0, "edges": 0}, "method": "No observed supplier network available."}
    total = sum(market_totals.values()) or 1.0
    UG = G.to_undirected()
    for u, v, data in UG.edges(data=True):
        data["distance"] = 1.0 / max(float(data.get("weight") or 0), 1e-9)
    try:
        bet = nx.betweenness_centrality(UG, weight="distance", normalized=True)
    except Exception:
        bet = {n: 0.0 for n in G.nodes}
    weighted_out = {n: sum(float(G[n][v].get("weight") or 0) for v in G.successors(n)) for n in G.nodes if G.nodes[n].get("node_type") == "supplier"}
    suppliers = []
    for node, value in weighted_out.items():
        reach = int(G.out_degree(node))
        suppliers.append({
            "code": node, "name": G.nodes[node].get("label") or node,
            "trade_value": round(value, 2), "global_share": round(value / total, 6),
            "market_reach": reach, "betweenness": round(float(bet.get(node, 0.0)), 6),
        })
    suppliers.sort(key=lambda x: (x["global_share"], x["market_reach"], x["betweenness"]), reverse=True)
    top_supplier_codes = [x["code"] for x in suppliers[:3]]

    markets = []
    for market, market_total in market_totals.items():
        local = sorted([(u, float(G[u][market]["weight"])) for u in G.predecessors(market)], key=lambda x: x[1], reverse=True)
        shares = [v / market_total for _,v in local] if market_total else []
        hhi = sum(s*s for s in shares)
        top1 = shares[0] if shares else 0.0
        top3 = sum(shares[:3])
        systemic_loss = sum(v for u,v in local if u in top_supplier_codes) / market_total if market_total else 0.0
        diversity = len(local)
        # This is a transparent structural vulnerability indicator, not a country-risk forecast.
        structural_risk = 0.45 * top1 + 0.35 * hhi + 0.20 * systemic_loss
        markets.append({
            "market": market, "supplier_count": diversity, "observed_imports": round(market_total, 2),
            "top1_share": round(top1, 6), "cr3": round(top3, 6), "hhi": round(hhi, 6),
            "loss_if_top3_systemic_suppliers_removed": round(systemic_loss, 6),
            "structural_risk": round(min(1.0, structural_risk), 6),
        })
    markets.sort(key=lambda x: x["structural_risk"], reverse=True)

    # Global stress curve: remove suppliers in descending observed global share.
    stress = []
    cumulative_removed = 0.0
    for k, supplier in enumerate(suppliers[: min(10, len(suppliers))], start=1):
        cumulative_removed += supplier["trade_value"]
        stress.append({"removed_suppliers": k, "remaining_observed_trade_share": round(max(0.0, 1 - cumulative_removed / total), 6)})

    edges = []
    for e in sorted(edges_raw, key=lambda x: x["value"], reverse=True)[:max(5, min(top_edges, 120))]:
        mt = market_totals.get(e["target"], 0.0)
        edges.append({**e, "share_of_market": round(e["value"] / mt, 6) if mt else 0.0})
    nodes = []
    visible = {e["source"] for e in edges} | {e["target"] for e in edges}
    for node in visible:
        attrs = G.nodes[node]
        nodes.append({"id": node, "label": attrs.get("label") or node, "type": attrs.get("node_type")})
    return {
        "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "observed_trade": round(total, 2), "markets": len(markets), "suppliers": len(suppliers)},
        "nodes": nodes, "edges": edges, "suppliers": suppliers[:25], "markets": markets, "stress_curve": stress,
        "method": "Directed supplier-to-market HS6 trade network built from observed UN Comtrade partner shares. Risk diagnostics use concentration, weighted market reach, betweenness and supplier-removal stress tests.",
    }
