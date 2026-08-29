from __future__ import annotations

from typing import Any

# V4.0 removes product-specific templates from application code.
# Product classification now comes from connected marketplace taxonomy providers.
CATALOG: list[dict[str, Any]] = []


def search_catalog(query: str, limit: int = 5) -> list[dict[str, Any]]:
    return []


def identify_product(text: str) -> dict[str, Any]:
    clean = " ".join(str(text or "").strip().split())
    return {
        "input": text,
        "identified": bool(clean),
        "confidence": "unclassified",
        "product_type": {
            "id": "generic",
            "name": clean or "Unclassified product",
            "category_path": [],
            "hs_candidates": [],
            "attributes": [],
        },
        "extracted_attributes": {},
        "suggested_title": clean[:180],
        "matches": [],
        "message": "No built-in product taxonomy is used. Attach a marketplace category or confirm classification in Project Setup.",
    }


def catalog_summary() -> list[dict[str, Any]]:
    return []
