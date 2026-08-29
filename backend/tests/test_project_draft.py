from app.schemas import ProjectCreateRequest, ProjectUpdateRequest
from app.main import _hs6, _project_readiness


def test_draft_project_allows_missing_hs_and_markets():
    req = ProjectCreateRequest(title="PC Accessories", product_type_id="generic")
    assert req.hs_code == ""
    assert req.markets == []
    assert req.status == "draft"


def test_long_customs_code_is_accepted_and_hs6_is_normalized():
    req = ProjectCreateRequest(title="Laptop", hs_code="8471300000")
    assert req.hs_code == "8471300000"
    assert _hs6(req.hs_code) == "847130"


def test_readiness_only_blocks_required_analysis_fields():
    project = {
        "title": "Laptop",
        "product_type_id": "generic",
        "origin": "Example Origin",
        "hs_code": "8471300000",
        "markets": ["US"],
        "attributes": {},
        "assumptions": {},
    }
    r = _project_readiness(project)
    assert r["required_complete"] is True
    assert r["checks"]["cost_inputs"] is False
    assert r["progress"] == 1.0


def test_project_does_not_default_origin_or_product_template():
    req = ProjectCreateRequest(title="Sample product", product_type_id="marketplace:sample")
    assert req.origin == ""
    assert req.product_type_id == "marketplace:sample"


def test_readiness_progress_uses_required_setup_fields_only():
    project = {
        "title": "Product",
        "product_type_id": "marketplace:test",
        "origin": "",
        "hs_code": "",
        "markets": [],
        "attributes": {"ebay_category_id": "123"},
        "assumptions": {"factory_cost": 10, "target_margin_rate": 0.2},
    }
    r = _project_readiness(project)
    assert r["checks"]["category"] is True
    assert r["checks"]["cost_inputs"] is True
    assert r["progress"] == 0.25


def test_readiness_rejects_short_hs_for_setup_completion():
    project = {
        "title": "Product",
        "product_type_id": "generic",
        "origin": "USA",
        "hs_code": "12345",
        "markets": ["US"],
        "attributes": {},
        "assumptions": {},
    }
    r = _project_readiness(project)
    assert r["checks"]["hs_code"] is False
    assert r["progress"] == 0.75
