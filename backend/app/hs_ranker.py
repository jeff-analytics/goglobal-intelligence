from __future__ import annotations

import math
import re
from collections import Counter
from threading import RLock
from typing import Any

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import normalize

from .sources.hs_reference import get_hs_reference
from .storage import list_hs_ranking_feedback

# HS descriptions contain classification-critical negations (for example
# "not knitted or crocheted").  Treating "not" as an ordinary stop word can
# invert the meaning of a candidate, so negation is handled separately below.
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
# Cold-start prior.  The negative coefficient is intentional: a candidate
# that explicitly negates a user requirement should be demoted.  This is a
# domain-semantic feature, not an HS-code-specific rule.
_SEED_WEIGHTS = np.asarray([0.32, 0.24, 0.18, 0.10, 0.05, -0.30, 0.03], dtype=float)


def _expand_phrases(text: str) -> str:
    """Normalize a small set of orthographic variants without class rules.

    The replacement keeps both a phrase token and the generic noun so that
    "T-shirt" can match "t shirt" while still retaining ordinary "shirt"
    evidence.  No HS codes or chapter-specific decisions are embedded here.
    """
    out = str(text or "").lower().replace("’", "'")
    out = re.sub(r"\bt\s*[- ]\s*shirts?\b", " tshirt shirt ", out)
    out = re.sub(r"\btshirts?\b", " tshirt shirt ", out)
    return out


def _normalize_token(token: str) -> str:
    token = str(token or "").lower().strip("-'_")
    if not token:
        return ""
    # Conservative plural normalization helps user wording match official HS
    # descriptions (shirt/shirts, battery/batteries) without a heavyweight NLP
    # runtime or internet model download.
    if len(token) > 4 and token.endswith("ies") and not token.endswith("eies"):
        token = token[:-3] + "y"
    elif len(token) > 4 and token.endswith("es") and not token.endswith(("ses", "xes", "zes")):
        # Keep words such as glasses/boxes stable; plain trailing-s handling
        # below covers most commodity nouns.
        token = token[:-1]
    elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    return token


def _raw_tokens(text: str) -> list[str]:
    expanded = _expand_phrases(text)
    raw = re.findall(r"[a-z0-9]+", expanded)
    return [_normalize_token(t) for t in raw if _normalize_token(t)]


def _analyze_text(text: str) -> dict[str, Any]:
    raw = _raw_tokens(text)
    negated: set[str] = set()

    # Capture "not X", "not X or Y", "without X", "non X" and similar short
    # coordinated descriptions that frequently occur in tariff nomenclature.
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
                # One content term is enough unless it is followed by a short
                # coordination such as "knitted or crocheted".
                if seen_content >= 2:
                    break
            j += 1

    positive: list[str] = []
    negative_query: list[str] = []
    for i, token in enumerate(raw):
        if token in _NEGATION_CUES or token in _STOP or len(token) < 2:
            continue
        if token in negated:
            negative_query.append(token)
        else:
            positive.append(token)

    # Preserve order while removing duplicates only for coverage calculations;
    # BM25 still uses the full positive token list and therefore term frequency.
    unique_positive = list(dict.fromkeys(positive))
    unique_negative = list(dict.fromkeys(negative_query))
    return {
        "raw": raw,
        "positive": positive,
        "positive_unique": unique_positive,
        "negated": negated,
        "negative_unique": unique_negative,
        "semantic_text": " ".join(positive + [f"neg_{x}" for x in sorted(negated)]),
    }


def _tokens(text: str) -> list[str]:
    """Backwards-compatible positive-token helper used by tests/consumers."""
    return list(_analyze_text(text)["positive"])


def _build_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    leaves = [r for r in rows if len(str(r.get("code") or "")) == 6]
    docs = [str(r.get("description") or "") for r in leaves]
    analyses = [_analyze_text(x) for x in docs]
    token_docs = [a["positive"] for a in analyses]
    semantic_docs = [a["semantic_text"] or "empty" for a in analyses]
    n = len(leaves)
    avgdl = sum(len(x) for x in token_docs) / max(1, n)
    df = Counter()
    for toks in token_docs:
        for t in set(toks):
            df[t] += 1

    # Local dense embedding: lexical word/bigram and character n-gram TF-IDF
    # are projected into a compact latent semantic space via TruncatedSVD.
    # This keeps the desktop app offline/local-first and avoids silently
    # downloading a transformer model while still providing a dense signal.
    vectorizer = FeatureUnion([
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, max_features=24000, sublinear_tf=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, max_features=32000, sublinear_tf=True)),
    ], transformer_weights={"word": 1.15, "char": 0.85})
    X = vectorizer.fit_transform(semantic_docs)
    max_comp = min(96, max(1, X.shape[0] - 1), max(1, X.shape[1] - 1))
    svd = TruncatedSVD(n_components=max_comp, random_state=42)
    dense = normalize(svd.fit_transform(X))
    code_idx = {str(r["code"]): i for i, r in enumerate(leaves)}
    return {
        "rows": leaves,
        "docs": docs,
        "analyses": analyses,
        "tokens": token_docs,
        "df": df,
        "avgdl": avgdl,
        "vectorizer": vectorizer,
        "svd": svd,
        "dense": dense,
        "code_idx": code_idx,
    }


def _index() -> dict[str, Any]:
    rows = get_hs_reference()
    # Include descriptions in the cache signature so tests/reference refreshes
    # with identical first/last codes cannot accidentally reuse an old index.
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


def _bm25_scores(index: dict[str, Any], query: str, k1: float = 1.5, b: float = .75) -> np.ndarray:
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
            idf = math.log(1 + (n - df + .5) / (df + .5))
            denom = f + k1 * (1 - b + b * dl / max(index["avgdl"], 1e-9))
            s += idf * (f * (k1 + 1) / denom)
        scores[i] = s
    return scores


def _semantic_scores(index: dict[str, Any], query: str) -> np.ndarray:
    analysis = _analyze_text(query)
    semantic_query = analysis["semantic_text"]
    if not semantic_query.strip():
        return np.zeros(len(index["rows"]), dtype=float)
    q = index["vectorizer"].transform([semantic_query])
    qv = normalize(index["svd"].transform(q))[0]
    return np.asarray(index["dense"] @ qv, dtype=float)


def _minmax(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    lo = float(np.min(x)); hi = float(np.max(x))
    if hi - lo < 1e-12:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return {(tokens[i], tokens[i + 1]) for i in range(max(0, len(tokens) - 1))}


def _feature_matrix(index: dict[str, Any], query: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bm = _bm25_scores(index, query)
    sem = _semantic_scores(index, query)
    bmn = _minmax(bm)
    semn = _minmax(sem)

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

        # Penalize semantic contradictions rather than deleting the evidence.
        # This is especially important for legal/tariff phrases such as
        # "not knitted", "without cocoa" or "excluding ...".
        positive_conflict = len(set(qtok) & doc_neg) / max(1, len(qtok))
        negative_conflict = len(qneg & toks) / max(1, len(qneg)) if qneg else 0.0
        negation_conflict = min(1.0, positive_conflict + negative_conflict)

        chapter_match = 0.0
        if digits and str(row.get("code") or "").startswith(digits[:6]):
            # Longer numeric prefixes are much more informative; feature stays
            # in [0,1] and remains generic across all HS chapters.
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


def _ltr_weights(index: dict[str, Any]) -> tuple[np.ndarray, str, int]:
    feedback = list_hs_ranking_feedback(limit=300)
    X: list[np.ndarray] = []
    y: list[int] = []
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
            if float(np.max(np.abs(diff))) < 1e-12:
                continue
            # Pairwise logistic ranking: selected > alternative.
            X.append(diff); y.append(1)
            X.append(-diff); y.append(0)

    seed = _normalize_weights(_SEED_WEIGHTS)
    if len(X) >= 12 and len(set(y)) == 2:
        try:
            model = LogisticRegression(
                C=0.75,
                fit_intercept=False,
                solver="liblinear",
                random_state=42,
                max_iter=1000,
            )
            model.fit(np.asarray(X), np.asarray(y))
            learned = _normalize_weights(model.coef_[0])
            # Sparse user feedback should adapt the ranking without erasing
            # safety semantics learned from the nomenclature itself.  Blend a
            # diminishing cold-start prior with the pairwise LTR weights.
            pair_count = len(X) // 2
            prior_share = max(0.20, min(0.50, 12.0 / (12.0 + pair_count)))
            blended = _normalize_weights(prior_share * seed + (1.0 - prior_share) * learned)
            return blended, "pairwise_logistic_ltr", len(feedback)
        except Exception:
            pass
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

    # Candidate generation is high-recall: union strong sparse, dense and
    # current-ranker hits before pairwise reranking.  Exact/prefix code queries
    # are also retained through the score feature rather than a hard-coded code.
    pool = (
        set(np.argsort(bm)[-100:].tolist())
        | set(np.argsort(sem)[-100:].tolist())
        | set(np.argsort(score)[-120:].tolist())
    )
    ranked = sorted(pool, key=lambda i: (float(score[i]), float(feats[i, 2]), float(feats[i, 0])), reverse=True)

    top = []
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
            "BM25 lexical retrieval + local dense LSA embedding (word/bigram and character TF-IDF projected with SVD) "
            "+ negation-aware nomenclature features + pairwise logistic Learning-to-Rank from confirmed HS selections."
        ),
        "ranking_model": model_name,
        "feedback_count": feedback_count,
        "feature_weights": {k: round(float(v), 4) for k, v in zip(_FEATURE_NAMES, weights)},
    }
