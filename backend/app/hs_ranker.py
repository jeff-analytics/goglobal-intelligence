from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from threading import RLock
from typing import Any

import numpy as np

from .sources.hs_reference import get_hs_reference
from .storage import list_hs_ranking_feedback

# HS descriptions contain classification-critical negations (for example
# "not knitted or crocheted"). Treating "not" as an ordinary stop word can
# invert candidate meaning, so negation is modelled explicitly.
_STOP = {
    "and", "or", "the", "a", "an", "of", "for", "with", "to", "in", "on", "by", "from",
    "item", "items", "product", "products", "other", "including", "whether", "elsewhere",
}
_NEGATION_CUES = {"not", "no", "without", "excluding", "except", "non"}
_NEGATION_BREAKS = {"of", "with", "for", "from", "in", "on", "by", "but", "than"}
_CACHE: dict[str, Any] = {}
_LOCK = RLock()

_FEATURE_NAMES = [
    "bm25",
    "embedding",
    "token_coverage",
    "bigram_overlap",
    "phrase",
    "negation_conflict",
    "code_prefix",
]

# Cold-start prior. The negative coefficient is intentional: a candidate that
# explicitly negates a user requirement should be demoted. This is a generic
# nomenclature feature and does not encode any specific HS code.
_SEED_WEIGHTS = np.asarray([0.32, 0.24, 0.18, 0.10, 0.05, -0.30, 0.03], dtype=float)

# The dense representation is a deterministic feature-hash embedding. Unlike
# a fitted SVD, it has no BLAS-dependent latent rotation, so the same query and
# HS reference yield the same ranking on macOS, Windows and GitHub Linux.
_EMBED_DIM = 384


def _expand_phrases(text: str) -> str:
    out = str(text or "").lower().replace("’", "'")
    out = re.sub(r"\bt\s*[- ]\s*shirts?\b", " tshirt shirt ", out)
    out = re.sub(r"\btshirts?\b", " tshirt shirt ", out)
    return out


def _normalize_token(token: str) -> str:
    token = str(token or "").lower().strip("-'_")
    if not token:
        return ""
    # Conservative plural normalization improves matching without a heavyweight
    # NLP runtime or model download.
    if len(token) > 4 and token.endswith("ies") and not token.endswith("eies"):
        token = token[:-3] + "y"
    elif len(token) > 4 and token.endswith("es") and not token.endswith(("ses", "xes", "zes")):
        token = token[:-1]
    elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    return token


def _raw_tokens(text: str) -> list[str]:
    expanded = _expand_phrases(text)
    raw = re.findall(r"[a-z0-9]+", expanded)
    out: list[str] = []
    for t in raw:
        norm = _normalize_token(t)
        if norm:
            out.append(norm)
    return out


def _analyze_text(text: str) -> dict[str, Any]:
    raw = _raw_tokens(text)
    negated: set[str] = set()

    # Capture short coordinated negations such as "not knitted or crocheted".
    for i, token in enumerate(raw):
        if token not in _NEGATION_CUES:
            continue
        seen_content = 0
        j = i + 1
        while j < len(raw) and j <= i + 5:
            current = raw[j]
            if current in _NEGATION_BREAKS:
                break
            if current in {"and", "or", "the", "a", "an"}:
                j += 1
                continue
            if current not in _STOP and current not in _NEGATION_CUES and len(current) >= 2:
                negated.add(current)
                seen_content += 1
                if seen_content >= 2:
                    break
            j += 1

    positive: list[str] = []
    negative_query: list[str] = []
    for token in raw:
        if token in _NEGATION_CUES or token in _STOP or len(token) < 2:
            continue
        if token in negated:
            negative_query.append(token)
        else:
            positive.append(token)

    return {
        "raw": raw,
        "positive": positive,
        "positive_unique": list(dict.fromkeys(positive)),
        "negated": negated,
        "negative_unique": list(dict.fromkeys(negative_query)),
    }


def _tokens(text: str) -> list[str]:
    """Backwards-compatible positive-token helper."""
    return list(_analyze_text(text)["positive"])


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return {(tokens[i], tokens[i + 1]) for i in range(max(0, len(tokens) - 1))}


def _embedding_feature_counts(text: str) -> Counter[str]:
    """Create deterministic lexical/orthographic features for dense embedding.

    The result is still embedded into a compact dense vector below, but the
    source features are explicit and stable. Character n-grams provide robust
    spelling/morphology matching while word/bigram features retain commodity
    meaning. Negated terms are namespaced so they cannot masquerade as positive
    evidence.
    """
    analysis = _analyze_text(text)
    feats: Counter[str] = Counter()
    pos = analysis["positive"]

    for token in pos:
        feats[f"w:{token}"] += 1.0
        padded = f"^{token}$"
        for n in (3, 4, 5):
            if len(padded) < n:
                continue
            for i in range(len(padded) - n + 1):
                feats[f"c{n}:{padded[i:i+n]}"] += 0.18

    for a, b in zip(pos, pos[1:]):
        feats[f"b:{a}_{b}"] += 1.25

    for token in sorted(analysis["negated"]):
        feats[f"neg:{token}"] += 1.0

    return feats


def _feature_idf(rows_features: list[Counter[str]]) -> dict[str, float]:
    n = max(1, len(rows_features))
    df: Counter[str] = Counter()
    for feats in rows_features:
        for key in feats.keys():
            df[key] += 1
    return {k: math.log((1.0 + n) / (1.0 + v)) + 1.0 for k, v in df.items()}


def _weighted_feature_map(
    feats: Counter[str],
    idf: dict[str, float],
    n_docs: int,
) -> dict[str, float]:
    unseen_idf = math.log(1.0 + max(1, n_docs)) + 1.0
    out: dict[str, float] = {}
    for key, value in feats.items():
        # Sublinear TF avoids one repeated token dominating the embedding.
        tf = 1.0 + math.log(max(float(value), 1e-12)) if value > 1.0 else float(value)
        out[key] = tf * float(idf.get(key, unseen_idf))
    return out


def _stable_hash_slots(feature: str) -> tuple[int, float, int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
    a = int.from_bytes(digest[0:4], "little") % _EMBED_DIM
    b = int.from_bytes(digest[4:8], "little") % _EMBED_DIM
    sa = 1.0 if (digest[8] & 1) == 0 else -1.0
    sb = 1.0 if (digest[9] & 1) == 0 else -1.0
    return a, sa, b, sb


def _dense_hash_embedding(weighted: dict[str, float]) -> np.ndarray:
    vec = np.zeros(_EMBED_DIM, dtype=np.float64)
    for feature, value in weighted.items():
        a, sa, b, sb = _stable_hash_slots(feature)
        # Two independently signed slots reduce collision variance while
        # remaining fully deterministic across Python/OS versions.
        vec[a] += sa * value
        vec[b] += sb * value * 0.7071067811865476
    norm = math.sqrt(math.fsum(float(x) * float(x) for x in vec))
    if norm > 0:
        vec /= norm
    return vec


def _sparse_cosine(
    left: dict[str, float],
    left_norm: float,
    right: dict[str, float],
    right_norm: float,
) -> float:
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    # Iterate over the smaller map for deterministic and efficient direct
    # evidence support.
    if len(left) > len(right):
        left, right = right, left
    dot = math.fsum(float(v) * float(right.get(k, 0.0)) for k, v in left.items())
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _build_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    leaves = [r for r in rows if len(str(r.get("code") or "")) == 6]
    docs = [str(r.get("description") or "") for r in leaves]
    analyses = [_analyze_text(x) for x in docs]
    token_docs = [a["positive"] for a in analyses]
    n = len(leaves)
    avgdl = sum(len(x) for x in token_docs) / max(1, n)

    df = Counter()
    for toks in token_docs:
        for t in set(toks):
            df[t] += 1

    raw_semantic = [_embedding_feature_counts(x) for x in docs]
    semantic_idf = _feature_idf(raw_semantic)
    weighted_semantic = [_weighted_feature_map(x, semantic_idf, n) for x in raw_semantic]
    semantic_norms = [math.sqrt(math.fsum(v * v for v in x.values())) for x in weighted_semantic]
    dense = np.vstack([_dense_hash_embedding(x) for x in weighted_semantic]) if leaves else np.zeros((0, _EMBED_DIM))

    code_idx = {str(r["code"]): i for i, r in enumerate(leaves)}
    return {
        "rows": leaves,
        "docs": docs,
        "analyses": analyses,
        "tokens": token_docs,
        "df": df,
        "avgdl": avgdl,
        "semantic_idf": semantic_idf,
        "semantic_weighted": weighted_semantic,
        "semantic_norms": semantic_norms,
        "dense": dense,
        "code_idx": code_idx,
    }


def _index() -> dict[str, Any]:
    rows = get_hs_reference()
    key = (
        len(rows),
        str(rows[0].get("code") if rows else ""),
        str(rows[-1].get("code") if rows else ""),
        str(rows[0].get("description") if rows else "")[:80],
        str(rows[-1].get("description") if rows else "")[:80],
    )
    with _LOCK:
        if _CACHE.get("key") != key:
            _CACHE.clear()
            _CACHE["key"] = key
            _CACHE["index"] = _build_index(rows)
        return _CACHE["index"]


def _bm25_scores(index: dict[str, Any], query: str, k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    q = _analyze_text(query)["positive"]
    n = len(index["rows"])
    scores = np.zeros(n, dtype=float)
    if not q:
        return scores
    for i, toks in enumerate(index["tokens"]):
        counts = Counter(toks)
        dl = len(toks)
        s = 0.0
        for term in q:
            f = counts.get(term, 0)
            if not f:
                continue
            df = index["df"].get(term, 0)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            denom = f + k1 * (1 - b + b * dl / max(index["avgdl"], 1e-9))
            s += idf * (f * (k1 + 1) / denom)
        scores[i] = s
    return scores


def _calibrate_dense_scores(dense_scores: np.ndarray, sparse_support: np.ndarray) -> np.ndarray:
    """Calibrate dense cosine by direct text support.

    A dense-only score is allowed a small floor for discovery, but it cannot
    dominate candidates when there is no direct word/character evidence. This
    prevents projection/hash-collision noise from producing CI-only ranking
    inversions while preserving the embedding signal for genuine overlap.
    """
    dense = np.clip(np.asarray(dense_scores, dtype=float), 0.0, 1.0)
    support = np.clip(np.asarray(sparse_support, dtype=float), 0.0, 1.0)
    reliability = 0.04 + 0.96 * np.sqrt(support)
    return np.clip(dense * reliability, 0.0, 1.0)


def _semantic_scores(index: dict[str, Any], query: str) -> np.ndarray:
    if not index["rows"]:
        return np.zeros(0, dtype=float)

    raw = _embedding_feature_counts(query)
    if not raw:
        return np.zeros(len(index["rows"]), dtype=float)
    weighted = _weighted_feature_map(raw, index["semantic_idf"], len(index["rows"]))
    q_norm = math.sqrt(math.fsum(v * v for v in weighted.values()))
    if q_norm <= 0:
        return np.zeros(len(index["rows"]), dtype=float)

    q_vec = _dense_hash_embedding(weighted)
    # Matrix-vector multiplication is only used for the compact deterministic
    # embedding. Direct support below prevents tiny platform-specific floating
    # differences from changing unsupported candidates into strong matches.
    dense_raw = np.asarray(index["dense"] @ q_vec, dtype=float)
    dense_raw = np.clip(dense_raw, 0.0, 1.0)

    support = np.asarray([
        _sparse_cosine(weighted, q_norm, doc, doc_norm)
        for doc, doc_norm in zip(index["semantic_weighted"], index["semantic_norms"])
    ], dtype=float)
    return _calibrate_dense_scores(dense_raw, support)


def _minmax(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    lo = float(np.min(x))
    hi = float(np.max(x))
    if hi - lo < 1e-12:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def _feature_matrix(index: dict[str, Any], query: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bm = _bm25_scores(index, query)
    sem = _semantic_scores(index, query)
    bmn = _minmax(bm)
    semn = np.clip(sem, 0.0, 1.0)

    q_analysis = _analyze_text(query)
    qtok = q_analysis["positive_unique"]
    qneg = set(q_analysis["negative_unique"])
    q_bigrams = _bigrams(q_analysis["positive"])
    qphrase = " ".join(q_analysis["positive"])
    digits = "".join(ch for ch in query if ch.isdigit())

    feats = []
    for i, row in enumerate(index["rows"]):
        analysis = index["analyses"][i]
        toks = set(analysis["positive"])
        doc_neg = set(analysis["negated"])
        coverage = sum(1 for t in qtok if t in toks) / max(1, len(qtok))

        doc_bigrams = _bigrams(analysis["positive"])
        bigram_overlap = len(q_bigrams & doc_bigrams) / max(1, len(q_bigrams)) if q_bigrams else 0.0

        positive_text = " ".join(analysis["positive"])
        phrase = 1.0 if qphrase and qphrase in positive_text else 0.0

        positive_conflict = len(set(qtok) & doc_neg) / max(1, len(qtok))
        negative_conflict = len(qneg & toks) / max(1, len(qneg)) if qneg else 0.0
        negation_conflict = min(1.0, positive_conflict + negative_conflict)

        chapter_match = 0.0
        if digits and str(row.get("code") or "").startswith(digits[:6]):
            chapter_match = min(1.0, len(digits[:6]) / 6.0)

        feats.append([
            float(bmn[i]),
            float(semn[i]),
            float(coverage),
            float(bigram_overlap),
            float(phrase),
            float(negation_conflict),
            float(chapter_match),
        ])
    return np.asarray(feats, dtype=float), bm, sem


def _normalize_weights(weights: np.ndarray) -> np.ndarray:
    denom = float(np.sum(np.abs(weights))) or 1.0
    return np.asarray(weights, dtype=float) / denom


def _pairwise_logistic_fit(diffs: list[np.ndarray], seed: np.ndarray) -> np.ndarray:
    """Deterministic pairwise logistic Learning-to-Rank.

    The previous implementation delegated to a native solver. Fixed-iteration
    gradient updates avoid solver/BLAS-dependent coefficient drift while still
    learning from confirmed selected > rejected pairs.
    """
    w = np.asarray(seed, dtype=float).copy()
    if not diffs:
        return _normalize_weights(w)

    lr = 0.22
    l2 = 0.06
    prior = np.asarray(seed, dtype=float)
    ordered = [np.asarray(d, dtype=float) for d in diffs]

    for step in range(220):
        grad = np.zeros_like(w)
        for d in ordered:
            z = float(np.dot(w, d))
            z = max(-30.0, min(30.0, z))
            # derivative of log(sigmoid(w·d))
            gain = 1.0 / (1.0 + math.exp(z))
            grad += gain * d
        grad /= max(1, len(ordered))
        grad -= l2 * (w - prior)
        w += (lr / math.sqrt(1.0 + step * 0.03)) * grad

    # Preserve the generic semantic safety sign even with sparse/misaligned
    # feedback; users can learn relative strength, but explicit contradiction
    # should never become a positive feature.
    neg_idx = _FEATURE_NAMES.index("negation_conflict")
    w[neg_idx] = min(float(w[neg_idx]), -0.02)
    return _normalize_weights(w)


def _ltr_weights(index: dict[str, Any]) -> tuple[np.ndarray, str, int]:
    feedback = list_hs_ranking_feedback(limit=300)
    diffs: list[np.ndarray] = []
    for item in feedback:
        query = str(item.get("query_text") or "").strip()
        selected = str(item.get("selected_code") or "")
        if not query or selected not in index["code_idx"]:
            continue
        feats, _, _ = _feature_matrix(index, query)
        si = index["code_idx"][selected]
        candidates = [
            str(x) for x in item.get("candidate_codes") or []
            if str(x) in index["code_idx"] and str(x) != selected
        ]
        for code in candidates[:16]:
            oi = index["code_idx"][code]
            diff = feats[si] - feats[oi]
            if float(np.max(np.abs(diff))) >= 1e-12:
                diffs.append(diff)

    seed = _normalize_weights(_SEED_WEIGHTS)
    if len(diffs) >= 6:
        learned = _pairwise_logistic_fit(diffs, seed)
        pair_count = len(diffs)
        prior_share = max(0.20, min(0.50, 12.0 / (12.0 + pair_count)))
        blended = _normalize_weights(prior_share * seed + (1.0 - prior_share) * learned)
        return blended, "pairwise_logistic_ltr", len(feedback)
    return seed, "seeded_pairwise_ranker", len(feedback)


def hybrid_hs_candidates(
    *,
    query: str,
    category_path: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    index = _index()
    parts = [query]
    if category_path:
        parts.extend(str(x) for x in category_path if x)
    if attributes:
        for k, v in attributes.items():
            if v not in (None, "", False):
                parts.extend([str(k), str(v)])
    context = " ".join(parts).strip()

    feats, bm, sem = _feature_matrix(index, context)
    weights, model_name, feedback_count = _ltr_weights(index)
    score = feats @ weights

    pool = (
        set(np.argsort(bm)[-100:].tolist())
        | set(np.argsort(sem)[-100:].tolist())
        | set(np.argsort(score)[-120:].tolist())
    )
    # Fully deterministic tie-breaking: ranking score, lexical evidence,
    # coverage, then code ascending. The final code key removes set-order
    # dependence when several candidates are exactly tied at zero.
    ranked = sorted(
        pool,
        key=lambda i: (
            -float(score[i]),
            -float(feats[i, 0]),
            -float(feats[i, 2]),
            str(index["rows"][i].get("code") or ""),
        ),
    )

    top: list[dict[str, Any]] = []
    max_score = float(score[ranked[0]]) if ranked else 1.0
    anchor_index = min(len(ranked) - 1, max(limit * 3, 1)) if ranked else 0
    min_score = float(score[ranked[anchor_index]]) if ranked else 0.0
    span = max(max_score - min_score, 1e-9)

    for i in ranked[:max(1, min(limit, 20))]:
        row = index["rows"][i]
        rel = max(0.0, min(1.0, (float(score[i]) - min_score) / span))
        top.append({
            **row,
            "score": round(float(score[i]), 6),
            "relative_confidence": round(rel, 4),
            "score_breakdown": {
                "bm25": round(float(feats[i, 0]), 4),
                "embedding": round(float(feats[i, 1]), 4),
                "token_coverage": round(float(feats[i, 2]), 4),
                "bigram_overlap": round(float(feats[i, 3]), 4),
                "phrase": round(float(feats[i, 4]), 4),
                "negation_conflict": round(float(feats[i, 5]), 4),
                "code_prefix": round(float(feats[i, 6]), 4),
            },
        })

    return {
        "query": query,
        "query_context": context,
        "candidates": top,
        "count": len(top),
        "source": "UN Comtrade HS reference",
        "method": (
            "BM25 lexical retrieval + deterministic local dense feature-hash embedding "
            "(word/bigram and character n-gram features) + negation-aware nomenclature features "
            "+ deterministic pairwise logistic Learning-to-Rank from confirmed HS selections."
        ),
        "ranking_model": model_name,
        "feedback_count": feedback_count,
        "feature_weights": {k: round(float(v), 4) for k, v in zip(_FEATURE_NAMES, weights)},
    }
