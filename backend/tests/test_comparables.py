from app.comparables import build_comparable_set


def test_generic_comparable_filter_has_no_product_specific_rules():
    rows = [
        {"item_id": "1", "title": "Alpha Device Model A", "price": 39.99, "condition": "NEW"},
        {"item_id": "2", "title": "Alpha Device Model B", "price": 49.99, "condition": "NEW"},
        {"item_id": "3", "title": "Alpha Device Model C", "price": 29.99, "condition": "USED"},
    ]
    result = build_comparable_set(rows, query="Alpha Device", target_price=40)
    assert result["accepted_count"] == 2
    assert result["rejected_count"] == 1
    assert result["summary"]["median"] == 44.99
    assert "product" not in result["filter_method"].lower()
    assert result["rejection_reasons"]["non-new condition"] == 1


def test_category_and_user_exclusion_are_dynamic():
    rows = [
        {"item_id":"1","title":"Model Pro 128GB","price":100,"condition":"NEW","category_id":"10"},
        {"item_id":"2","title":"Model Pro case","price":10,"condition":"NEW","category_id":"10"},
        {"item_id":"3","title":"Model Pro 256GB","price":120,"condition":"NEW","category_id":"99"},
    ]
    result=build_comparable_set(rows,query="Model Pro",expected_category_id="10",excluded_terms=["case"])
    assert result["accepted_count"]==1
    assert result["rejection_reasons"]["user-excluded term"]==1
    assert result["rejection_reasons"]["category mismatch"]==1
