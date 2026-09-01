from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
import io
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import perf_counter

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response, RedirectResponse

from .catalog import CATALOG, catalog_summary, identify_product, search_catalog
from .comparables import build_comparable_set
from .config import settings, refresh_settings, update_local_env, mask_client_id, mask_secret
from .engine import calculate_pricing
from .markets import MARKETS, market_list
from .schemas import (
    PricingRequest, ReversePricingRequest, ProductIdentifyRequest, ProjectCreateRequest, ProjectUpdateRequest,
    TariffOverrideRequest, TaxOverrideRequest, EbayLocalConfigRequest, ComtradeLocalConfigRequest,
    ModelAPILocalConfigRequest, WebResearchLocalConfigRequest, ParetoScreenRequest, ProfitSimulationRequest,
    PortfolioOptimizationRequest, HSRankingFeedbackRequest,
)
from .sources.comtrade import compute_growth_metrics, fetch_import_history, fetch_import_history_compact, fetch_imports, fetch_supplier_structure, summarize_imports, validate_subscription_key
from .sources.comtrade_reference import resolve_partner, search_partners
from .sources.hs_reference import suggest_hs_candidates, search_hs_reference
from .hs_ranker import hybrid_hs_candidates
from .sources.ebay import (
    get_category_children,
    get_category_suggestions,
    get_default_category_tree_id,
    get_item_aspects,
    get_top_categories,
    get_top_categories_cached,
    search_listings,
    test_connection as test_ebay_connection,
    test_connection_with_config as validate_ebay_connection,
    reset_token_cache,
)
from .sources.ecb import convert, fetch_eur_reference_rate
from .sources.wits import fetch_tariff, fetch_tariff_cached
from .sources.official_tariff import lookup_official_tariff
from .market_support import support_registry, contract_from_snapshot, source_meta
from .ai_layer import ai_status, generate_evidence_brief, test_connection as test_ai_connection, list_models, normalize_ai_model_id
from .ai_recovery import recover_market, recover_hs_candidates, recovery_capabilities
from .research_agent import generate_decision_research, research_capabilities, validate_tavily, report_matches_language
from .intelligence import decision_case, evidence_quality, reverse_cost, trade_volatility, pareto_frontier, market_quadrants, standout_markets
from .advanced_analytics import non_dominated_sort, simulate_profit_uncertainty, optimize_resource_allocation, analyze_trade_network
from .providers import PROVIDERS, provider_statuses
from .portfolio import parse_portfolio_bytes, portfolio_batch_id
from .exporter import build_project_workbook
from .tariff_supply import build_supply_profile, start_tariff_job, tariff_job
from .storage import (
    create_project,
    delete_project,
    delete_tariff_override,
    get_project,
    get_tariff_override,
    init_db,
    latest_snapshot,
    list_projects,
    list_listing_snapshots,
    list_snapshots,
    save_listing_snapshot,
    save_snapshot,
    save_tariff_override,
    save_market_scan,
    get_market_scan,
    delete_market_scan,
    update_project,
    save_tax_override, get_tax_override, delete_tax_override, save_ai_brief, get_ai_brief,
    save_supply_profile, get_supply_profile, list_tariff_matrix,
    source_runtime_summary, source_cache_clear, list_ai_evidence, list_ai_recovery_runs, latest_ai_evidence,
    save_hs_ranking_feedback, list_hs_ranking_feedback,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="GoGlobal Intelligence API", version="5.4.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



def _hs6(value: str | None) -> str:
    """Normalize a user-entered HS/local tariff code to the HS6 needed by Comtrade/WITS."""
    clean = "".join(ch for ch in str(value or "").strip() if ch.isalnum())
    if len(clean) < 2:
        return ""
    return clean[:6]


def _safe_float(value):
    """Best-effort numeric coercion for persisted/legacy evidence.

    External evidence and older local databases can contain formatted strings
    such as ``"1,234.5"`` or ``"5%"``.  Read paths must never turn these
    display-format differences into a page-level HTTP 500.
    """
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if not text:
                return None
            if text.endswith("%"):
                text = text[:-1].strip()
            value = text
        out = float(value)
        if out != out or out in (float("inf"), float("-inf")):
            return None
        return out
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_mapping(value):
    """Return a plain mapping for dicts and Pydantic/domain result models."""
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            return dumped if isinstance(dumped, Mapping) else {}
        except Exception:
            return {}
    return {}


def _project_readiness(project: dict) -> dict:
    attrs = project.get("attributes") or {}
    assumptions = project.get("assumptions") or {}
    checks = {
        "product": bool(project.get("title")),
        "category": bool(attrs.get("ebay_category_id") or project.get("product_type_id") not in (None, "", "generic")),
        "hs_code": len(_hs6(project.get("hs_code"))) >= 6,
        "origin": bool(project.get("origin")),
        "markets": bool(project.get("markets")),
        "cost_inputs": assumptions.get("factory_cost") is not None and assumptions.get("target_margin_rate") is not None,
    }
    required = ["product", "hs_code", "origin", "markets"]
    complete = all(checks[k] for k in required)
    return {
        "checks": checks,
        "required_complete": complete,
        "progress": sum(1 for k in required if checks[k]) / len(required),
        "next_required": next((k for k in required if not checks[k]), None),
    }


@app.get("/")
def root_redirect():
    # Avoid a confusing JSON/404 page if the API port is opened directly.
    return RedirectResponse(url="http://localhost:5173", status_code=307)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


RELEASE_BUILD_ID = "v541-20260901-final-ci-r5"


@app.get("/api/health")
def health():
    refresh_settings()
    return {"status": "ok", "service": "GoGlobal Intelligence API", "env": settings.app_env, "version": "5.4.1", "build": RELEASE_BUILD_ID}


@app.get("/api/markets")
def markets():
    return {"markets": market_list(), "count": len(MARKETS)}


@app.get("/api/catalog")
def catalog():
    return {"items": catalog_summary(), "count": len(CATALOG)}


@app.get("/api/catalog/search")
def catalog_search(q: str, limit: int = 5):
    return {"query": q, "matches": search_catalog(q, limit=max(1, min(limit, 10)))}


@app.post("/api/catalog/identify")
def catalog_identify(req: ProductIdentifyRequest):
    return identify_product(req.text)


@app.get("/api/projects")
def projects():
    return {"projects": list_projects()}


@app.post("/api/projects")
def project_create(req: ProjectCreateRequest):
    invalid_markets = [m for m in req.markets if m.upper() not in MARKETS]
    if invalid_markets:
        raise HTTPException(status_code=422, detail=f"Unknown markets: {', '.join(invalid_markets)}")
    payload = req.model_dump()
    payload["markets"] = [m.upper() for m in req.markets]
    project = create_project(payload)
    project["readiness"] = _project_readiness(project)
    return project


@app.get("/api/projects/{project_id}")
def project_get(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.patch("/api/projects/{project_id}")
def project_update(project_id: int, req: ProjectUpdateRequest):
    changes = req.model_dump(exclude_unset=True)
    if "markets" in changes and changes["markets"] is not None:
        invalid_markets = [m for m in changes["markets"] if m.upper() not in MARKETS]
        if invalid_markets:
            raise HTTPException(status_code=422, detail=f"Unknown markets: {', '.join(invalid_markets)}")
        changes["markets"] = [m.upper() for m in changes["markets"]]
    project = update_project(project_id, changes)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.delete("/api/projects/{project_id}")
def project_delete(project_id: int):
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found or example project cannot be deleted")
    return {"deleted": True}


@app.get("/api/projects/{project_id}/dashboard")
def project_dashboard(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    snapshots = []
    origin_code = str((project.get("attributes") or {}).get("origin_partner_code") or "") or None
    if hs:
        for market in project.get("markets", []):
            snap = latest_snapshot(market, hs, origin_code=origin_code)
            if snap:
                snapshots.append(snap)
    benchmarks = {market: _research_benchmark(project, market) for market in project.get("markets", [])}
    return {
        "project": project,
        "readiness": _project_readiness(project),
        "analysis_hs6": hs or None,
        "snapshots": snapshots,
        "benchmarks": benchmarks,
        "data_status": data_status(),
    }




@app.get("/api/projects/{project_id}/readiness")
def project_readiness(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_readiness(project)


@app.get("/api/projects/{project_id}/export")
def project_export(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    snapshots = list_snapshots(hs) if hs else []
    origin_code = str((project.get("attributes") or {}).get("origin_partner_code") or "")
    selected = [s for s in snapshots if s.get("market") in set(project.get("markets") or []) and (not origin_code or str((s.get("origin") or {}).get("code") or "") == origin_code)]
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "readiness": _project_readiness(project),
        "analysis_hs6": hs or None,
        "market_snapshots": selected,
        "listing_snapshots": list_listing_snapshots(),
    }


@app.get("/api/data/status")
def data_status():
    refresh_settings()
    return {
        "comtrade": {
            "configured": True,
            "credential_present": bool(settings.comtrade_subscription_key),
            "mode": "free-key" if settings.comtrade_subscription_key else "public-preview",
            "registration": "recommended-now" if not settings.comtrade_subscription_key else "complete",
            "note": "A free key is recommended for bilateral and multi-year retrieval." if not settings.comtrade_subscription_key else "Free API key detected.",
        },
        "wits": {"configured": True, "credential_present": True, "mode": "public-reference", "registration": "not-required", "note": "Historical/reference tariff source; may not return a numeric observation for every product-market pair."},
        "official_tariff": {"configured": True, "credential_present": True, "mode": "provider-registry", "registration": "not-required", "note": "All configured markets have an official tariff source registry. US, UK and AU include automated lookup paths; other markets expose the official current source and require an unambiguous local tariff line or verified override."},
        "data_backbone": {"configured": True, "credential_present": True, "mode": "unified-market-contract", "registration": "not-required", "note": "Normalizes trade, supplier, tariff, tax-source, FX, freshness and provenance fields across all configured markets."},
        "tariff_matrix": {"configured": True, "credential_present": True, "mode": "background-hs6-reference", "registration": "not-required", "note": "UNCTAD TRAINS / WITS analytical tariff references are cached locally; current legal duty verification remains separate."},
        "origin_supply": {"configured": True, "credential_present": bool(settings.comtrade_subscription_key), "mode": "un-comtrade-export-flow", "registration": "recommended-now" if not settings.comtrade_subscription_key else "complete", "note": "Origin export history, destination structure and observed target-market corridors."},
        "ai": ai_status(),
        "ecb": {"configured": True, "credential_present": True, "mode": "public", "registration": "not-required"},
        "ebay": {
            "configured": bool(settings.ebay_client_id and settings.ebay_client_secret),
            "credential_present": bool(settings.ebay_client_id and settings.ebay_client_secret),
            "mode": settings.ebay_env,
            "registration": "complete" if settings.ebay_client_id and settings.ebay_client_secret else "recommended-now",
            "client_id_masked": mask_client_id(settings.ebay_client_id),
            "config_sources": list(settings.config_sources),
            "hot_reload": True,
            "note": (
                "Sandbox credentials detected. OAuth can be validated, but Sandbox results are not market benchmarks."
                if settings.ebay_env == "sandbox" and settings.ebay_client_id and settings.ebay_client_secret
                else "Production credentials detected. Browse access still depends on eBay Production approval."
                if settings.ebay_client_id and settings.ebay_client_secret
                else "Create Sandbox keys now. Production Buy API access has a separate approval process."
            ),
        },
        "listing_csv": {"configured": True, "credential_present": True, "mode": "local-import", "registration": "not-required"},
        "storage": {"configured": True, "mode": "sqlite", "registration": "not-required"},
    }


@app.get("/api/data/backbone/support")
def backbone_support():
    return {"markets": support_registry(), "ai": ai_status(), "version": "5.4.1"}


@app.get("/api/projects/{project_id}/backbone")
def project_backbone(project_id: int):
    project=get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs=_hs6(project.get("hs_code"))
    origin_code=str((project.get("attributes") or {}).get("origin_partner_code") or "") or None
    rows=[]
    for code in project.get("markets") or []:
        snap=latest_snapshot(code,hs,origin_code=origin_code) if hs else None
        contract=contract_from_snapshot(snap,code)
        tax_override=get_tax_override(code)
        if tax_override:
            contract["tax"]={"rate":tax_override.get("rate"),"source":"Verified manual tax","reference_year":tax_override.get("reference_year"),"note":tax_override.get("note"),"updated_at":tax_override.get("updated_at"),"status":"verified_manual","official_url":source_meta(code).get("tax_url")}
        rows.append(contract)
    return {"project_id":project_id,"hs6":hs or None,"origin":project.get("origin"),"markets":rows,"support_registry":support_registry()}


@app.get("/api/data/tax/override")
def tax_override_get(market: str):
    return {"override": get_tax_override(market), "source": source_meta(market).get("tax_source"), "official_url": source_meta(market).get("tax_url")}


@app.post("/api/data/tax/override")
def tax_override_save(req: TaxOverrideRequest):
    if req.market.upper() not in MARKETS:
        raise HTTPException(status_code=422, detail="Unknown market code")
    return {"override":save_tax_override(market=req.market,rate=req.rate,reference_year=req.reference_year,note=req.note)}


@app.delete("/api/data/tax/override")
def tax_override_delete(market: str):
    return {"deleted":delete_tax_override(market)}



_AI_SCOPE_MAP = {
    "all": ["trade", "tariff", "tax", "fx", "market_access", "marketplace", "origin_supply"],
    "market_scan": ["trade"],
    "explorer": ["trade", "tariff"],
    # A page-level action should only spend tokens on the data family shown on
    # that page. The global action is the only one that spans all families.
    "trade": ["trade", "tariff", "tax", "fx"],
    # The tariff/supply page also contains a project-level origin-export profile.
    # That profile comes from the dedicated Comtrade supply sync, so its absence
    # must block the green "data complete" state even though it is not an AI field.
    "tariff": ["tariff", "tax", "trade", "origin_supply"],
    "marketplace": ["marketplace"],
    "cost": ["tariff", "tax", "fx", "marketplace"],
    "backbone": ["trade", "tariff", "tax", "fx", "market_access", "marketplace", "origin_supply"],
}


def _ai_field_map(project_id: int, market: str) -> dict[str, dict]:
    rows = list_ai_evidence(project_id, market)
    out: dict[str, dict] = {}
    for row in rows:
        key = str(row.get("field_name") or "")
        if key and key not in out:
            out[key] = row
    return out


def _overlay_scan_row(project_id: int, row: dict) -> dict:
    """Overlay only missing scan values with source-backed AI evidence."""
    out = dict(row or {})
    code = str(out.get("market") or "").upper()
    if not code:
        return out
    fields = _ai_field_map(project_id, code)
    recovered = []
    history_rec = fields.get("trade.history")
    history = history_rec.get("value") if history_rec else None
    if isinstance(history, list) and history:
        clean = []
        for item in history:
            if not isinstance(item, dict):
                continue
            try:
                yr = int(str(item.get("year"))[:4])
            except Exception:
                continue
            try:
                total = float(item.get("total_imports")) if item.get("total_imports") is not None else None
            except Exception:
                total = None
            try:
                origin = float(item.get("imports_from_origin")) if item.get("imports_from_origin") is not None else None
            except Exception:
                origin = None
            if total is not None or origin is not None:
                clean.append({"year": yr, "trade_value": total, "origin_value": origin})
        if clean:
            clean.sort(key=lambda x: x["year"])
            metrics = compute_growth_metrics([{"year": x["year"], "trade_value": x.get("trade_value")} for x in clean])
            latest = next((x for x in reversed(clean) if x.get("trade_value") is not None), None)
            if out.get("latest_year") is None and latest:
                out["latest_year"] = latest["year"]
            if out.get("imports") is None and latest:
                out["imports"] = latest.get("trade_value"); recovered.append("imports")
            if out.get("origin_imports") is None and latest and latest.get("origin_value") is not None:
                out["origin_imports"] = latest.get("origin_value"); recovered.append("origin_imports")
            if out.get("origin_share") is None and latest and latest.get("trade_value") not in (None, 0) and latest.get("origin_value") is not None:
                out["origin_share"] = latest["origin_value"] / latest["trade_value"]; recovered.append("origin_share")
            if out.get("yoy") is None and metrics.get("yoy") is not None:
                out["yoy"] = metrics.get("yoy"); recovered.append("yoy")
            if out.get("cagr") is None and metrics.get("cagr") is not None:
                out["cagr"] = metrics.get("cagr"); recovered.append("cagr")
    mappings = {
        "trade.latest_total_imports": "imports",
        "trade.latest_imports_from_origin": "origin_imports",
        "trade.latest_origin_share": "origin_share",
    }
    for field, target in mappings.items():
        if out.get(target) is None and fields.get(field) and fields[field].get("value") is not None:
            try:
                val = float(fields[field]["value"])
                if target == "origin_share" and val > 1:
                    val /= 100
                out[target] = val; recovered.append(target)
            except Exception:
                pass
    if out.get("imports") is not None:
        out["available"] = True
    if recovered:
        out["ai_recovered_fields"] = sorted(set(recovered))
        out["source"] = "AI source-backed evidence" if out.get("source") in (None, "", "UN Comtrade") and not row.get("available") else out.get("source")
    return out


def _missing_recovery_requests(project: dict, market: str, snapshot: dict | None, allowed: list[str]) -> list[str]:
    """Return real data gaps, based on values rather than source-card presence.

    A registered source such as ``HMRC VAT`` is only a pointer.  It does not make
    VAT complete until an actual rate exists (or the user has explicitly supplied
    a manual override).  The same rule applies to tariff references/local codes.
    """
    code = str(market or "").upper()
    snap = snapshot or {}
    trade = snap.get("trade") or {}
    suppliers = snap.get("suppliers") or {}
    tariff = snap.get("tariff") or {}
    official = snap.get("tariff_official_lookup") or {}
    tax = snap.get("tax") or {}
    fx = snap.get("fx") or {}
    missing: list[str] = []

    if "trade" in allowed:
        has_total = trade.get("latest_total_imports") is not None
        has_origin_share = trade.get("latest_origin_share") is not None
        has_supply = bool(suppliers.get("suppliers"))
        if not (has_total and has_origin_share and has_supply):
            missing.append("trade")

    if "tariff" in allowed:
        manual_tariff = get_tariff_override(code, _hs6(project.get("hs_code")))
        has_rate = bool(manual_tariff) or tariff.get("rate") is not None
        confirmed = ''.join(ch for ch in str(project.get("hs_code") or '') if ch.isalnum())
        has_local_code = len(confirmed) > 6 or bool(official.get("local_code") or tariff.get("nomenclature"))
        if not (has_rate and has_local_code):
            missing.append("tariff")

    if "tax" in allowed:
        # A source label/URL is not a tax value.  Only a rate or a user-confirmed
        # override closes this gap.  This fixes the false green "data complete"
        # state seen when HMRC VAT was identified but the rate was blank.
        if not get_tax_override(code) and tax.get("rate") is None:
            missing.append("tax")

    if "fx" in allowed and fx.get("rate") is None:
        missing.append("fx")
    if "marketplace" in allowed and _research_benchmark(project, code) is None:
        missing.append("marketplace")
    if "market_access" in allowed and not list_ai_evidence(int(project.get("id") or 0), code, "market_access"):
        missing.append("market_access")
    if "origin_supply" in allowed:
        # Origin export capacity / target-market corridors are project-level data.
        # A tariff matrix row is not a substitute for this profile.  This fixes
        # the false green state shown while both supply panels still said "No data".
        supply_profile = get_supply_profile(int(project.get("id") or 0)) if project.get("id") else None
        supply_ok = bool(supply_profile)
        if supply_ok:
            profile_hs = _hs6(supply_profile.get("hs6") or supply_profile.get("hs_code"))
            project_hs = _hs6(project.get("hs_code"))
            expected_origin = str((project.get("attributes") or {}).get("origin_partner_code") or "").lstrip("0")
            profile_origin = str((supply_profile.get("origin") or {}).get("code") or supply_profile.get("origin_code") or "").lstrip("0")
            corridor_markets = {str(x.get("market") or "").upper() for x in (supply_profile.get("target_corridors") or []) if x.get("market")}
            selected_markets = {str(x).upper() for x in (project.get("markets") or [])}
            supply_ok = (not project_hs or profile_hs == project_hs) and (not expected_origin or profile_origin == expected_origin) and selected_markets.issubset(corridor_markets)
        if not supply_ok:
            missing.append("origin_supply")
    return list(dict.fromkeys(missing))



def _ai_recovery_plan(project: dict, *, scope: str = "all", market_codes: list[str] | None = None) -> dict:
    """Pure local preflight. It never calls the configured model provider."""
    allowed = _AI_SCOPE_MAP.get(scope, _AI_SCOPE_MAP["all"])
    hs = _hs6(project.get("hs_code"))
    if len(hs) < 6:
        return {"project_id":project.get("id"),"scope":scope,"status":"needs_hs","markets":[],"summary":{"markets":0,"with_gaps":0,"categories":0,"max_model_calls":0}}
    attrs=project.get("attributes") or {}
    origin_code=str(attrs.get("origin_partner_code") or "") or None
    codes=[str(x).upper() for x in (market_codes or project.get("markets") or []) if str(x).upper() in MARKETS]
    codes=list(dict.fromkeys(codes))
    caps=recovery_capabilities();native=bool(caps.get("native_web_search"))
    rows=[];category_count=0;call_count=0
    for code in codes:
        snap=latest_snapshot(code,hs,origin_code=origin_code)
        missing=_missing_recovery_requests(project,code,snap,allowed)
        recoverable=[];unsupported=[]
        meta=source_meta(code)
        for item in missing:
            if item == "origin_supply":
                # This gap has a deterministic in-product recovery path (the
                # "Sync supply evidence" button).  Do not spend model tokens on it.
                unsupported.append(item);continue
            if native:
                recoverable.append(item);continue
            if item=="tariff" and meta.get("tariff_url"):
                recoverable.append(item);continue
            if item=="tax" and meta.get("tax_url"):
                recoverable.append(item);continue
            unsupported.append(item)
        if recoverable:
            call_count += 1
            category_count += len(recoverable)
        rows.append({"market":code,"missing":missing,"recoverable":recoverable,"unsupported":unsupported,"model_calls":1 if recoverable else 0})
    return {
        "project_id":project.get("id"),"scope":scope,
        "status":"complete" if not any(r["missing"] for r in rows) else "ready" if call_count else "unsupported",
        "markets":rows,
        "summary":{"markets":len(codes),"with_gaps":sum(1 for r in rows if r["missing"]),"categories":category_count,"max_model_calls":call_count},
        "capabilities":caps,
    }

def _recover_project_scope(project: dict, *, scope: str = "all", market_codes: list[str] | None = None) -> dict:
    plan=_ai_recovery_plan(project,scope=scope,market_codes=market_codes)
    if plan.get("status")=="needs_hs":
        return {"project_id":project.get("id"),"scope":scope,"status":"needs_hs","markets":[],"summary":{"markets":0,"requested":0,"recoverable":0,"complete":0,"saved":0,"applied":0,"prices":0,"failures":0,"no_evidence":0,"unsupported":0,"model_calls":0,"total_tokens":0}}
    hs=_hs6(project.get("hs_code"));attrs=project.get("attributes") or {};origin_code=str(attrs.get("origin_partner_code") or "") or None
    plan_rows={r["market"]:r for r in plan.get("markets") or []}
    requested_codes=list(plan_rows)
    results=[]

    def one(code: str):
        row=plan_rows[code];missing=row.get("missing") or [];recoverable=row.get("recoverable") or []
        if not missing:
            return {"market":code,"status":"complete","requested":[],"recoverable":[],"saved":0,"applied":0,"marketplace_observations":0,"errors":[],"model_calls":0,"usage":{"total_tokens":0}}
        if not recoverable:
            return {"market":code,"status":"unsupported","requested":missing,"recoverable":[],"unsupported":row.get("unsupported") or missing,"saved":0,"applied":0,"marketplace_observations":0,"errors":[],"model_calls":0,"usage":{"total_tokens":0}}
        snapshot=latest_snapshot(code,hs,origin_code=origin_code)
        try:
            result=recover_market(project,snapshot,code,requested=recoverable)
            return {**result,"requested":missing,"recoverable":recoverable,"unsupported":row.get("unsupported") or []}
        except Exception as exc:
            return {"market":code,"status":"failed","requested":missing,"recoverable":recoverable,"unsupported":row.get("unsupported") or [],"saved":0,"applied":0,"marketplace_observations":0,"errors":[str(exc)],"model_calls":1,"usage":{"total_tokens":0}}

    runnable=[code for code in requested_codes if (plan_rows[code].get("recoverable") or [])]
    static=[code for code in requested_codes if code not in runnable]
    for code in static:
        results.append(one(code))
    if runnable:
        with ThreadPoolExecutor(max_workers=min(2,len(runnable))) as pool:
            results.extend(list(pool.map(one,runnable)))
    order={code:i for i,code in enumerate(requested_codes)};results.sort(key=lambda r:order.get(r.get("market"),9999))
    summary={
        "markets":len(requested_codes),
        "requested":sum(1 for r in results if r.get("requested")),
        "recoverable":sum(1 for r in results if r.get("recoverable")),
        "complete":sum(1 for r in results if r.get("status")=="complete"),
        "saved":sum(int(r.get("saved") or 0) for r in results),
        "applied":sum(int(r.get("applied") or 0) for r in results),
        "prices":sum(int(r.get("marketplace_observations") or 0) for r in results),
        "failures":sum(1 for r in results if r.get("status")=="failed"),
        "no_evidence":sum(1 for r in results if r.get("status")=="no_evidence"),
        "unsupported":sum(1 for r in results if r.get("status")=="unsupported"),
        "model_calls":sum(int(r.get("model_calls") or 0) for r in results),
        "total_tokens":sum(int((r.get("usage") or {}).get("total_tokens") or 0) for r in results),
    }
    if summary["requested"]==0:
        status="complete"
    elif summary["saved"]+summary["prices"]>0:
        status="recovered" if summary["failures"]==0 and summary["no_evidence"]==0 else "partial"
    elif summary["recoverable"]==0:
        status="unsupported"
    elif summary["failures"]:
        status="failed"
    else:
        status="no_evidence"
    return {"project_id":project.get("id"),"scope":scope,"status":status,"markets":results,"summary":summary,"plan":plan.get("summary") or {}}


@app.get("/api/ai/status")
def ai_status_route():
    return {**ai_status(), "recovery": recovery_capabilities(), "research": research_capabilities()}


@app.get("/api/projects/{project_id}/ai/plan")
def ai_recovery_plan_route(
    project_id: int,
    scope: str = Query(default="all", pattern="^(all|market_scan|explorer|trade|tariff|marketplace|cost|backbone)$"),
    market_codes: str | None = Query(default=None, max_length=2500),
):
    project=get_project(project_id)
    if not project:
        raise HTTPException(status_code=404,detail="Project not found")
    caps=recovery_capabilities()
    if not caps.get("configured"):
        raise HTTPException(status_code=422,detail="Model API is not configured")
    codes=[x.strip().upper() for x in str(market_codes or "").split(",") if x.strip()] or None
    return _ai_recovery_plan(project,scope=scope,market_codes=codes)


@app.get("/api/projects/{project_id}/ai/evidence")
def ai_evidence_list(project_id: int, market: str | None = None):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "records": list_ai_evidence(project_id, market), "runs": list_ai_recovery_runs(project_id, market)}


@app.post("/api/projects/{project_id}/ai/recover")
def ai_recover_market(project_id: int, market: str, requested: str = "tariff,tax,trade,fx,market_access,marketplace"):
    """Single-market recovery with the same free gap guard used by the UI.

    Even direct API callers cannot force a paid model request for fields that are
    already complete. Unsupported gaps also return without calling the model.
    """
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    code = str(market or "").upper()
    if code not in MARKETS:
        raise HTTPException(status_code=422, detail="Unknown market code")
    caps = recovery_capabilities()
    if not caps.get("configured"):
        raise HTTPException(status_code=422, detail="Model API is not configured")
    hs = _hs6(project.get("hs_code"))
    origin_code = str((project.get("attributes") or {}).get("origin_partner_code") or "") or None
    snapshot = latest_snapshot(code, hs, origin_code=origin_code) if hs else None
    kinds = list(dict.fromkeys(x.strip() for x in str(requested or "").split(",") if x.strip()))
    missing = _missing_recovery_requests(project, code, snapshot, kinds)
    if not missing:
        return {"project_id":project_id,"market":code,"status":"complete","requested":[],"saved":0,"applied":0,"marketplace_observations":0,"model_calls":0,"usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0}}
    native = bool(caps.get("native_web_search"))
    meta = source_meta(code)
    recoverable = [x for x in missing if native or (x=="tariff" and meta.get("tariff_url")) or (x=="tax" and meta.get("tax_url"))]
    if not recoverable:
        return {"project_id":project_id,"market":code,"status":"unsupported","requested":missing,"recoverable":[],"saved":0,"applied":0,"marketplace_observations":0,"model_calls":0,"usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0}}
    try:
        return recover_market(project, snapshot, code, requested=recoverable)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI evidence recovery failed: {exc}") from exc



@app.post("/api/projects/{project_id}/ai/recover-all")
def ai_recover_project(
    project_id: int,
    scope: str = Query(default="all", pattern="^(all|market_scan|explorer|trade|tariff|marketplace|cost|backbone)$"),
    market_codes: str | None = Query(default=None, max_length=2500),
):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    caps = recovery_capabilities()
    if not caps.get("configured"):
        raise HTTPException(status_code=422, detail="Model API is not configured")
    codes = [x.strip().upper() for x in str(market_codes or "").split(",") if x.strip()] or None
    return _recover_project_scope(project, scope=scope, market_codes=codes)


@app.get("/api/portfolio/ai/plan")
def ai_recover_portfolio_plan(batch_id: str | None = None):
    caps=recovery_capabilities()
    if not caps.get("configured"):
        raise HTTPException(status_code=422,detail="Model API is not configured")
    projects=list_projects()
    if batch_id:
        projects=[p for p in projects if str((p.get("attributes") or {}).get("portfolio_batch_id") or "")==str(batch_id)]
    projects=[p for p in projects if p.get("markets") and len(_hs6(p.get("hs_code")))>=6][:100]
    plans=[_ai_recovery_plan(p,scope="all") for p in projects]
    return {
        "batch_id":batch_id,"projects":len(projects),"plans":plans,
        "summary":{
            "projects_with_gaps":sum(1 for x in plans if (x.get("summary") or {}).get("with_gaps")),
            "categories":sum(int((x.get("summary") or {}).get("categories") or 0) for x in plans),
            "max_model_calls":sum(int((x.get("summary") or {}).get("max_model_calls") or 0) for x in plans),
        }
    }


@app.post("/api/portfolio/ai/recover")
def ai_recover_portfolio(batch_id: str | None = None):
    caps = recovery_capabilities()
    if not caps.get("configured"):
        raise HTTPException(status_code=422, detail="Model API is not configured")
    projects = list_projects()
    if batch_id:
        projects = [p for p in projects if str((p.get("attributes") or {}).get("portfolio_batch_id") or "") == str(batch_id)]
    projects = [p for p in projects if p.get("markets") and len(_hs6(p.get("hs_code"))) >= 6]
    results = []
    # Portfolio recovery is deliberately serialized at the project level. Each
    # project already limits market concurrency to two, preventing a bulk upload
    # from flooding the configured model provider.
    for project in projects[:100]:
        results.append(_recover_project_scope(project, scope="all"))
    summary = {
        "projects": len(results),
        "markets": sum(int((r.get("summary") or {}).get("markets") or 0) for r in results),
        "saved": sum(int((r.get("summary") or {}).get("saved") or 0) for r in results),
        "applied": sum(int((r.get("summary") or {}).get("applied") or 0) for r in results),
        "prices": sum(int((r.get("summary") or {}).get("prices") or 0) for r in results),
        "failures": sum(int((r.get("summary") or {}).get("failures") or 0) for r in results),
        "model_calls": sum(int((r.get("summary") or {}).get("model_calls") or 0) for r in results),
        "total_tokens": sum(int((r.get("summary") or {}).get("total_tokens") or 0) for r in results),
    }
    return {"batch_id": batch_id, "results": results, "summary": summary}


@app.get("/api/projects/{project_id}/ai/brief")
def ai_brief_get(project_id: int, market: str, locale: str = "en"):
    brief=get_ai_brief(project_id,market)
    wanted="zh" if str(locale).lower().startswith("zh") else "en"
    if brief and brief.get("language") not in (None,wanted):
        brief=None
    return {"brief":brief}


@app.post("/api/projects/{project_id}/ai/brief")
def ai_brief_generate(project_id: int, market: str, locale: str = "en"):
    project=get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    code=market.upper()
    if code not in project.get("markets",[]):
        raise HTTPException(status_code=422, detail="Market is not selected for this project")
    hs=_hs6(project.get("hs_code"))
    origin_code=str((project.get("attributes") or {}).get("origin_partner_code") or "") or None
    snap=latest_snapshot(code,hs,origin_code=origin_code) if hs else None
    contract=contract_from_snapshot(snap,code)
    tax_override=get_tax_override(code)
    if tax_override:
        contract["tax"]={"rate":tax_override.get("rate"),"source":"Verified manual tax","reference_year":tax_override.get("reference_year"),"note":tax_override.get("note"),"updated_at":tax_override.get("updated_at"),"status":"verified_manual","official_url":source_meta(code).get("tax_url")}
    decisions=project_decision_cases(project_id)["cases"]
    decision=next((x for x in decisions if x.get("market")==code),{"market":code,"status":"INSUFFICIENT_EVIDENCE"})
    try:
        result=generate_evidence_brief(product=project,market_contract=contract,decision=decision,language=locale)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI brief failed: {exc}") from exc
    return {"brief":save_ai_brief(project_id,code,result)}


@app.get("/api/projects/{project_id}/ai/research")
def ai_research_get(project_id: int, market: str, locale: str = "en"):
    saved=get_ai_brief(project_id,market)
    wanted="zh" if str(locale).lower().startswith("zh") else "en"
    if saved and (saved.get("mode") != "decision-research-agent" or saved.get("language") not in (None,wanted) or not report_matches_language(saved, wanted)):
        saved=None
    return {"research":saved,"capabilities":research_capabilities()}


@app.post("/api/projects/{project_id}/ai/research")
def ai_research_generate(project_id: int, market: str, locale: str = "en"):
    project=get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    code=market.upper()
    if code not in project.get("markets",[]):
        raise HTTPException(status_code=422, detail="Market is not selected for this project")
    hs=_hs6(project.get("hs_code"))
    origin_code=str((project.get("attributes") or {}).get("origin_partner_code") or "") or None
    snap=latest_snapshot(code,hs,origin_code=origin_code) if hs else None
    contract=contract_from_snapshot(snap,code)
    tax_override=get_tax_override(code)
    if tax_override:
        contract["tax"]={"rate":tax_override.get("rate"),"source":"Verified manual tax","reference_year":tax_override.get("reference_year"),"note":tax_override.get("note"),"updated_at":tax_override.get("updated_at"),"status":"verified_manual","official_url":source_meta(code).get("tax_url")}
    decisions=project_decision_cases(project_id)["cases"]
    decision=next((x for x in decisions if x.get("market")==code),{"market":code,"status":"INSUFFICIENT_EVIDENCE"})
    evidence=list_ai_evidence(project_id,code)
    market_cfg=MARKETS.get(code) or {}
    market_name=(market_cfg.get("label_zh") if str(locale).lower().startswith("zh") else market_cfg.get("label")) or market_cfg.get("label") or code
    try:
        result=generate_decision_research(
            project=project, market_code=code, market_name=market_name, market_contract=contract,
            decision=decision, existing_evidence=evidence, language=locale,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI decision research failed: {exc}") from exc
    return {"research":save_ai_brief(project_id,code,result),"capabilities":research_capabilities()}


@app.post("/api/pricing/calculate")
def pricing(req: PricingRequest):
    try:
        return calculate_pricing(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/data/trade")
def trade(
    reporter: str = Query(..., description="UN Comtrade numeric reporter code"),
    hs: str = Query(..., min_length=2, max_length=6),
    period: str = Query(..., description="Annual period (YYYY)"),
    partner: str = Query("0", description="UN Comtrade partner code; 0 means World"),
):
    try:
        rows = fetch_imports(reporter_code=reporter, hs_code=hs, period=period, partner_code=partner)
        return {"summary": summarize_imports(rows), "rows": rows, "source": "UN Comtrade"}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"UN Comtrade request failed: {exc}") from exc


@app.get("/api/data/trade/history")
def trade_history(
    reporter: str,
    hs: str,
    start_year: int | None = Query(default=None, ge=1988, le=2100),
    end_year: int | None = Query(default=None, ge=1988, le=2100),
    partner: str = "0",
):
    runtime_end = end_year if end_year is not None else datetime.now().year - 1
    runtime_start = start_year if start_year is not None else max(1988, runtime_end - 4)
    if runtime_end < runtime_start or runtime_end - runtime_start > 10:
        raise HTTPException(status_code=422, detail="Use a year range of 0 to 10 years.")
    years = list(range(runtime_start, runtime_end + 1))
    try:
        history = fetch_import_history(reporter_code=reporter, hs_code=hs, years=years, partner_code=partner)
        return {
            "history": history,
            "metrics": compute_growth_metrics(history),
            "source": "UN Comtrade",
            "mode": "free-key" if settings.comtrade_subscription_key else "public-preview",
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"UN Comtrade history request failed: {exc}") from exc


@app.get("/api/data/tariff")
def tariff(reporter: str, hs: str, year: str, partner: str = "000"):
    try:
        return fetch_tariff(reporter_code=reporter, partner_code=partner, hs_code=hs, year=year)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"WITS request failed: {exc}") from exc


@app.get("/api/data/tariff/override")
def tariff_override_get(market: str, hs: str):
    return {"override": get_tariff_override(market, hs)}


@app.post("/api/data/tariff/override")
def tariff_override_save(req: TariffOverrideRequest):
    if req.market.upper() not in MARKETS:
        raise HTTPException(status_code=422, detail="Unknown market code")
    return {
        "override": save_tariff_override(
            market=req.market,
            hs_code=req.hs_code,
            rate=req.rate,
            reference_year=req.reference_year,
            note=req.note,
        )
    }


@app.delete("/api/data/tariff/override")
def tariff_override_delete(market: str, hs: str):
    return {"deleted": delete_tariff_override(market, hs)}


@app.get("/api/data/fx")
def fx(currency: str, start_period: str | None = None):
    try:
        return fetch_eur_reference_rate(currency, start_period)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ECB request failed: {exc}") from exc


@app.get("/api/data/fx/convert")
def fx_convert(amount: float, from_currency: str, to_currency: str, start_period: str | None = None):
    try:
        return convert(amount, from_currency, to_currency, start_period)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ECB request failed: {exc}") from exc


def _coverage_block(*, years: list[int], world_history: list[dict], origin_history: list[dict], tariff_result: dict | None, fx_result: dict | None) -> dict:
    world_available = [int(r["year"]) for r in world_history if r.get("trade_value") is not None]
    origin_available = [int(r["year"]) for r in origin_history if r.get("trade_value") is not None]
    missing_world = [y for y in years if y not in world_available]
    missing_origin = [y for y in years if y not in origin_available]
    common = sorted(set(world_available) & set(origin_available))

    trade_world_status = "full" if not missing_world else "partial" if world_available else "missing"
    trade_origin_status = "full" if not missing_origin else "partial" if origin_available else "missing"
    if tariff_result and tariff_result.get("rate") is not None:
        tariff_status = "override" if tariff_result.get("override_used") else "fallback" if tariff_result.get("fallback_used") else "live"
    else:
        tariff_status = "missing"
    fx_status = "live" if fx_result and fx_result.get("rate") is not None else "missing"

    if trade_world_status == "full" and trade_origin_status == "full" and tariff_status != "missing" and fx_status == "live":
        overall = "full"
    elif world_available:
        overall = "partial"
    else:
        overall = "insufficient"

    return {
        "overall": overall,
        "requested_years": years,
        "requested_count": len(years),
        "world": {
            "status": trade_world_status,
            "available_years": world_available,
            "missing_years": missing_world,
            "coverage_ratio": round(len(world_available) / len(years), 4) if years else 0,
        },
        "origin": {
            "status": trade_origin_status,
            "available_years": origin_available,
            "missing_years": missing_origin,
            "coverage_ratio": round(len(origin_available) / len(years), 4) if years else 0,
        },
        "common_years": common,
        "tariff_status": tariff_status,
        "fx_status": fx_status,
    }


@app.get("/api/reference/partners")
def partner_reference_search(q: str = Query(..., min_length=1, max_length=120), limit: int = Query(12, ge=1, le=50)):
    try:
        return {"query": q, "items": search_partners(q, limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"UN Comtrade partner reference failed: {exc}") from exc


@app.get("/api/data/market/screen")
def market_screen(
    hs: str = Query(..., min_length=2, max_length=14),
    origin: str = Query(default="", max_length=120),
    year: int | None = Query(default=None, ge=1988, le=2100),
    lookback_years: int = Query(default=3, ge=1, le=5),
    market_codes: str | None = Query(default=None, max_length=2000),
):
    """Source-backed market screen with demand, trend, origin share and coverage.

    The endpoint does not create a synthetic attractiveness score. It returns
    comparable evidence dimensions so the user can rank or filter transparently.
    """
    hs = _hs6(hs)
    if not hs:
        raise HTTPException(status_code=422, detail="Enter a valid HS code before market screening.")
    screening_year = int(year or (datetime.now(timezone.utc).year - 1))
    years = list(range(max(1988, screening_year - lookback_years + 1), screening_year + 1))
    origin_ref = None
    if origin.strip():
        try:
            origin_ref = resolve_partner(origin)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not load UN Comtrade country reference: {exc}") from exc
    started = perf_counter()

    def one_market(code: str, cfg: dict) -> dict:
        try:
            world = fetch_import_history_compact(
                reporter_code=str(cfg["reporter"]), hs_code=hs, years=years, partner_code="0"
            )
            # Avoid a second network query when the market has no observed world
            # import evidence in the requested window.
            world_has_data = any(x.get("trade_value") is not None for x in world)
            origin_hist = fetch_import_history_compact(
                reporter_code=str(cfg["reporter"]), hs_code=hs, years=years, partner_code=origin_ref["code"]
            ) if origin_ref and world_has_data else []
            metrics = compute_growth_metrics(world)
            origin_by_year = {int(x["year"]): x.get("trade_value") for x in origin_hist if x.get("trade_value") is not None}
            latest_year = metrics.get("latest_year")
            latest_imports = metrics.get("latest_value")
            origin_imports = origin_by_year.get(int(latest_year)) if latest_year is not None else None
            origin_share = origin_imports / latest_imports if latest_imports not in (None, 0) and origin_imports is not None else None
            available = [x["year"] for x in world if x.get("trade_value") is not None]
            return {
                "market": code,
                "label": cfg["label"],
                "currency": cfg["currency"],
                "requested_years": years,
                "latest_year": latest_year,
                "imports": latest_imports,
                "yoy": metrics.get("yoy"),
                "cagr": metrics.get("cagr"),
                "origin_imports": origin_imports,
                "origin_share": origin_share,
                "coverage_ratio": len(available) / len(years) if years else 0,
                "available_years": available,
                "available": latest_imports is not None,
                "source": "UN Comtrade",
                "error": None,
            }
        except Exception as exc:
            return {
                "market": code, "label": cfg["label"], "currency": cfg["currency"],
                "requested_years": years, "latest_year": None, "imports": None, "yoy": None,
                "cagr": None, "origin_imports": None, "origin_share": None, "coverage_ratio": 0,
                "available_years": [], "available": False, "source": "UN Comtrade", "error": str(exc),
            }

    requested_codes = [x.strip().upper() for x in str(market_codes or "").split(",") if x.strip()]
    if requested_codes:
        market_items = [(code, MARKETS[code]) for code in requested_codes if code in MARKETS and MARKETS[code].get("trade_supported", True)]
    else:
        market_items = [(code, cfg) for code, cfg in MARKETS.items() if cfg.get("featured") and cfg.get("trade_supported", True)]
    if not market_items:
        raise HTTPException(status_code=422, detail="No trade-supported markets were selected for screening.")

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(3, len(market_items))) as pool:
        futures = [pool.submit(one_market, code, cfg) for code, cfg in market_items]
        for future in futures:
            rows.append(future.result())

    rows.sort(key=lambda x: (x.get("imports") is not None, x.get("imports") or 0), reverse=True)
    return {
        "hs_code": hs,
        "origin": origin_ref,
        "requested_years": years,
        "markets": rows,
        "source": "UN Comtrade",
        "method": "multi-dimensional evidence; sorted by latest reported import value; no synthetic market score",
        "duration_ms": int((perf_counter() - started) * 1000),
    }


@app.get("/api/projects/{project_id}/market-scan")
def project_market_scan_cached(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    cached = get_market_scan(project_id)
    if not cached:
        return {"cached": False, "scan": None}
    current_hs = _hs6(project.get("hs_code"))
    cached_hs = _hs6(cached.get("hs_code"))
    cached_origin = str((cached.get("origin") or {}).get("name") or "").strip().lower()
    current_origin = str(project.get("origin") or "").strip().lower()
    stale = current_hs != cached_hs or (current_origin and cached_origin and current_origin != cached_origin)
    visible_scan = dict(cached)
    visible_scan["markets"] = [_overlay_scan_row(project_id, row) for row in (cached.get("markets") or [])]
    return {"cached": True, "stale": stale, "scan": visible_scan}


@app.post("/api/projects/{project_id}/market-scan")
def project_market_scan_run(
    project_id: int,
    year: int | None = Query(default=None, ge=1988, le=2100),
    lookback_years: int = Query(default=3, ge=1, le=5),
):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    if not hs:
        raise HTTPException(status_code=422, detail="Confirm an HS code before market screening.")
    selected_codes = [str(x).upper() for x in (project.get("markets") or []) if str(x).upper() in MARKETS]
    market_codes = ",".join(selected_codes) if selected_codes else None
    result = market_screen(hs=hs, origin=str(project.get("origin") or ""), year=year, lookback_years=lookback_years, market_codes=market_codes)
    result["scanned_at"] = datetime.now(timezone.utc).isoformat()
    saved = save_market_scan(project_id, result)
    visible = dict(saved)
    visible["markets"] = [_overlay_scan_row(project_id, row) for row in (saved.get("markets") or [])]
    return visible


@app.delete("/api/projects/{project_id}/market-scan")
def project_market_scan_clear(project_id: int):
    return {"deleted": delete_market_scan(project_id)}


@app.get("/api/projects/{project_id}/supply")
def project_supply_cached(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    payload = get_supply_profile(project_id)
    return {"cached": bool(payload), "profile": payload}


@app.post("/api/projects/{project_id}/supply/sync")
def project_supply_sync(
    project_id: int,
    end_year: int | None = Query(default=None, ge=1988, le=2100),
    lookback_years: int = Query(default=4, ge=2, le=8),
):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    if len(hs) < 6:
        raise HTTPException(status_code=422, detail="Confirm an HS6 code before supply research.")
    attrs = project.get("attributes") or {}
    origin_code = str(attrs.get("origin_partner_code") or "").strip()
    origin_name = str(project.get("origin") or "").strip()
    origin_ref = {"code": origin_code, "name": origin_name} if origin_code else None
    if not origin_ref:
        try:
            origin_ref = resolve_partner(origin_name)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not load UN Comtrade country reference: {exc}") from exc
    if not origin_ref:
        raise HTTPException(status_code=422, detail="Origin could not be resolved to a UN Comtrade reporter code.")
    last_year = int(end_year or (datetime.now(timezone.utc).year - 1))
    years = list(range(max(1988, last_year - lookback_years + 1), last_year + 1))
    try:
        payload = build_supply_profile(origin=origin_ref, hs6=hs, years=years, target_markets=list(project.get("markets") or []))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"UN Comtrade supply research failed: {exc}") from exc
    return save_supply_profile(project_id, payload)


@app.get("/api/projects/{project_id}/supply-network")
def project_supply_network(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    if len(hs) < 6:
        raise HTTPException(status_code=422, detail="Confirm an HS6 code before supply-network analysis.")
    origin_code = str(_safe_mapping(project.get("attributes")).get("origin_partner_code") or "") or None
    blocks = []
    for market in project.get("markets") or []:
        try:
            snap = _safe_mapping(latest_snapshot(market, hs, origin_code=origin_code))
        except Exception:
            snap = {}
        suppliers = _safe_mapping(snap.get("suppliers"))
        if suppliers.get("suppliers"):
            blocks.append({"market": market, "label": _safe_mapping(MARKETS.get(market)).get("label") or market, "suppliers": suppliers.get("suppliers")})
    result = analyze_trade_network(blocks)
    return {"project_id": project_id, "hs6": hs, "observed_markets": [b["market"] for b in blocks], **result}


@app.get("/api/tariff-matrix")
def tariff_matrix_cached(
    hs: str = Query(..., min_length=2, max_length=14),
    origin_code: str = Query(default="", max_length=12),
    year: int | None = Query(default=None, ge=1988, le=2100),
    market_codes: str | None = Query(default=None, max_length=2500),
    project_id: int | None = Query(default=None, ge=1),
):
    hs6 = _hs6(hs)
    if len(hs6) < 6:
        raise HTTPException(status_code=422, detail="Confirm an HS6 code before tariff matrix research.")
    codes = [x.strip().upper() for x in str(market_codes or "").split(",") if x.strip()] or None
    normalized_origin = str(origin_code or "").zfill(3) if str(origin_code or "").strip() else ""
    rows = list_tariff_matrix(hs_code=hs6, origin_code=normalized_origin, requested_year=year, markets=codes)
    if project_id:
        known = {str(r.get("market") or "").upper() for r in rows}
        candidate_markets = codes or sorted(known)
        for code in candidate_markets:
            rec = latest_ai_evidence(project_id, code, "tariff.rate")
            if not rec or rec.get("value") is None:
                continue
            try: ai_rate = float(rec.get("value"))
            except Exception: continue
            row = next((x for x in rows if str(x.get("market") or "").upper() == code), None)
            if row is None:
                row = {"market":code,"label":(MARKETS.get(code) or {}).get("label") or code,"status":"ai_recovered","rate":ai_rate,"year":rec.get("observed_at"),"tariff_type":"AI source-backed","source":rec.get("source_name"),"source_url":rec.get("source_url"),"retrieval_method":rec.get("retrieval_method"),"scanned_at":rec.get("retrieved_at")}
                rows.append(row)
            elif row.get("rate") is None:
                row.update({"status":"ai_recovered","rate":ai_rate,"year":row.get("year") or rec.get("observed_at"),"tariff_type":row.get("tariff_type") or "AI source-backed","source":rec.get("source_name"),"source_url":rec.get("source_url"),"retrieval_method":rec.get("retrieval_method"),"scanned_at":row.get("scanned_at") or rec.get("retrieved_at")})
    return {
        "hs6": hs6,
        "origin_code": normalized_origin,
        "requested_year": year,
        "rows": rows,
        "count": len(rows),
        "source": "UNCTAD TRAINS / WITS",
        "method": "HS6 analytical tariff reference; legal/current local tariff verification remains separate.",
    }


@app.post("/api/projects/{project_id}/tariff-matrix/scan")
def tariff_matrix_scan_start(
    project_id: int,
    year: int | None = Query(default=None, ge=1988, le=2100),
    scope: str = Query(default="selected", pattern="^(selected|global)$"),
):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs6 = _hs6(project.get("hs_code"))
    if len(hs6) < 6:
        raise HTTPException(status_code=422, detail="Confirm an HS6 code before tariff matrix research.")
    attrs = project.get("attributes") or {}
    origin_code = str(attrs.get("origin_partner_code") or "").strip()
    if not origin_code and project.get("origin"):
        try:
            origin_ref = resolve_partner(str(project.get("origin") or ""))
        except Exception:
            origin_ref = None
        origin_code = str((origin_ref or {}).get("code") or "")
    scan_year = int(year or (datetime.now(timezone.utc).year - 1))
    if scope == "global":
        markets = [code for code, cfg in MARKETS.items() if cfg.get("reporter") and cfg.get("trade_supported", True)]
    else:
        markets = [str(code).upper() for code in (project.get("markets") or []) if str(code).upper() in MARKETS and MARKETS[str(code).upper()].get("reporter")]
    if not markets:
        raise HTTPException(status_code=422, detail="No tariff-supported markets are available for this scope.")
    return start_tariff_job(markets=markets, hs6=hs6, origin_code=(origin_code.zfill(3) if origin_code else "000"), year=scan_year)


@app.get("/api/tariff-matrix/jobs/{job_id}")
def tariff_matrix_job_status(job_id: str):
    job = tariff_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tariff matrix job not found")
    return job


@app.get("/api/data/tariff/official")
def tariff_official_lookup(market: str, code: str, origin: str = ""):
    try:
        return lookup_official_tariff(market=market, code=code, origin=origin)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Official tariff lookup failed: {exc}") from exc


@app.get("/api/data/market/sync")
def market_sync(
    market: str,
    reporter: str | None = None,
    currency: str | None = None,
    hs: str = Query(..., min_length=2, max_length=14),
    origin: str = Query(default="", max_length=120),
    start_year: int | None = Query(default=None, ge=1988, le=2100),
    end_year: int | None = Query(default=None, ge=1988, le=2100),
):
    market = market.upper()
    cfg = MARKETS.get(market)
    if cfg is None:
        raise HTTPException(status_code=422, detail="Unknown market code")
    raw_tariff_code = str(hs or "")
    hs = _hs6(hs)
    if not hs:
        raise HTTPException(status_code=422, detail="Enter a valid HS code before market sync.")
    reporter_value = reporter or cfg.get("reporter")
    if not reporter_value:
        raise HTTPException(status_code=422, detail="This country/area is listed for selection but has no UN Comtrade reporter code in the local reference.")
    reporter = str(reporter_value)
    currency_value = currency or cfg.get("currency")
    currency = str(currency_value or "")

    runtime_end = end_year if end_year is not None else datetime.now().year - 1
    runtime_start = start_year if start_year is not None else max(1988, runtime_end - 4)
    if runtime_end < runtime_start or runtime_end - runtime_start > 10:
        raise HTTPException(status_code=422, detail="Use a year range of 0 to 10 years.")

    origin_ref = None
    if origin.strip():
        try:
            origin_ref = resolve_partner(origin)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not load UN Comtrade country reference: {exc}") from exc
        if not origin_ref:
            raise HTTPException(status_code=422, detail="Origin could not be resolved to a UN Comtrade partner code. Use a country/area name or ISO code from the Origin suggestions.")

    origin_partner_code = origin_ref["code"] if origin_ref else None
    tariff_partner_code = str(origin_partner_code).zfill(3) if origin_partner_code else "000"
    started = perf_counter()
    years = list(range(runtime_start, runtime_end + 1))

    with ThreadPoolExecutor(max_workers=5) as pool:
        # Compact multi-period retrieval is substantially more reliable for the
        # interactive workflow than five independent calls. Missing years still
        # fall back to isolated requests inside fetch_import_history_compact.
        world_future = pool.submit(fetch_import_history_compact, reporter_code=reporter, hs_code=hs, years=years, partner_code="0")
        origin_future = pool.submit(fetch_import_history_compact, reporter_code=reporter, hs_code=hs, years=years, partner_code=origin_partner_code) if origin_partner_code else None
        official_tariff_future = pool.submit(lookup_official_tariff, market=market, code=raw_tariff_code, origin=origin_ref["name"] if origin_ref else "")
        fx_future = pool.submit(fetch_eur_reference_rate, currency) if currency else None

        world_history = world_future.result()
        origin_history = origin_future.result() if origin_future else []

        # Interactive market refresh never waits on the WITS host. Reuse a
        # previously observed WITS value only as a historical reference; live
        # WITS refresh is isolated to the background tariff-matrix workflow.
        tariff_result = fetch_tariff_cached(
            reporter_code=reporter, partner_code=tariff_partner_code, hs_code=hs, year=str(runtime_end)
        )
        tariff_error = None

        official_tariff = None
        official_tariff_error = None
        try:
            official_tariff = official_tariff_future.result()
        except Exception as exc:
            official_tariff_error = str(exc)

        # Prefer a uniquely resolved current official rate. Keep WITS/TRAINS as
        # a historical/reference fallback where an official current line cannot
        # be resolved safely from the available code.
        if official_tariff and official_tariff.get("rate") is not None:
            tariff_result = {
                "reporter_code": reporter,
                "partner_code": tariff_partner_code,
                "hs_code": hs,
                "requested_year": str(runtime_end),
                "year": runtime_end,
                "rate": official_tariff.get("rate"),
                "tariff_type": "official current tariff",
                "min_rate": None,
                "max_rate": None,
                "nomenclature": official_tariff.get("local_code"),
                "fallback_used": False,
                "override_used": False,
                "source": official_tariff.get("source"),
                "source_type": official_tariff.get("source_type"),
                "rate_text": official_tariff.get("rate_text"),
                "lookup_url": official_tariff.get("lookup_url"),
                "note": official_tariff.get("note"),
            }

        fx_result = None
        fx_error = None
        try:
            fx_result = fx_future.result() if fx_future else None
        except Exception as exc:
            fx_error = str(exc)

    override = get_tariff_override(market, hs)
    if override:
        tariff_result = {
            "reporter_code": reporter,
            "partner_code": tariff_partner_code,
            "hs_code": hs,
            "requested_year": str(runtime_end),
            "year": override.get("reference_year"),
            "rate": override.get("rate"),
            "tariff_type": "manual override",
            "min_rate": None,
            "max_rate": None,
            "nomenclature": None,
            "fallback_used": False,
            "override_used": True,
            "source": "User override",
            "note": override.get("note"),
            "updated_at": override.get("updated_at"),
        }

    world_metrics = compute_growth_metrics(world_history)
    origin_metrics = compute_growth_metrics(origin_history)

    supplier_result = None
    supplier_error = None
    supplier_year = world_metrics.get("latest_year")
    if supplier_year is not None:
        try:
            supplier_result = fetch_supplier_structure(
                reporter_code=reporter, hs_code=hs, period=str(supplier_year), limit=12
            )
        except Exception as exc:
            supplier_error = str(exc)

    origin_by_year = {int(r["year"]): r.get("trade_value") for r in origin_history if r.get("trade_value") is not None}

    # If bilateral history is missing but the partner-level supplier structure
    # contains the selected origin, use that same-year partner observation for
    # the latest origin value/share. This avoids displaying a blank origin share
    # while the supplier table already contains the evidence.
    supplier_origin_value = None
    supplier_origin_share = None
    if supplier_result and origin_partner_code:
        for supplier in supplier_result.get("suppliers") or []:
            if str(supplier.get("partner_code")) == str(origin_partner_code):
                supplier_origin_value = supplier.get("trade_value")
                supplier_origin_share = supplier.get("share")
                if supplier_result.get("year") is not None and supplier_origin_value is not None:
                    origin_by_year.setdefault(int(supplier_result["year"]), supplier_origin_value)
                break

    combined_history = []
    for row in world_history:
        year = int(row["year"])
        total = row.get("trade_value")
        origin_value = origin_by_year.get(year)
        origin_share = origin_value / total if total not in (None, 0) and origin_value is not None else None
        combined_history.append({
            "year": year,
            "total_imports": total,
            "imports_from_origin": origin_value,
            "origin_share": origin_share,
            "world_ok": bool(row.get("ok")),
            "origin_ok": origin_value is not None,
        })

    latest_year = world_metrics.get("latest_year")
    latest_total = world_metrics.get("latest_value")
    latest_origin = origin_by_year.get(int(latest_year)) if latest_year is not None else None
    latest_share = latest_origin / latest_total if latest_total not in (None, 0) and latest_origin is not None else None
    if latest_share is None and supplier_result and supplier_result.get("year") == latest_year:
        latest_origin = supplier_origin_value if latest_origin is None else latest_origin
        latest_share = supplier_origin_share

    volatility = trade_volatility(combined_history)
    errors = {
        "trade_world": [r for r in world_history if r.get("error")],
        "trade_origin": [r for r in origin_history if r.get("error")],
        "suppliers": supplier_error,
        "tariff": tariff_error,
        "official_tariff": official_tariff_error,
        "fx": fx_error,
    }
    quality = _coverage_block(years=years, world_history=world_history, origin_history=origin_history, tariff_result=tariff_result, fx_result=fx_result)

    payload = {
        "market": market,
        "market_label": cfg["label"],
        "reporter_code": reporter,
        "currency": currency.upper() if currency else None,
        "hs_code": hs,
        "origin": origin_ref,
        "start_year": runtime_start,
        "end_year": runtime_end,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "trade": {
            "history": combined_history,
            "world_metrics": world_metrics,
            "origin_metrics": origin_metrics,
            "latest_year": latest_year,
            "latest_total_imports": latest_total,
            "latest_imports_from_origin": latest_origin,
            "latest_origin_share": latest_share,
            "volatility": volatility,
            "source": "UN Comtrade",
            "mode": "free-key" if settings.comtrade_subscription_key else "public-preview",
        },
        "suppliers": supplier_result,
        "tariff": tariff_result,
        "tariff_official_lookup": official_tariff,
        "fx": fx_result,
        "quality": quality,
        "errors": errors,
        "sync_duration_ms": int((perf_counter() - started) * 1000),
    }
    return save_snapshot(payload)


@app.get("/api/data/snapshots")
def snapshots(hs: str | None = None):
    return {"snapshots": list_snapshots(hs)}


@app.get("/api/data/runtime")
def data_runtime():
    refresh_settings()
    return {
        "sources": source_runtime_summary(),
        "comtrade_mode": "free-key" if settings.comtrade_subscription_key else "public-preview",
        "comtrade_daily_limit": 500 if settings.comtrade_subscription_key else None,
        "comtrade_max_records": 100000 if settings.comtrade_subscription_key else 500,
    }


@app.delete("/api/data/runtime/cache")
def data_runtime_cache_clear(request: Request, provider: str | None = None):
    _require_local_request(request)
    return {"deleted": source_cache_clear(provider)}


def _require_local_request(request: Request) -> None:
    host = (request.client.host if request.client else "").strip().lower()
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Local configuration can only be changed from this computer.")


@app.get("/api/local-config/apis")
def api_local_config_get(request: Request):
    _require_local_request(request)
    refresh_settings()
    return {
        "comtrade": {
            "configured": bool(settings.comtrade_subscription_key),
            "api_key_masked": mask_secret(settings.comtrade_subscription_key),
            "secret_stored": bool(settings.comtrade_subscription_key),
            "config_sources": list(settings.config_sources),
        },
        "ebay": {
            "environment": settings.ebay_env,
            "configured": bool(settings.ebay_client_id and settings.ebay_client_secret),
            "client_id_masked": mask_client_id(settings.ebay_client_id),
            "marketplace_id": settings.ebay_marketplace_id,
            "secret_stored": bool(settings.ebay_client_secret),
            "config_sources": list(settings.config_sources),
        },
        "ai": {
            "configured": bool(settings.ai_protocol and settings.ai_base_url and settings.ai_model),
            "provider": settings.ai_provider,
            "protocol": settings.ai_protocol,
            "base_url": settings.ai_base_url,
            "api_key_masked": mask_secret(settings.ai_api_key),
            "secret_stored": bool(settings.ai_api_key),
            "model": settings.ai_model,
            "config_sources": list(settings.config_sources),
            "recovery": recovery_capabilities(),
            "research": research_capabilities(),
        },
        "research": {
            "provider": settings.web_research_provider,
            "active_provider": research_capabilities().get("active_provider"),
            "tavily_configured": bool(settings.tavily_api_key),
            "api_key_masked": mask_secret(settings.tavily_api_key),
            "base_url": settings.tavily_base_url,
            "capabilities": research_capabilities(),
            "config_sources": list(settings.config_sources),
        },
        "public": {
            "wits": {"configured": True, "credential_required": False},
            "ecb": {"configured": True, "credential_required": False},
            "official_tariff": {"configured": True, "credential_required": False},
        },
        "storage": {"location": ".env", "local_only": True, "restart_required": False},
    }


@app.post("/api/local-config/comtrade/validate")
def comtrade_local_config_validate(req: ComtradeLocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    api_key = (req.api_key or "").strip() or settings.comtrade_subscription_key
    if not api_key:
        raise HTTPException(status_code=422, detail="UN Comtrade API key is not configured")
    try:
        return validate_subscription_key(api_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"UN Comtrade API test failed: {exc}") from exc


@app.post("/api/local-config/comtrade")
def comtrade_local_config_save(req: ComtradeLocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    api_key = (req.api_key or "").strip() or settings.comtrade_subscription_key
    if not api_key:
        raise HTTPException(status_code=422, detail="UN Comtrade API key is required for the first setup.")
    update_local_env({"COMTRADE_SUBSCRIPTION_KEY": api_key})
    refresh_settings()
    return {
        "saved": True,
        "configured": bool(settings.comtrade_subscription_key),
        "api_key_masked": mask_secret(settings.comtrade_subscription_key),
        "config_sources": list(settings.config_sources),
        "restart_required": False,
    }


@app.get("/api/data/comtrade/test")
def comtrade_test():
    refresh_settings()
    if not settings.comtrade_subscription_key:
        raise HTTPException(status_code=422, detail="UN Comtrade API key is not configured")
    try:
        return validate_subscription_key(settings.comtrade_subscription_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"UN Comtrade API test failed: {exc}") from exc


@app.post("/api/local-config/ai/validate")
def ai_local_config_validate(req: ModelAPILocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    overrides = {
        "provider": (req.provider or "").strip() or settings.ai_provider,
        "protocol": (req.protocol or "").strip() or settings.ai_protocol,
        "base_url": (req.base_url or "").strip() or settings.ai_base_url,
        "api_key": (req.api_key or "").strip() or settings.ai_api_key,
        "model": (req.model or "").strip() or settings.ai_model,
    }
    try:
        return test_ai_connection(overrides)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model API test failed: {exc}") from exc


@app.post("/api/local-config/ai")
def ai_local_config_save(req: ModelAPILocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    provider = (req.provider or "").strip() or settings.ai_provider
    protocol = (req.protocol or "").strip() or settings.ai_protocol
    base_url = (req.base_url or "").strip() or settings.ai_base_url
    api_key = (req.api_key or "").strip() or settings.ai_api_key
    model = (req.model or "").strip() or settings.ai_model
    model = normalize_ai_model_id(provider=provider, base_url=base_url, model=model)
    if not protocol:
        raise HTTPException(status_code=422, detail="Model API protocol is required.")
    if not base_url:
        raise HTTPException(status_code=422, detail="API Base URL is required.")
    if not model:
        raise HTTPException(status_code=422, detail="Model ID is required.")
    update_local_env({
        "AI_PROVIDER": provider,
        "AI_PROTOCOL": protocol,
        "AI_BASE_URL": base_url,
        "AI_API_KEY": api_key,
        "AI_MODEL": model,
    })
    return {
        "saved": True,
        "configured": bool(settings.ai_protocol and settings.ai_base_url and settings.ai_model),
        "provider": settings.ai_provider,
        "protocol": settings.ai_protocol,
        "base_url": settings.ai_base_url,
        "api_key_masked": mask_secret(settings.ai_api_key),
        "secret_stored": bool(settings.ai_api_key),
        "model": settings.ai_model,
        "config_sources": list(settings.config_sources),
        "restart_required": False,
    }


@app.post("/api/local-config/ai/models")
def ai_models(req: ModelAPILocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    overrides = {
        "provider": (req.provider or "").strip() or settings.ai_provider,
        "protocol": (req.protocol or "").strip() or settings.ai_protocol,
        "base_url": (req.base_url or "").strip() or settings.ai_base_url,
        "api_key": (req.api_key or "").strip() or settings.ai_api_key,
        "model": (req.model or "").strip() or settings.ai_model,
    }
    try:
        return list_models(overrides)
    except Exception as exc:
        return {
            "configured": False,
            "available": [],
            "selected": overrides["model"],
            "source": "unavailable",
            "provider": overrides["provider"],
            "protocol": overrides["protocol"],
            "warning": str(exc),
        }


@app.get("/api/data/ai/test")
def ai_test():
    refresh_settings()
    try:
        return test_ai_connection()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model API test failed: {exc}") from exc


@app.post("/api/local-config/research/validate")
def research_local_config_validate(req: WebResearchLocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    provider=(req.provider or settings.web_research_provider or "auto").strip().lower()
    if provider == "none":
        return {"ok":True,"provider":"none","message":"Web research disabled"}
    if provider in {"auto","native"}:
        caps=research_capabilities()
        if caps.get("native_available"):
            return {"ok":True,"provider":"native","message":"Provider-native web research is available; no generation request was sent"}
        if provider == "native":
            raise HTTPException(status_code=422, detail="The current model/protocol does not expose provider-native web search")
    if provider in {"auto","tavily"}:
        key=(req.api_key or "").strip() or settings.tavily_api_key
        base=(req.base_url or "").strip() or settings.tavily_base_url
        try:
            return validate_tavily(key,base)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Web research test failed: {exc}") from exc
    return {"ok":True,"provider":"none"}


@app.post("/api/local-config/research")
def research_local_config_save(req: WebResearchLocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    provider=(req.provider or settings.web_research_provider or "auto").strip().lower()
    api_key=(req.api_key or "").strip() or settings.tavily_api_key
    base_url=(req.base_url or "").strip() or settings.tavily_base_url or "https://api.tavily.com"
    update_local_env({
        "WEB_RESEARCH_PROVIDER":provider,
        "TAVILY_API_KEY":api_key,
        "TAVILY_BASE_URL":base_url,
    })
    caps=research_capabilities()
    return {
        "saved":True,"provider":settings.web_research_provider,"active_provider":caps.get("active_provider"),
        "tavily_configured":bool(settings.tavily_api_key),"api_key_masked":mask_secret(settings.tavily_api_key),
        "base_url":settings.tavily_base_url,"capabilities":caps,"restart_required":False,
    }


@app.post("/api/local-config/ebay/validate")
def ebay_local_config_validate(req: EbayLocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    environment = (req.environment or settings.ebay_env or "sandbox").strip().lower()
    client_id = (req.client_id or "").strip() or settings.ebay_client_id
    client_secret = (req.client_secret or "").strip() or settings.ebay_client_secret
    if not client_id or not client_secret:
        raise HTTPException(status_code=422, detail="Client ID and Client Secret are required.")
    try:
        return validate_ebay_connection(
            environment=environment,
            client_id=client_id,
            client_secret=client_secret,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay OAuth validation failed: {exc}") from exc


@app.get("/api/local-config/ebay")
def ebay_local_config_get(request: Request):
    _require_local_request(request)
    refresh_settings()
    return {
        "environment": settings.ebay_env,
        "configured": bool(settings.ebay_client_id and settings.ebay_client_secret),
        "client_id_masked": mask_client_id(settings.ebay_client_id),
        "marketplace_id": settings.ebay_marketplace_id,
        "config_sources": list(settings.config_sources),
        "secret_stored": bool(settings.ebay_client_secret),
    }


@app.post("/api/local-config/ebay")
def ebay_local_config_save(req: EbayLocalConfigRequest, request: Request):
    _require_local_request(request)
    refresh_settings()
    current_id = settings.ebay_client_id
    current_secret = settings.ebay_client_secret
    client_id = (req.client_id or "").strip() or current_id
    client_secret = (req.client_secret or "").strip() or current_secret
    if not client_id or not client_secret:
        raise HTTPException(status_code=422, detail="Client ID and Client Secret are required for the first eBay setup.")
    update_local_env({
        "EBAY_ENV": req.environment,
        "EBAY_CLIENT_ID": client_id,
        "EBAY_CLIENT_SECRET": client_secret,
        "EBAY_MARKETPLACE_ID": (req.marketplace_id or settings.ebay_marketplace_id or "").strip(),
    })
    reset_token_cache()
    return {
        "saved": True,
        "environment": settings.ebay_env,
        "configured": bool(settings.ebay_client_id and settings.ebay_client_secret),
        "client_id_masked": mask_client_id(settings.ebay_client_id),
        "marketplace_id": settings.ebay_marketplace_id,
        "config_sources": list(settings.config_sources),
        "restart_required": False,
    }


@app.get("/api/data/ebay/test")
def ebay_test():
    refresh_settings()
    try:
        return test_ebay_connection()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay OAuth test failed: {exc}") from exc






@app.post("/api/projects/{project_id}/run-analysis")
def project_run_analysis(
    project_id: int,
    start_year: int | None = Query(default=None, ge=1988, le=2100),
    end_year: int | None = Query(default=None, ge=1988, le=2100),
    ai_recovery: bool = Query(default=False),
):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    if not hs:
        raise HTTPException(status_code=422, detail="Confirm an HS code before running market analysis.")
    origin_text = str(project.get("origin") or "").strip()
    if not origin_text:
        raise HTTPException(status_code=422, detail="Confirm the product origin before running market analysis.")
    try:
        origin_ref = resolve_partner(origin_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load UN Comtrade country reference: {exc}") from exc
    if not origin_ref:
        raise HTTPException(status_code=422, detail="Origin could not be resolved. Choose a country/area from the Origin suggestions in Project Setup.")
    attrs = {**(project.get("attributes") or {}), "origin_partner_code": origin_ref["code"], "origin_partner_name": origin_ref["name"], "origin_iso2": origin_ref.get("iso2"), "origin_iso3": origin_ref.get("iso3")}
    project = update_project(project_id, {"origin": origin_ref["name"], "attributes": attrs}) or project
    current_year = datetime.now(timezone.utc).year
    start_year = int(start_year or current_year - 5)
    end_year = int(end_year or current_year - 1)
    selected_markets = [m for m in (project.get("markets") or []) if m in MARKETS]
    if not selected_markets:
        raise HTTPException(status_code=422, detail="Select at least one market before running analysis.")
    if end_year < start_year or end_year - start_year > 10:
        raise HTTPException(status_code=422, detail="Use a year range of 0 to 10 years.")

    started = perf_counter()
    results: list[dict] = []
    errors: list[dict] = []

    def one(code: str):
        try:
            return market_sync(market=code, hs=project.get("hs_code") or hs, origin=origin_ref["name"], start_year=start_year, end_year=end_year)
        except HTTPException as exc:
            return {"market": code, "error": exc.detail}
        except Exception as exc:
            return {"market": code, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=min(4, len(selected_markets))) as pool:
        futures = [pool.submit(one, code) for code in selected_markets]
        for future in futures:
            row = future.result()
            if row.get("error") and not row.get("trade"):
                errors.append(row)
            else:
                results.append(row)

    ai_results = []
    caps = recovery_capabilities()
    if ai_recovery and caps.get("configured") and results:
        def recover_one(row: dict):
            code = str(row.get("market") or "")
            quality = evidence_quality(row)
            requested = list(quality.get("missing") or [])
            mapped = []
            for item in requested:
                if item in {"trade", "origin_trade", "supplier_structure"}: mapped.append("trade")
                elif item == "tariff": mapped.append("tariff")
                elif item == "fx": mapped.append("fx")
            if not get_tax_override(code) and (row.get("tax") or {}).get("rate") is None: mapped.append("tax")
            if _research_benchmark(project, code) is None: mapped.append("marketplace")
            if not list_ai_evidence(project_id, code, "market_access"): mapped.append("market_access")
            mapped = list(dict.fromkeys(mapped))
            if not mapped:
                return None
            try:
                return recover_market(project, row, code, requested=mapped)
            except Exception as exc:
                return {"market": code, "error": str(exc)}
        with ThreadPoolExecutor(max_workers=min(2, len(results))) as recovery_pool:
            for item in recovery_pool.map(recover_one, results):
                if item: ai_results.append(item)

    update_project(project_id, {"status": "active" if results else project.get("status", "draft")})
    return {
        "project_id": project_id,
        "hs6": hs,
        "requested_markets": selected_markets,
        "succeeded": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
        "ai_recovery": ai_results,
        "duration_ms": int((perf_counter() - started) * 1000),
    }


@app.get("/api/ebay/taxonomy/meta")
def ebay_taxonomy_meta(marketplace: str = Query(..., min_length=4, max_length=32)):
    try:
        return get_default_category_tree_id(marketplace)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay taxonomy metadata failed: {exc}") from exc


@app.get("/api/ebay/taxonomy/top")
def ebay_taxonomy_top(marketplace: str = Query(..., min_length=4, max_length=32), force: bool = False, cached_only: bool = False):
    try:
        if cached_only and not force:
            return get_top_categories_cached(marketplace)
        return get_top_categories(marketplace, force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay taxonomy tree failed: {exc}") from exc


@app.get("/api/ebay/taxonomy/children")
def ebay_taxonomy_children(marketplace: str, category_id: str):
    try:
        return get_category_children(marketplace, category_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay taxonomy subtree failed: {exc}") from exc


@app.get("/api/ebay/taxonomy/suggest")
def ebay_taxonomy_suggest(marketplace: str, q: str, limit: int = 12):
    try:
        return get_category_suggestions(marketplace, q, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay taxonomy suggestions failed: {exc}") from exc


@app.get("/api/ebay/taxonomy/aspects")
def ebay_taxonomy_aspects(marketplace: str, category_id: str):
    try:
        return get_item_aspects(marketplace, category_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay category aspects failed: {exc}") from exc


@app.get("/api/data/listings")
def listings(q: str, marketplace: str = Query(..., min_length=4, max_length=32), limit: int = 50, category_id: str | None = None, sort: str | None = None, offset: int = 0):
    try:
        return search_listings(query=q, marketplace_id=marketplace, limit=limit, category_id=category_id, sort=sort, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay request failed: {exc}") from exc


@app.get("/api/data/listings/comparables")
def listing_comparables(
    q: str,
    marketplace: str = Query(..., min_length=4, max_length=32),
    limit: int = 100,
    target_price: float | None = None,
    excluded: str | None = None,
    category_id: str | None = None,
    sort: str | None = None,
    offset: int = 0,
    project_id: int | None = None,
):
    try:
        payload = PROVIDERS["ebay"].search(query=q, marketplace_id=marketplace, limit=limit, category_id=category_id, sort=sort, offset=offset)
        exclusions = [x.strip() for x in excluded.split(",")] if excluded else None
        project = get_project(project_id) if project_id else None
        attrs = (project or {}).get("attributes") or {}
        expected_category = category_id or attrs.get("ebay_category_id")
        expected_aspects = attrs.get("ebay_aspects") or {}
        comparable = build_comparable_set(
            payload.get("items", []), query=q, target_price=target_price,
            excluded_terms=exclusions, expected_category_id=str(expected_category) if expected_category else None,
            expected_attributes=expected_aspects if isinstance(expected_aspects, dict) else {},
            remove_price_outliers=True,
        )
        return {
            **payload,
            "comparable_set": comparable,
            "benchmark_allowed": bool(payload.get("is_market_data")),
            "benchmark_note": "Production market data may feed pricing after comparable filtering." if payload.get("is_market_data") else "Sandbox output is integration-test data only and is blocked from pricing benchmarks.",
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay comparable request failed: {exc}") from exc


@app.get("/api/data/listings/sync")
def listing_sync(q: str, marketplace: str = Query(..., min_length=4, max_length=32), limit: int = 50, category_id: str | None = None, sort: str | None = None, offset: int = 0):
    try:
        payload = search_listings(query=q, marketplace_id=marketplace, limit=limit, category_id=category_id, sort=sort, offset=offset)
        payload["synced_at"] = datetime.now(timezone.utc).isoformat()
        return save_listing_snapshot(payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"eBay listing sync failed: {exc}") from exc


@app.get("/api/data/listings/snapshots")
def listing_snapshots():
    return {"snapshots": list_listing_snapshots()}


# --- V4 decision/workflow endpoints -------------------------------------------------

def _project_context_for_hs(project: dict) -> tuple[list[str], dict[str, object]]:
    attrs = project.get("attributes") or {}
    path = attrs.get("ebay_category_path") or []
    if not isinstance(path, list):
        path = [str(path)]
    aspects = attrs.get("ebay_aspects") or {}
    if not isinstance(aspects, dict):
        aspects = {}
    return [str(x) for x in path], aspects


def _verified_benchmark(project: dict, market: str) -> dict | None:
    assumptions = project.get("assumptions") or {}
    manual = (assumptions.get("market_benchmarks") or {}).get(market)
    if isinstance(manual, dict) and manual.get("median") is not None:
        return {**manual, "source": manual.get("source") or "User verified benchmark", "verified": True}
    for payload in list_listing_snapshots():
        if int(payload.get("project_id") or 0) != int(project.get("id") or 0):
            continue
        if str(payload.get("market_code") or "").upper() != market.upper():
            continue
        if not payload.get("verified_market_data"):
            continue
        summary = (payload.get("comparable_set") or {}).get("summary") or {}
        if summary.get("median") is not None:
            return {
                "median": summary.get("median"),
                "p25": summary.get("p25"),
                "p75": summary.get("p75"),
                "currency": payload.get("currency"),
                "source": payload.get("source") or "Verified marketplace upload",
                "verified": True,
                "synced_at": payload.get("synced_at"),
            }
    return None


def _research_benchmark(project: dict, market: str) -> dict | None:
    verified = _verified_benchmark(project, market)
    if verified:
        return verified
    for payload in list_listing_snapshots():
        if int(payload.get("project_id") or 0) != int(project.get("id") or 0):
            continue
        if str(payload.get("market_code") or "").upper() != market.upper():
            continue
        if not payload.get("source_backed_market_data"):
            continue
        summary = (payload.get("comparable_set") or {}).get("summary") or {}
        if summary.get("median") is not None:
            return {
                "median": summary.get("median"), "p25": summary.get("p25"), "p75": summary.get("p75"),
                "currency": payload.get("currency"), "source": payload.get("source") or "Source-backed web observations",
                "verified": False, "source_backed": True, "evidence_level": payload.get("evidence_level") or "C",
                "synced_at": payload.get("synced_at"), "observation_count": len((payload.get("comparable_set") or {}).get("accepted") or []),
            }
    return None


def _pricing_input_context(project: dict, snapshot: dict | None) -> dict[str, float] | None:
    """Resolve deterministic pricing inputs from saved assumptions and source-backed evidence."""
    a = _safe_mapping(project.get("assumptions"))
    factory_cost = _safe_float(a.get("factory_cost"))
    platform_fee_rate = _safe_float(a.get("platform_fee_rate"))
    target_margin_rate = _safe_float(a.get("target_margin_rate"))
    if factory_cost is None or platform_fee_rate is None or target_margin_rate is None:
        return None

    snap = _safe_mapping(snapshot)
    market_code = str(snap.get("market") or "")
    hs6 = _hs6(project.get("hs_code"))
    tariff_override = get_tariff_override(market_code, hs6) if market_code and hs6 else None
    override_rate = _safe_float(_safe_mapping(tariff_override).get("rate"))
    assumption_duty = _safe_float(a.get("duty_rate"))
    snapshot_duty = _safe_float(_safe_mapping(snap.get("tariff")).get("rate"))
    if override_rate is not None:
        duty_rate = override_rate / 100
    elif assumption_duty is not None:
        duty_rate = assumption_duty
    elif snapshot_duty is not None:
        duty_rate = snapshot_duty / 100
    else:
        ai_tariff = latest_ai_evidence(int(project.get("id") or 0), market_code, "tariff.rate") if project.get("id") else None
        ai_rate = _safe_float(_safe_mapping(ai_tariff).get("value"))
        if ai_rate is None:
            return None
        duty_rate = ai_rate / 100

    tax_override = get_tax_override(market_code) if market_code else None
    override_tax = _safe_float(_safe_mapping(tax_override).get("rate"))
    assumption_tax = _safe_float(a.get("tax_rate"))
    snapshot_tax = _safe_float(_safe_mapping(snap.get("tax")).get("rate"))
    if override_tax is not None:
        tax_rate = override_tax / 100
    elif assumption_tax is not None:
        tax_rate = assumption_tax
    elif snapshot_tax is not None:
        tax_rate = snapshot_tax / 100
    else:
        ai_tax = latest_ai_evidence(int(project.get("id") or 0), market_code, "tax.rate") if project.get("id") else None
        ai_tax_rate = _safe_float(_safe_mapping(ai_tax).get("value"))
        if ai_tax_rate is None:
            return None
        tax_rate = ai_tax_rate / 100

    return {
        "factory_cost": float(factory_cost),
        "packaging_cost": float(_safe_float(a.get("packaging_cost")) or 0),
        "freight_cost": float(_safe_float(a.get("freight_cost")) or 0),
        "fulfillment_cost": float(_safe_float(a.get("fulfillment_cost")) or 0),
        "duty_rate": float(duty_rate),
        "tax_rate": float(tax_rate),
        "platform_fee_rate": float(platform_fee_rate),
        "target_margin_rate": float(target_margin_rate),
    }


def _pricing_for_market(project: dict, snapshot: dict | None) -> dict | None:
    inputs = _pricing_input_context(project, snapshot)
    if not inputs:
        return None
    try:
        return calculate_pricing(PricingRequest(**inputs))
    except Exception:
        return None


@app.get("/api/hs/search")
def hs_search(q: str = Query(..., min_length=1, max_length=120), limit: int = Query(12, ge=1, le=50)):
    try:
        return search_hs_reference(query=q, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HS reference lookup failed: {exc}") from exc


@app.get("/api/hs/suggest")
def hs_suggest(
    q: str = Query(default="", max_length=600),
    project_id: int | None = None,
    limit: int = Query(default=8, ge=1, le=20),
):
    project = get_project(project_id) if project_id else None
    query = q.strip() or str((project or {}).get("title") or "").strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Provide a product name or project before requesting HS candidates.")
    category_path, attributes = _project_context_for_hs(project or {})
    primary_error = None
    try:
        result = hybrid_hs_candidates(query=query, category_path=category_path, attributes=attributes, limit=limit)
        if result.get("candidates"):
            return result
    except Exception as exc:
        primary_error = exc
    # Keep the deterministic token matcher as a safe fallback if the local
    # embedding/LTR index cannot be constructed on a constrained machine.
    try:
        fallback = suggest_hs_candidates(query=query, category_path=category_path, attributes=attributes, limit=limit)
        fallback["ranking_model"] = "deterministic_fallback"
        fallback["hybrid_error"] = str(primary_error or "")[:500]
        return fallback
    except Exception as exc:
        detail = primary_error or exc
        raise HTTPException(status_code=502, detail=f"HS reference lookup failed: {detail}") from detail


@app.post("/api/hs/feedback")
def hs_ranking_feedback(req: HSRankingFeedbackRequest):
    try:
        return {"saved": save_hs_ranking_feedback(**req.model_dump())}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not save HS ranking feedback: {exc}") from exc


@app.post("/api/projects/{project_id}/ai/hs-candidates")
def ai_hs_candidates(project_id: int, limit: int = Query(default=8, ge=1, le=20)):
    project=get_project(project_id)
    if not project:
        raise HTTPException(status_code=404,detail="Project not found")
    caps=recovery_capabilities()
    if not caps.get("configured"):
        raise HTTPException(status_code=422,detail="Model API is not configured")
    if not caps.get("native_web_search"):
        raise HTTPException(status_code=422,detail="Current model protocol does not support source-backed web research")
    try:
        return recover_hs_candidates(project,query=str(project.get("title") or ""),limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502,detail=f"AI HS research failed: {exc}") from exc


@app.post("/api/pricing/reverse")
def pricing_reverse(req: ReversePricingRequest):
    try:
        return reverse_cost(**req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/profit-simulation")
def project_profit_simulation(project_id: int, req: ProfitSimulationRequest):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    market = str(req.market or "").upper()
    if market not in (project.get("markets") or []):
        raise HTTPException(status_code=422, detail="Market is not selected for this project")
    hs = _hs6(project.get("hs_code"))
    origin_code = str(_safe_mapping(project.get("attributes")).get("origin_partner_code") or "") or None
    snapshot = latest_snapshot(market, hs, origin_code=origin_code) if hs else None
    inputs = _pricing_input_context(project, snapshot)
    if not inputs:
        raise HTTPException(status_code=422, detail="Complete cost, tariff and tax inputs before uncertainty simulation.")
    benchmark = _safe_mapping(_research_benchmark(project, market))
    benchmark_price = _safe_float(benchmark.get("median"))
    forward = _safe_mapping(_pricing_for_market(project, snapshot))
    selling_price = benchmark_price if benchmark_price is not None and benchmark_price > 0 else _safe_float(forward.get("target_price"))
    if selling_price is None or selling_price <= 0:
        raise HTTPException(status_code=422, detail="A market price benchmark or calculable target price is required.")
    baseline = {**inputs, "selling_price": float(selling_price)}

    variables = [v.model_dump() for v in req.variables]
    if not variables:
        def bounds(name: str, frac: float, floor: float = 0.0):
            base = float(baseline.get(name) or 0.0)
            if base == 0:
                hi = 0.03 if name in {"duty_rate", "tax_rate", "platform_fee_rate"} else max(1.0, selling_price * 0.05)
                return floor, hi
            return max(floor, base * (1 - frac)), max(floor, base * (1 + frac))
        p_lo, p_hi = max(0.01, selling_price * 0.90), selling_price * 1.10
        f_lo, f_hi = bounds("factory_cost", .10)
        fr_lo, fr_hi = bounds("freight_cost", .20)
        pf_base = float(baseline.get("platform_fee_rate") or 0)
        pf_lo, pf_hi = max(0.0, pf_base - .02), min(.95, pf_base + .02)
        d_base = float(baseline.get("duty_rate") or 0)
        d_lo, d_hi = (0.0, .03) if d_base == 0 else (max(0.0, d_base * .80), min(.95, d_base * 1.20))
        variables = [
            {"name":"selling_price","distribution":"triangular","low":p_lo,"high":p_hi,"mode":selling_price},
            {"name":"factory_cost","distribution":"triangular","low":f_lo,"high":f_hi,"mode":baseline["factory_cost"]},
            {"name":"freight_cost","distribution":"triangular","low":fr_lo,"high":fr_hi,"mode":baseline["freight_cost"]},
            {"name":"platform_fee_rate","distribution":"uniform","low":pf_lo,"high":pf_hi},
            {"name":"duty_rate","distribution":"uniform","low":d_lo,"high":d_hi},
        ]
    try:
        result = simulate_profit_uncertainty(
            baseline=baseline, variable_specs=variables, sample_count=req.sample_count,
            method=req.sampling_method, sobol_base_n=req.sobol_base_n, seed=req.seed,
            target_margin_rate=float(inputs.get("target_margin_rate") or 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result.update({
        "project_id": project_id, "market": market,
        "currency": benchmark.get("currency") or _safe_mapping(MARKETS.get(market)).get("currency") or _safe_mapping(project.get("assumptions")).get("base_currency") or "USD",
        "price_source": benchmark.get("source") if benchmark_price is not None else "Calculated target price",
    })
    return result


@app.get("/api/marketplace/providers")
def marketplace_providers():
    refresh_settings()
    return {"providers": provider_statuses()}


@app.post("/api/marketplace/listings/upload")
async def marketplace_listing_upload(
    file: UploadFile = File(...),
    project_id: int = Form(...),
    market: str = Form(...),
    query: str = Form(default=""),
    verified_market_data: bool = Form(default=False),
    excluded_terms: str = Form(default=""),
):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    market = market.upper()
    if market not in MARKETS:
        raise HTTPException(status_code=422, detail="Unknown market code")
    filename = file.filename or "marketplace.csv"
    if not filename.lower().endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(status_code=422, detail="Supported marketplace observation formats: CSV, XLSX")
    payload = await file.read()
    try:
        provider = PROVIDERS["csv"]
        rows = provider.parse_bytes(payload, filename=filename)
        attrs = project.get("attributes") or {}
        category_id = attrs.get("ebay_category_id")
        aspects = attrs.get("ebay_aspects") or {}
        comparable = build_comparable_set(
            rows,
            query=query or project.get("title") or "",
            excluded_terms=[x.strip() for x in excluded_terms.split(",") if x.strip()],
            expected_category_id=str(category_id) if category_id else None,
            expected_attributes=aspects if isinstance(aspects, dict) else {},
            minimum_query_overlap=0.0,
            minimum_attribute_overlap=0.0,
            remove_price_outliers=True,
        )
        currencies = [str(x.get("currency") or "").upper() for x in comparable.get("accepted", []) if x.get("currency")]
        currency = max(set(currencies), key=currencies.count) if currencies else MARKETS[market]["currency"]
        saved = save_listing_snapshot({
            "environment": "user-upload",
            "source": "User-uploaded marketplace observations",
            "project_id": project_id,
            "market_code": market,
            "marketplace": "USER_UPLOAD",
            "query": query or project.get("title") or "",
            "verified_market_data": bool(verified_market_data),
            "is_market_data": bool(verified_market_data),
            "currency": currency,
            "total": len(rows),
            "returned": len(rows),
            "items": rows,
            "comparable_set": comparable,
            "provenance_note": "Marked verified by the user" if verified_market_data else "Uploaded observations are stored but blocked from decision benchmarks until marked verified.",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        })
        return saved
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse marketplace observations: {exc}") from exc


@app.get("/api/projects/{project_id}/decision-cases")
def project_decision_cases(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    origin_code = str((project.get("attributes") or {}).get("origin_partner_code") or "") or None
    cases = []
    for market in project.get("markets") or []:
        snapshot = latest_snapshot(market, hs, origin_code=origin_code) if hs else None
        benchmark = _research_benchmark(project, market)
        pricing_result = _pricing_for_market(project, snapshot)
        reverse_result = None
        if benchmark and benchmark.get("median") is not None:
            a = project.get("assumptions") or {}
            manual_tariff = get_tariff_override(market, hs) if hs else None
            manual_rate = _safe_float(_safe_mapping(manual_tariff).get("rate"))
            assumption_duty = _safe_float(a.get("duty_rate"))
            snapshot_rate = _safe_float(_safe_mapping(_safe_mapping(snapshot).get("tariff")).get("rate"))
            if manual_rate is not None:
                tariff_rate = manual_rate / 100
            elif assumption_duty is not None:
                tariff_rate = assumption_duty
            elif snapshot_rate is not None:
                tariff_rate = snapshot_rate / 100
            else:
                ai_tariff = latest_ai_evidence(project_id, market, "tariff.rate")
                ai_tariff_rate = _safe_float(_safe_mapping(ai_tariff).get("value"))
                tariff_rate = ai_tariff_rate / 100 if ai_tariff_rate is not None else 0
            manual_tax = get_tax_override(market)
            manual_tax_rate = _safe_float(_safe_mapping(manual_tax).get("rate"))
            assumption_tax = _safe_float(a.get("tax_rate"))
            snapshot_tax_rate = _safe_float(_safe_mapping(_safe_mapping(snapshot).get("tax")).get("rate"))
            if manual_tax_rate is not None:
                effective_tax_rate = manual_tax_rate / 100
            elif assumption_tax is not None:
                effective_tax_rate = assumption_tax
            elif snapshot_tax_rate is not None:
                effective_tax_rate = snapshot_tax_rate / 100
            else:
                ai_tax = latest_ai_evidence(project_id, market, "tax.rate")
                ai_tax_rate = _safe_float(_safe_mapping(ai_tax).get("value"))
                effective_tax_rate = ai_tax_rate / 100 if ai_tax_rate is not None else 0
            try:
                reverse_result = reverse_cost(
                    target_selling_price=float(benchmark["median"]),
                    packaging_cost=float(a.get("packaging_cost") or 0),
                    freight_cost=float(a.get("freight_cost") or 0),
                    fulfillment_cost=float(a.get("fulfillment_cost") or 0),
                    duty_rate=tariff_rate,
                    tax_rate=effective_tax_rate,
                    platform_fee_rate=float(a.get("platform_fee_rate") or 0),
                    target_margin_rate=float(a.get("target_margin_rate") or 0),
                    current_factory_cost=float(a.get("factory_cost")) if a.get("factory_cost") is not None else None,
                )
            except Exception:
                reverse_result = None
        cost_ready = pricing_result is not None
        cases.append(decision_case(
            market=market,
            snapshot=snapshot,
            pricing=pricing_result,
            reverse=reverse_result,
            benchmark=benchmark,
            cost_ready=cost_ready,
        ))
    return {"project_id": project_id, "cases": cases, "count": len(cases)}


@app.get("/api/projects/{project_id}/data-quality")
def project_data_quality(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    origin_code = str((project.get("attributes") or {}).get("origin_partner_code") or "") or None
    items = []
    for market in project.get("markets") or []:
        snapshot = latest_snapshot(market, hs, origin_code=origin_code) if hs else None
        items.append({"market": market, **evidence_quality(snapshot, benchmark_available=bool(_research_benchmark(project, market)), cost_ready=_pricing_for_market(project, snapshot) is not None)})
    return {"project_id": project_id, "items": items}




@app.get("/api/projects/{project_id}/explorer")
def project_explorer(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    if not hs:
        raise HTTPException(status_code=422, detail="Confirm an HS code before using Opportunity Explorer.")
    origin_code = str((_safe_mapping(project.get("attributes"))).get("origin_partner_code") or "") or None
    cached = _safe_mapping(get_market_scan(project_id))
    cached_rows = cached.get("markets") if isinstance(cached.get("markets"), list) else []
    scan_rows = {}
    for raw in cached_rows:
        if not isinstance(raw, dict) or not raw.get("market"):
            continue
        try:
            row = _overlay_scan_row(project_id, dict(raw))
        except Exception:
            row = dict(raw)
        scan_rows[str(row.get("market") or raw.get("market")).upper()] = row

    # Opportunity Explorer must remain usable even when Decision Cases contains
    # legacy/malformed economics data.  Decision status enriches the explorer; it
    # is not a prerequisite for rendering market evidence.
    try:
        decision_cases = project_decision_cases(project_id).get("cases") or []
        decision_map = {str(c.get("market") or "").upper(): c for c in decision_cases if isinstance(c, dict) and c.get("market")}
    except Exception:
        decision_map = {}

    supply_profile = _safe_mapping(get_supply_profile(project_id))
    corridor_rows = supply_profile.get("target_corridors") if isinstance(supply_profile.get("target_corridors"), list) else []
    corridor_map = {str(x.get("market") or "").upper(): x for x in corridor_rows if isinstance(x, dict) and x.get("market")}
    selected = {str(x).upper() for x in (project.get("markets") or []) if str(x).strip()}
    market_codes = list(dict.fromkeys(list(scan_rows.keys()) + list(selected)))
    rows = []
    for code in market_codes:
        cfg = _safe_mapping(MARKETS.get(code))
        scan = _safe_mapping(scan_rows.get(code))
        try:
            snapshot = latest_snapshot(code, hs, origin_code=origin_code)
        except Exception:
            snapshot = None
        snap = _safe_mapping(snapshot)
        trade = _safe_mapping(snap.get("trade"))
        suppliers = _safe_mapping(snap.get("suppliers"))
        tariff = _safe_mapping(snap.get("tariff"))
        decision = _safe_mapping(decision_map.get(code))
        try:
            quality = _safe_mapping(decision.get("evidence_quality")) or evidence_quality(snap or None)
        except Exception:
            quality = evidence_quality(None)
        try:
            benchmark = _research_benchmark(project, code)
        except Exception:
            benchmark = None
        try:
            pricing = _pricing_for_market(project, snap or None)
        except Exception:
            pricing = None
        margin_at_benchmark = None
        try:
            pricing_inputs = _pricing_input_context(project, snap or None)
            benchmark_value = _safe_float(_safe_mapping(benchmark).get("median"))
            if pricing_inputs and benchmark_value is not None and benchmark_value > 0:
                priced_at_market = calculate_pricing(PricingRequest(**pricing_inputs, listing_median=benchmark_value))
                margin_at_benchmark = _safe_float(_safe_mapping(priced_at_market).get("margin_at_listing_median"))
        except Exception:
            margin_at_benchmark = None
        economics = _safe_mapping(decision.get("economics"))
        reverse = _safe_mapping(economics.get("reverse"))
        corridor = _safe_mapping(corridor_map.get(code))
        world_metrics = _safe_mapping(trade.get("world_metrics"))
        tariff_rate = _safe_float(tariff.get("rate"))
        imports = _safe_float(trade.get("latest_total_imports"))
        if imports is None:
            imports = _safe_float(scan.get("imports"))
        yoy = _safe_float(world_metrics.get("yoy"))
        if yoy is None:
            yoy = _safe_float(scan.get("yoy"))
        cagr = _safe_float(world_metrics.get("cagr"))
        if cagr is None:
            cagr = _safe_float(scan.get("cagr"))
        origin_share = _safe_float(trade.get("latest_origin_share"))
        if origin_share is None:
            origin_share = _safe_float(scan.get("origin_share"))
        row = {
            "market": code,
            "label": cfg.get("label") or scan.get("label") or code,
            "currency": cfg.get("currency") or scan.get("currency"),
            "selected": code in selected,
            "latest_year": trade.get("latest_year") or scan.get("latest_year"),
            "imports": imports,
            "yoy": yoy,
            "cagr": cagr,
            "origin_share": origin_share,
            "origin_exports": _safe_float(_safe_mapping(supply_profile.get("metrics")).get("latest_value")),
            "origin_export_cagr": _safe_float(_safe_mapping(supply_profile.get("metrics")).get("cagr")),
            "corridor_exports": _safe_float(corridor.get("trade_value")),
            "corridor_share": _safe_float(corridor.get("share")),
            "corridor_rank": corridor.get("rank"),
            "coverage": _safe_float(quality.get("trade_coverage")) if quality.get("trade_coverage") is not None else _safe_float(scan.get("coverage_ratio")),
            "cr3": _safe_float(suppliers.get("cr3")),
            "cr5": _safe_float(suppliers.get("cr5")),
            "hhi": _safe_float(suppliers.get("hhi")),
            "tariff": tariff_rate / 100 if tariff_rate is not None else None,
            "evidence_ratio": _safe_float(quality.get("completeness_ratio")),
            "evidence_status": quality.get("status"),
            "missing_evidence": quality.get("missing") if isinstance(quality.get("missing"), list) else [],
            "decision_status": decision.get("status"),
            "benchmark_median": _safe_float(_safe_mapping(benchmark).get("median")),
            "margin_at_benchmark": margin_at_benchmark,
            "required_price": _safe_float(_safe_mapping(pricing).get("target_price")),
            "factory_headroom": _safe_float(reverse.get("factory_cost_headroom")),
            "source": scan.get("source") or trade.get("source") or "UN Comtrade",
            "detailed_synced": bool(snap),
        }
        rows.append(row)
    rows.sort(key=lambda r: (r.get("imports") is not None, r.get("imports") if r.get("imports") is not None else 0.0), reverse=True)
    frontier = pareto_frontier(rows, maximize=("imports", "cagr", "coverage"), min_metrics=2)
    quadrants = market_quadrants(rows)
    for row in rows:
        row["pareto_frontier"] = row["market"] in frontier
        row["quadrant"] = quadrants.get(row["market"])
    return {
        "project_id": project_id,
        "hs6": hs,
        "origin": project.get("origin"),
        "rows": rows,
        "standouts": standout_markets(rows),
        "frontier_method": "Non-weighted Pareto frontier using observed import size, 3Y CAGR and trade coverage; no synthetic score.",
        "scan_cached_at": cached.get("scanned_at"),
        "supply_synced_at": supply_profile.get("synced_at"),
        "supply_method": supply_profile.get("method"),
    }


@app.post("/api/projects/{project_id}/pareto")
def project_pareto_screen(project_id: int, req: ParetoScreenRequest):
    explorer = project_explorer(project_id)
    allowed = {
        "imports", "cagr", "origin_share", "coverage", "cr3", "cr5", "hhi", "tariff",
        "evidence_ratio", "benchmark_median", "margin_at_benchmark", "required_price", "factory_headroom",
        "corridor_share", "origin_export_cagr",
    }
    objectives = [o.model_dump() for o in req.objectives if o.key in allowed]
    if not objectives:
        candidates = [
            {"key":"imports","direction":"max"}, {"key":"cagr","direction":"max"},
            {"key":"margin_at_benchmark","direction":"max"}, {"key":"hhi","direction":"min"},
            {"key":"tariff","direction":"min"}, {"key":"evidence_ratio","direction":"max"},
        ]
        rows = explorer.get("rows") or []
        objectives = [o for o in candidates if sum(1 for r in rows if _safe_float(r.get(o["key"])) is not None) >= 2]
        if len(objectives) < 2:
            objectives = [{"key":"imports","direction":"max"},{"key":"cagr","direction":"max"}]
    try:
        result = non_dominated_sort(explorer.get("rows") or [], objectives)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"project_id": project_id, "hs6": explorer.get("hs6"), **result}


def _portfolio_safe_snapshot(snapshot):
    """Normalize persisted evidence before Portfolio read-only aggregation.

    Older local databases and AI/source-backed evidence can contain partially
    structured blocks.  Portfolio is an overview page, so one malformed
    optional block must not turn the entire matrix into HTTP 500.
    """
    snap = dict(_safe_mapping(snapshot))
    trade = dict(_safe_mapping(snap.get("trade")))
    trade["world_metrics"] = dict(_safe_mapping(trade.get("world_metrics")))
    snap["trade"] = trade
    snap["suppliers"] = dict(_safe_mapping(snap.get("suppliers")))
    snap["tariff"] = dict(_safe_mapping(snap.get("tariff")))
    snap["tax"] = dict(_safe_mapping(snap.get("tax")))
    snap["fx"] = dict(_safe_mapping(snap.get("fx")))
    snap["quality"] = dict(_safe_mapping(snap.get("quality")))
    return snap or None


@app.get("/api/portfolio/matrix")
def portfolio_matrix(batch_id: str | None = None):
    projects = list_projects()
    if batch_id:
        projects = [p for p in projects if str(_safe_mapping(p.get("attributes")).get("portfolio_batch_id") or "") == batch_id]
    all_markets = []
    rows = []
    for project in projects:
        attrs = _safe_mapping(project.get("attributes"))
        hs = _hs6(project.get("hs_code"))
        origin_code = str(attrs.get("origin_partner_code") or "") or None
        cells = {}
        raw_markets = project.get("markets")
        project_markets = raw_markets if isinstance(raw_markets, list) else []
        for raw_market in project_markets:
            market = str(raw_market or "").upper().strip()
            if not market:
                continue
            if market not in all_markets:
                all_markets.append(market)

            try:
                snapshot = latest_snapshot(market, hs, origin_code=origin_code) if hs else None
            except Exception:
                snapshot = None
            snapshot = _portfolio_safe_snapshot(snapshot)

            try:
                benchmark = _research_benchmark(project, market)
                benchmark = dict(benchmark) if isinstance(benchmark, dict) else None
            except Exception:
                benchmark = None

            try:
                pricing = _pricing_for_market(project, snapshot)
            except Exception:
                pricing = None
            cost_ready = pricing is not None

            try:
                quality = evidence_quality(snapshot, benchmark_available=bool(benchmark), cost_ready=cost_ready)
            except Exception:
                quality = {"completeness_ratio": 0.0}
            try:
                decision = decision_case(
                    market=market, snapshot=snapshot, benchmark=benchmark,
                    pricing=pricing, cost_ready=cost_ready,
                )
                status = decision.get("status") or "PENDING"
            except Exception:
                status = "PENDING"

            trade = _safe_mapping(_safe_mapping(snapshot).get("trade"))
            world_metrics = _safe_mapping(trade.get("world_metrics"))
            cells[market] = {
                "status": status,
                "evidence_ratio": _safe_float(quality.get("completeness_ratio")) or 0.0,
                "imports": _safe_float(trade.get("latest_total_imports")),
                "cagr": _safe_float(world_metrics.get("cagr")),
                "origin_share": _safe_float(trade.get("latest_origin_share")),
            }
        rows.append({
            "project_id": project.get("id"),
            "sku": attrs.get("portfolio_sku"),
            "title": project.get("title"),
            "hs_code": project.get("hs_code"),
            "origin": project.get("origin"),
            "cells": cells,
        })
    return {"markets": all_markets, "rows": rows, "count": len(rows), "batch_id": batch_id}


@app.get("/api/portfolio/optimization-inputs")
def portfolio_optimization_inputs(batch_id: str | None = None):
    projects = list_projects()
    if batch_id:
        projects = [p for p in projects if str(_safe_mapping(p.get("attributes")).get("portfolio_batch_id") or "") == batch_id]
    opportunities = []
    skipped = []
    for project in projects:
        hs = _hs6(project.get("hs_code"))
        attrs = _safe_mapping(project.get("attributes"))
        origin_code = str(attrs.get("origin_partner_code") or "") or None
        for market in project.get("markets") or []:
            try:
                snap = _portfolio_safe_snapshot(latest_snapshot(market, hs, origin_code=origin_code) if hs else None)
                benchmark = _safe_mapping(_research_benchmark(project, market))
                inputs = _pricing_input_context(project, snap)
            except Exception:
                snap, benchmark, inputs = None, {}, None
            price = _safe_float(benchmark.get("median"))
            if not inputs or price is None or price <= 0:
                skipped.append({"project_id": project.get("id"), "product": project.get("title"), "market": market, "reason": "missing_price_or_cost"})
                continue
            try:
                priced = calculate_pricing(PricingRequest(**inputs, listing_median=price))
                margin = _safe_float(_safe_mapping(priced).get("margin_at_listing_median"))
            except Exception:
                margin = None
            if margin is None or margin >= 0.98:
                skipped.append({"project_id": project.get("id"), "product": project.get("title"), "market": market, "reason": "invalid_margin"})
                continue
            # Allocation represents operating-capital/cost budget. Convert margin
            # on revenue into profit per unit of cost so MILP coefficients are comparable.
            return_rate = margin / max(1e-6, 1 - margin)
            trade = _safe_mapping(_safe_mapping(snap).get("trade"))
            suppliers = _safe_mapping(_safe_mapping(snap).get("suppliers"))
            quality = evidence_quality(snap, benchmark_available=True, cost_ready=True)
            vol = trade_volatility(trade.get("history") or [])
            hhi = _safe_float(suppliers.get("hhi")) or 0.0
            evidence = _safe_float(quality.get("completeness_ratio")) or 0.0
            vol_scaled = min(1.0, max(0.0, (vol or 0.0) / 0.50))
            risk_score = min(1.0, 0.40 * min(1.0, hhi) + 0.35 * vol_scaled + 0.25 * (1 - evidence))
            uncertainty = abs(return_rate) * min(0.80, 0.15 + 0.35 * vol_scaled + 0.20 * min(1.0, hhi) + 0.30 * (1 - evidence))
            opportunities.append({
                "project_id": project.get("id"), "product": project.get("title") or str(project.get("id")), "market": market,
                "return_rate": round(return_rate, 8), "revenue_rate": round(1 + return_rate, 8),
                "uncertainty": round(uncertainty, 8), "risk_score": round(risk_score, 8),
                "evidence_ratio": round(evidence, 4), "margin_at_market_price": round(margin, 6),
                "market_price": price, "currency": benchmark.get("currency") or _safe_mapping(MARKETS.get(market)).get("currency"),
                "volatility": None if vol is None else round(float(vol), 6), "hhi": round(hhi, 6),
                "enabled": return_rate > 0,
            })
    return {
        "opportunities": opportunities, "count": len(opportunities), "skipped": skipped,
        "method": "Planning coefficients are derived from market-price unit economics; structural risk uses observed trade volatility, supplier concentration and evidence completeness. These are transparent planning proxies, not demand forecasts.",
    }


@app.post("/api/portfolio/optimize")
def portfolio_optimize(req: PortfolioOptimizationRequest):
    payload = req.model_dump()
    if not payload.get("opportunities"):
        payload["opportunities"] = portfolio_optimization_inputs().get("opportunities") or []
    try:
        return optimize_resource_allocation(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/export.xlsx")
def project_export_xlsx(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    hs = _hs6(project.get("hs_code"))
    origin_code = str((project.get("attributes") or {}).get("origin_partner_code") or "") or None
    snapshots = []
    for market in project.get("markets") or []:
        snap = latest_snapshot(market, hs, origin_code=origin_code) if hs else None
        if snap:
            snapshots.append(snap)
    decisions = project_decision_cases(project_id)["cases"]
    listing_rows = [x for x in list_listing_snapshots() if int(x.get("project_id") or 0) == project_id]
    supply_profile = get_supply_profile(project_id) or {}
    matrix_origin = str((supply_profile.get("origin") or {}).get("code") or origin_code or "")
    if matrix_origin:
        matrix_origin = matrix_origin.zfill(3)
    tariff_rows = list_tariff_matrix(hs_code=hs, origin_code=matrix_origin) if hs else []
    ai_evidence_rows = list_ai_evidence(project_id)
    data = build_project_workbook(project=project, snapshots=snapshots, decisions=decisions, listing_snapshots=listing_rows, explorer_rows=project_explorer(project_id)["rows"] if hs else [], supply_profile=supply_profile, tariff_matrix=tariff_rows, ai_evidence=ai_evidence_rows)
    safe = "".join(ch if ch.isalnum() else "_" for ch in project.get("title", "project"))[:60]
    headers = {"Content-Disposition": f'attachment; filename="GoGlobal_{project_id}_{safe}.xlsx"'}
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@app.get("/api/portfolio/template.csv")
def portfolio_template():
    content = "product_name,sku,origin,hs_code,target_markets,factory_cost,packaging_cost,freight_cost,fulfillment_cost,platform_fee_pct,target_margin_pct,currency\n"
    return Response(content=content, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="GoGlobal_portfolio_template.csv"'})


@app.post("/api/portfolio/import")
async def portfolio_import(file: UploadFile = File(...)):
    filename = file.filename or "portfolio.csv"
    if not filename.lower().endswith((".csv", ".xlsx")):
        raise HTTPException(status_code=422, detail="Portfolio import accepts CSV or XLSX.")
    payload = await file.read()
    try:
        rows = parse_portfolio_bytes(payload, filename=filename)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse portfolio file: {exc}") from exc
    batch = portfolio_batch_id()
    created = []
    rejected = []
    for row in rows:
        invalid_markets = [m for m in row.get("markets", []) if m not in MARKETS]
        errors = list(row.get("errors") or [])
        if invalid_markets:
            errors.append(f"Unknown markets: {', '.join(invalid_markets)}")
        if errors:
            rejected.append({**row, "errors": errors})
            continue
        attrs = {"portfolio_batch_id": batch, "portfolio_sku": row.get("sku"), "portfolio_source_file": filename, "portfolio_source_row": row.get("row_number")}
        project = create_project({
            "product_type_id": "generic",
            "title": row["title"],
            "description": "",
            "origin": row.get("origin") or "",
            "hs_code": row.get("hs_code") or "",
            "attributes": attrs,
            "markets": row.get("markets") or [],
            "assumptions": row.get("assumptions") or {},
            "status": "draft",
        })
        created.append(project)
    return {"batch_id": batch, "filename": filename, "rows": len(rows), "created": created, "created_count": len(created), "rejected": rejected, "rejected_count": len(rejected)}
