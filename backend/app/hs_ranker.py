from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from threading import RLock
from typing import Any, Iterable, Sequence

from .sources.hs_reference import get_hs_reference
from .storage import list_hs_ranking_feedback

HS_RANKER_REVISION = "r5-pure-python-deterministic"

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
_SEED_WEIGHTS = [0.32, 0.24, 0.18, 0.10, 0.05, -0.30, 0.03]
_EMBED_DIM = 256
_DENSE_NO_SUPPORT_CAP = 0.04


def _expand_phrases(text: str) -> str:
    out = str(text or "").lower().replace("’", "'")
    out = re.sub(r"\bt\s*[- ]\s*shirts?\b", " tshirt shirt ", out)
    out = re.sub(r"\btshirts?\b", " tshirt shirt ", out)
    return out


def _normalize_token(token: str) -> str:
    token = str(token or "").lower().strip("-'_")
    if not token:
        return ""
    if len(token) > 4 and token.endswith("ies") and not token.endswith("eies"):
        token = token[:-3] + "y"
    elif len(token) > 4 and token.endswith("es") and not token.endswith(("ses", "xes", "zes")):
        token = token[:-1]
    elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    return token


def _raw_tokens(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9]+", _expand_phrases(text))
    out: list[str] = []
    for token in raw:
        norm = _normalize_token(token)
        if norm:
            out.append(norm)
    return out


def _analyze_text(text: str) -> dict[str, Any]:
    raw = _raw_tokens(text)
    negated: set[str] = set()
    for i, token in enumerate(raw):
        if token not in _NEGATION_CUES:
            continue
        seen_content = 0
        for j in range(i + 1, min(len(raw), i + 6)):
            current = raw[j]
            if current in _NEGATION_BREAKS:
                break
            if current in {"and", "or", "the", "a", "an"}:
                continue
            if current not in _STOP and current not in _NEGATION_CUES and len(current) >= 2:
                negated.add(current)
                seen_content += 1
                if seen_content >= 2:
                    break

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
    return list(_analyze_text(text)["positive"])


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return {(tokens[i], tokens[i + 1]) for i in range(max(0, len(tokens) - 1))}


def _embedding_feature_counts(text: str) -> Counter[str]:
    analysis = _analyze_text(text)
    feats: Counter[str] = Counter()
    pos = analysis["positive"]
    for token in pos:
        feats[f"w:{token}"] += 1.0
        padded = f"^{token}$"
        for n in (3, 4, 5):
            for i in range(max(0, len(padded) - n + 1)):
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
        for key in feats:
            df[key] += 1
    return {key: math.log((1.0 + n) / (1.0 + count)) + 1.0 for key, count in df.items()}


def _weighted_feature_map(feats: Counter[str], idf: dict[str, float], n_docs: int) -> dict[str, float]:
    unseen_idf = math.log(1.0 + max(1, n_docs)) + 1.0
    out: dict[str, float] = {}
    for key, value in feats.items():
        tf = 1.0 + math.log(float(value)) if value > 1.0 else float(value)
        out[key] = tf * float(idf.get(key, unseen_idf))
    return out


def _stable_hash_slots(feature: str) -> tuple[int, float, int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
    first = int.from_bytes(digest[0:4], "little") % _EMBED_DIM
    second = int.from_bytes(digest[4:8], "little") % _EMBED_DIM
    sign_first = 1.0 if (digest[8] & 1) == 0 else -1.0
    sign_second = 1.0 if (digest[9] & 1) == 0 else -1.0
    return first, sign_first, second, sign_second


def _dense_hash_embedding(weighted: dict[str, float]) -> tuple[float, ...]:
    vec = [0.0] * _EMBED_DIM
    # sorted() makes accumulation order independent of dict/set iteration.
    for feature in sorted(weighted):
        value = float(weighted[feature])
        a, sa, b, sb = _stable_hash_slots(feature)
        vec[a] += sa * value
        vec[b] += sb * value * 0.7071067811865476
    norm = math.sqrt(math.fsum(value * value for value in vec))
    if norm <= 0.0:
        return tuple(vec)
    return tuple(value / norm for value in vec)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return math.fsum(float(a) * float(b) for a, b in zip(left, right))


def _sparse_cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    left_norm = math.sqrt(math.fsum(float(v) * float(v) for v in left.values()))
    right_norm = math.sqrt(math.fsum(float(v) * float(v) for v in right.values()))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    shared = sorted(set(left).intersection(right))
    dot = math.fsum(float(left[key]) * float(right[key]) for key in shared)
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _build_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    leaves = [row for row in rows if len(str(row.get("code") or "")) == 6]
    docs = [str(row.get("description") or "") for row in leaves]
    analyses = [_analyze_text(doc) for doc in docs]
    token_docs = [analysis["positive"] for analysis in analyses]
    n_docs = len(leaves)
    avgdl = sum(len(tokens) for tokens in token_docs) / max(1, n_docs)

    df: Counter[str] = Counter()
    for tokens in token_docs:
        for token in set(tokens):
            df[token] += 1

    raw_semantic = [_embedding_feature_counts(doc) for doc in docs]
    semantic_idf = _feature_idf(raw_semantic)
    semantic_weighted = [_weighted_feature_map(features, semantic_idf, n_docs) for features in raw_semantic]
    dense = [_dense_hash_embedding(weighted) for weighted in semantic_weighted]
    code_idx = {str(row["code"]): idx for idx, row in enumerate(leaves)}
    return {
        "rows": leaves,
        "docs": docs,
        "analyses": analyses,
        "tokens": token_docs,
        "df": df,
        "avgdl": avgdl,
        "semantic_idf": semantic_idf,
        "semantic_weighted": semantic_weighted,
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


def _bm25_scores(index: dict[str, Any], query: str, k1: float = 1.5, b: float = 0.75) -> list[float]:
    query_tokens = _analyze_text(query)["positive"]
    n_docs = len(index["rows"])
    scores = [0.0] * n_docs
    if not query_tokens:
        return scores
    for idx, tokens in enumerate(index["tokens"]):
        counts = Counter(tokens)
        dl = len(tokens)
        total = 0.0
        for term in query_tokens:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            df = index["df"].get(term, 0)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1.0 - b + b * dl / max(index["avgdl"], 1e-9))
            total += idf * (frequency * (k1 + 1.0) / denominator)
        scores[idx] = total
    return scores


def _calibrate_dense_scores(dense_scores: Iterable[float], sparse_support: Iterable[float]) -> list[float]:
    calibrated: list[float] = []
    for raw, support in zip(dense_scores, sparse_support):
        dense = max(0.0, min(1.0, float(raw)))
        direct = max(0.0, min(1.0, float(support)))
        reliability = 0.04 + 0.96 * math.sqrt(direct)
        value = dense * reliability
        if direct <= 0.0:
            value = min(value, _DENSE_NO_SUPPORT_CAP)
        calibrated.append(max(0.0, min(1.0, value)))
    return calibrated


def _semantic_scores(index: dict[str, Any], query: str) -> list[float]:
    if not index["rows"]:
        return []
    raw = _embedding_feature_counts(query)
    if not raw:
        return [0.0] * len(index["rows"])
    weighted = _weighted_feature_map(raw, index["semantic_idf"], len(index["rows"]))
    query_vec = _dense_hash_embedding(weighted)
    dense_raw = [max(0.0, min(1.0, _dot(doc_vec, query_vec))) for doc_vec in index["dense"]]
    direct_support = [_sparse_cosine(weighted, doc) for doc in index["semantic_weighted"]]
    return _calibrate_dense_scores(dense_raw, direct_support)


def _minmax(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    low = min(float(v) for v in values)
    high = max(float(v) for v in values)
    if high - low < 1e-12:
        return [0.0] * len(values)
    return [(float(v) - low) / (high - low) for v in values]


def _feature_matrix(index: dict[str, Any], query: str) -> tuple[list[list[float]], list[float], list[float]]:
    bm25 = _bm25_scores(index, query)
    semantic = _semantic_scores(index, query)
    bm25_norm = _minmax(bm25)

    query_analysis = _analyze_text(query)
    query_tokens = query_analysis["positive_unique"]
    query_negative = set(query_analysis["negative_unique"])
    query_bigrams = _bigrams(query_analysis["positive"])
    query_phrase = " ".join(query_analysis["positive"])
    digits = "".join(ch for ch in query if ch.isdigit())

    features: list[list[float]] = []
    for idx, row in enumerate(index["rows"]):
        analysis = index["analyses"][idx]
        token_set = set(analysis["positive"])
        doc_negated = set(analysis["negated"])
        coverage = sum(1 for token in query_tokens if token in token_set) / max(1, len(query_tokens))

        semantic_score = float(semantic[idx])
        if coverage <= 0.0 and bm25[idx] <= 0.0:
            semantic_score = min(semantic_score, _DENSE_NO_SUPPORT_CAP)

        doc_bigrams = _bigrams(analysis["positive"])
        bigram_overlap = len(query_bigrams & doc_bigrams) / max(1, len(query_bigrams)) if query_bigrams else 0.0
        positive_text = " ".join(analysis["positive"])
        phrase = 1.0 if query_phrase and query_phrase in positive_text else 0.0

        positive_conflict = len(set(query_tokens) & doc_negated) / max(1, len(query_tokens))
        negative_conflict = len(query_negative & token_set) / max(1, len(query_negative)) if query_negative else 0.0
        negation_conflict = min(1.0, positive_conflict + negative_conflict)

        code_prefix = 0.0
        if digits and str(row.get("code") or "").startswith(digits[:6]):
            code_prefix = min(1.0, len(digits[:6]) / 6.0)

        features.append([
            float(bm25_norm[idx]),
            semantic_score,
            float(coverage),
            float(bigram_overlap),
            float(phrase),
            float(negation_conflict),
            float(code_prefix),
        ])
    return features, bm25, semantic


def _normalize_weights(weights: Sequence[float]) -> list[float]:
    denominator = math.fsum(abs(float(weight)) for weight in weights) or 1.0
    return [float(weight) / denominator for weight in weights]


def _pairwise_logistic_fit(diffs: list[list[float]], seed: Sequence[float]) -> list[float]:
    weights = [float(value) for value in seed]
    if not diffs:
        return _normalize_weights(weights)
    learning_rate = 0.22
    l2 = 0.06
    prior = [float(value) for value in seed]

    for step in range(220):
        gradient = [0.0] * len(weights)
        for diff in diffs:
            z = max(-30.0, min(30.0, _dot(weights, diff)))
            gain = 1.0 / (1.0 + math.exp(z))
            for idx, value in enumerate(diff):
                gradient[idx] += gain * float(value)
        count = max(1, len(diffs))
        factor = learning_rate / math.sqrt(1.0 + step * 0.03)
        for idx in range(len(weights)):
            gradient[idx] = gradient[idx] / count - l2 * (weights[idx] - prior[idx])
            weights[idx] += factor * gradient[idx]

    neg_idx = _FEATURE_NAMES.index("negation_conflict")
    weights[neg_idx] = min(weights[neg_idx], -0.02)
    return _normalize_weights(weights)


def _ltr_weights(index: dict[str, Any]) -> tuple[list[float], str, int]:
    feedback = list_hs_ranking_feedback(limit=300)
    diffs: list[list[float]] = []
    for item in feedback:
        query = str(item.get("query_text") or "").strip()
        selected = str(item.get("selected_code") or "")
        if not query or selected not in index["code_idx"]:
            continue
        features, _, _ = _feature_matrix(index, query)
        selected_idx = index["code_idx"][selected]
        candidates = sorted({
            str(code) for code in item.get("candidate_codes") or []
            if str(code) in index["code_idx"] and str(code) != selected
        })
        for code in candidates[:16]:
            other_idx = index["code_idx"][code]
            diff = [a - b for a, b in zip(features[selected_idx], features[other_idx])]
            if max((abs(value) for value in diff), default=0.0) >= 1e-12:
                diffs.append(diff)

    seed = _normalize_weights(_SEED_WEIGHTS)
    if len(diffs) >= 6:
        learned = _pairwise_logistic_fit(diffs, seed)
        pair_count = len(diffs)
        prior_share = max(0.20, min(0.50, 12.0 / (12.0 + pair_count)))
        blended = _normalize_weights([
            prior_share * a + (1.0 - prior_share) * b for a, b in zip(seed, learned)
        ])
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
        parts.extend(str(value) for value in category_path if value)
    if attributes:
        for key in sorted(attributes):
            value = attributes[key]
            if value not in (None, "", False):
                parts.extend([str(key), str(value)])
    context = " ".join(parts).strip()

    features, bm25, semantic = _feature_matrix(index, context)
    weights, model_name, feedback_count = _ltr_weights(index)
    scores = [_dot(row, weights) for row in features]

    candidate_indices = list(range(len(index["rows"])))
    bm25_top = sorted(candidate_indices, key=lambda i: (-bm25[i], str(index["rows"][i].get("code") or "")))[:100]
    semantic_top = sorted(candidate_indices, key=lambda i: (-semantic[i], str(index["rows"][i].get("code") or "")))[:100]
    score_top = sorted(candidate_indices, key=lambda i: (-scores[i], str(index["rows"][i].get("code") or "")))[:120]
    pool = sorted(set(bm25_top + semantic_top + score_top))

    ranked = sorted(
        pool,
        key=lambda i: (
            -scores[i],
            -features[i][0],
            -features[i][2],
            str(index["rows"][i].get("code") or ""),
        ),
    )

    top: list[dict[str, Any]] = []
    max_score = scores[ranked[0]] if ranked else 1.0
    anchor_index = min(len(ranked) - 1, max(limit * 3, 1)) if ranked else 0
    min_score = scores[ranked[anchor_index]] if ranked else 0.0
    span = max(max_score - min_score, 1e-9)

    for idx in ranked[:max(1, min(limit, 20))]:
        row = index["rows"][idx]
        relative = max(0.0, min(1.0, (scores[idx] - min_score) / span))
        top.append({
            **row,
            "score": round(scores[idx], 6),
            "relative_confidence": round(relative, 4),
            "score_breakdown": {
                "bm25": round(features[idx][0], 4),
                "embedding": round(features[idx][1], 4),
                "token_coverage": round(features[idx][2], 4),
                "bigram_overlap": round(features[idx][3], 4),
                "phrase": round(features[idx][4], 4),
                "negation_conflict": round(features[idx][5], 4),
                "code_prefix": round(features[idx][6], 4),
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
            "+ pure-Python deterministic pairwise logistic Learning-to-Rank from confirmed HS selections."
        ),
        "ranking_model": model_name,
        "feedback_count": feedback_count,
        "feature_weights": {name: round(value, 4) for name, value in zip(_FEATURE_NAMES, weights)},
        "ranker_revision": HS_RANKER_REVISION,
    }
