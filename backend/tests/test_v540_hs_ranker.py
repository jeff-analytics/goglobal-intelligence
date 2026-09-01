from __future__ import annotations

import inspect

import app.hs_ranker as ranker

ROWS = [
    {"code": "610910", "description": "T-shirts singlets and other vests of cotton knitted or crocheted"},
    {"code": "610990", "description": "T-shirts singlets and other vests of other textile materials knitted or crocheted"},
    {"code": "620520", "description": "Men's or boys' shirts of cotton not knitted or crocheted"},
    {"code": "611020", "description": "Jerseys pullovers cardigans waistcoats and similar articles of cotton knitted"},
    {"code": "640419", "description": "Footwear with outer soles of rubber or plastics and uppers of textile materials"},
    {"code": "850760", "description": "Lithium-ion accumulators"},
    {"code": "420222", "description": "Handbags with outer surface of plastic sheeting or textile materials"},
]


def reset(monkeypatch, feedback=None):
    monkeypatch.setattr(ranker, "get_hs_reference", lambda: ROWS)
    monkeypatch.setattr(ranker, "list_hs_ranking_feedback", lambda limit=200: list(feedback or []))
    ranker._CACHE.clear()


def test_hs_ranker_revision_is_r5_pure_python():
    assert ranker.HS_RANKER_REVISION == "r5-pure-python-deterministic"
    source = inspect.getsource(ranker)
    assert "import numpy" not in source


def test_hybrid_hs_ranker_combines_lexical_and_dense_signals(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=5)
    assert result["candidates"][0]["code"] == "610910"
    assert result["ranking_model"] == "seeded_pairwise_ranker"
    assert result["ranker_revision"] == "r5-pure-python-deterministic"
    first = result["candidates"][0]["score_breakdown"]
    assert first["bm25"] >= 0
    assert first["embedding"] >= 0
    assert "Learning-to-Rank" in result["method"]


def test_confirmed_hs_feedback_activates_pairwise_ltr(monkeypatch):
    feedback = [
        {
            "query_text": "cotton knitted t shirt",
            "selected_code": "610910",
            "candidate_codes": ["610990", "620520", "611020"],
        }
        for _ in range(6)
    ]
    reset(monkeypatch, feedback)
    result = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=5)
    assert result["ranking_model"] == "pairwise_logistic_ltr"
    assert result["feedback_count"] == 6
    assert result["candidates"][0]["code"] == "610910"


def test_hybrid_ranker_penalizes_classification_negation(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=5)
    by_code = {item["code"]: item for item in result["candidates"]}
    assert by_code["620520"]["score_breakdown"]["negation_conflict"] > 0
    assert by_code["610910"]["score_breakdown"]["negation_conflict"] == 0
    assert by_code["610910"]["score"] > by_code["620520"]["score"]


def test_hybrid_ranker_preserves_exact_numeric_hs_prefix_signal(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="850760", limit=5)
    assert result["candidates"][0]["code"] == "850760"
    assert result["candidates"][0]["score_breakdown"]["code_prefix"] == 1.0


def test_dense_embedding_does_not_amplify_unsupported_noise(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=7)
    by_code = {item["code"]: item for item in result["candidates"]}
    for code in ("850760", "420222"):
        breakdown = by_code[code]["score_breakdown"]
        assert breakdown["bm25"] == 0.0
        assert breakdown["token_coverage"] == 0.0
        assert breakdown["embedding"] <= 0.04
    assert by_code["610910"]["score_breakdown"]["embedding"] > by_code["850760"]["score_breakdown"]["embedding"]


def test_dense_calibration_hard_caps_zero_support():
    calibrated = ranker._calibrate_dense_scores([0.9965, 0.82], [0.0, 0.64])
    assert calibrated[0] <= 0.04
    assert calibrated[1] > 0.65


def test_hybrid_ranker_is_exactly_deterministic_across_rebuilds(monkeypatch):
    reset(monkeypatch)
    baseline = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=7)
    expected = baseline["candidates"]
    for _ in range(50):
        ranker._CACHE.clear()
        current = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=7)
        assert current["candidates"] == expected


def test_ltr_is_exactly_deterministic_across_rebuilds(monkeypatch):
    feedback = [
        {
            "query_text": "cotton knitted t shirt",
            "selected_code": "610910",
            "candidate_codes": ["610990", "620520", "611020"],
        }
        for _ in range(8)
    ]
    reset(monkeypatch, feedback)
    baseline = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=7)
    assert baseline["ranking_model"] == "pairwise_logistic_ltr"
    expected = baseline["candidates"]
    expected_weights = baseline["feature_weights"]
    for _ in range(25):
        ranker._CACHE.clear()
        current = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=7)
        assert current["candidates"] == expected
        assert current["feature_weights"] == expected_weights


def test_zero_lexical_support_never_exceeds_dense_cap(monkeypatch):
    reset(monkeypatch)
    for query in (
        "cotton knitted t shirt",
        "rechargeable lithium battery",
        "textile handbag",
        "rubber sole footwear",
    ):
        result = ranker.hybrid_hs_candidates(query=query, limit=7)
        for candidate in result["candidates"]:
            breakdown = candidate["score_breakdown"]
            if breakdown["bm25"] == 0.0 and breakdown["token_coverage"] == 0.0:
                assert breakdown["embedding"] <= 0.04


def test_numeric_prefix_ranking_is_stable_for_partial_code(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="8507", limit=7)
    assert result["candidates"][0]["code"].startswith("8507")
