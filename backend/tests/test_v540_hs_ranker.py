from __future__ import annotations

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


def test_hybrid_hs_ranker_combines_lexical_and_dense_signals(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=5)
    assert result["candidates"][0]["code"] == "610910"
    assert result["ranking_model"] == "seeded_pairwise_ranker"
    first = result["candidates"][0]["score_breakdown"]
    assert first["bm25"] >= 0
    assert first["embedding"] >= 0
    assert "Learning-to-Rank" in result["method"]


def test_confirmed_hs_feedback_activates_pairwise_ltr(monkeypatch):
    feedback = []
    for _ in range(6):
        feedback.append({
            "query_text": "cotton knitted t shirt",
            "selected_code": "610910",
            "candidate_codes": ["610990", "620520", "611020"],
        })
    reset(monkeypatch, feedback)
    result = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=5)
    assert result["ranking_model"] == "pairwise_logistic_ltr"
    assert result["feedback_count"] == 6
    assert result["candidates"][0]["code"] == "610910"


def test_hybrid_ranker_penalizes_classification_negation(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=5)
    by_code = {x["code"]: x for x in result["candidates"]}
    assert by_code["620520"]["score_breakdown"]["negation_conflict"] > 0
    assert by_code["610910"]["score_breakdown"]["negation_conflict"] == 0
    assert by_code["610910"]["score"] > by_code["620520"]["score"]


def test_hybrid_ranker_preserves_exact_numeric_hs_prefix_signal(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="850760", limit=5)
    assert result["candidates"][0]["code"] == "850760"
    assert result["candidates"][0]["score_breakdown"]["code_prefix"] == 1.0


def test_dense_embedding_does_not_amplify_unsupported_projection_noise(monkeypatch):
    reset(monkeypatch)
    result = ranker.hybrid_hs_candidates(query="cotton knitted t shirt", limit=7)
    by_code = {x["code"]: x for x in result["candidates"]}
    unrelated = by_code["850760"]["score_breakdown"]
    assert unrelated["bm25"] == 0.0
    assert unrelated["token_coverage"] == 0.0
    assert unrelated["embedding"] < 0.25
    assert by_code["610910"]["score_breakdown"]["embedding"] > unrelated["embedding"]


def test_dense_calibration_caps_semantic_only_outlier():
    import numpy as np

    raw = np.asarray([0.9965, 0.82], dtype=float)
    support = np.asarray([0.0, 0.64], dtype=float)
    calibrated = ranker._calibrate_dense_scores(raw, support)
    assert calibrated[0] < 0.13
    assert calibrated[1] > 0.65
