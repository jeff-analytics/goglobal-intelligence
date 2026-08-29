from app.sources import ebay


def test_top_categories_compacts_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(ebay, "_TAXONOMY_CACHE_DIR", tmp_path)

    def fake_request(path, **kwargs):
        if path == "/get_default_category_tree_id":
            return {"categoryTreeId": "0", "categoryTreeVersion": "1"}
        if path == "/category_tree/0":
            return {
                "categoryTreeId": "0",
                "categoryTreeVersion": "1",
                "rootCategoryNode": {
                    "category": {"categoryId": "0", "categoryName": "Root"},
                    "childCategoryTreeNodes": [
                        {
                            "category": {"categoryId": "2", "categoryName": "Electronics"},
                            "categoryTreeNodeLevel": 1,
                            "childCategoryTreeNodes": [
                                {"category": {"categoryId": "3", "categoryName": "Phones"}, "leafCategoryTreeNode": True}
                            ],
                        },
                        {"category": {"categoryId": "1", "categoryName": "Art"}, "categoryTreeNodeLevel": 1, "leafCategoryTreeNode": True},
                    ],
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(ebay, "_taxonomy_request", fake_request)
    result = ebay.get_top_categories("EBAY_US")
    assert result["count"] == 2
    assert [x["name"] for x in result["categories"]] == ["Art", "Electronics"]
    assert result["categories"][1]["child_count"] == 1


def test_category_suggestions_include_path(monkeypatch):
    def fake_request(path, **kwargs):
        if path == "/get_default_category_tree_id":
            return {"categoryTreeId": "0", "categoryTreeVersion": "1"}
        if path.endswith("get_category_suggestions"):
            return {
                "categorySuggestions": [
                    {
                        "category": {"categoryId": "9355", "categoryName": "Cell Phones & Smartphones"},
                        "categoryTreeNodeLevel": 2,
                        "categoryTreeNodeAncestors": [
                            {"categoryId": "15032", "categoryName": "Cell Phones & Accessories", "categoryTreeNodeLevel": 1}
                        ],
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(ebay, "_taxonomy_request", fake_request)
    result = ebay.get_category_suggestions("EBAY_US", "iphone")
    assert result["suggestions"][0]["path"] == ["Cell Phones & Accessories", "Cell Phones & Smartphones"]


def test_category_children_use_cached_full_tree_without_subtree_api(monkeypatch, tmp_path):
    monkeypatch.setattr(ebay, "_TAXONOMY_CACHE_DIR", tmp_path)
    ebay._TAXONOMY_META_CACHE.clear()
    ebay._TAXONOMY_TREE_MEMORY.clear()
    ebay._TAXONOMY_INDEX_MEMORY.clear()

    calls = []
    def fake_request(path, **kwargs):
        calls.append(path)
        if path == "/get_default_category_tree_id":
            return {"categoryTreeId": "0", "categoryTreeVersion": "1"}
        if path == "/category_tree/0":
            return {
                "categoryTreeId": "0",
                "categoryTreeVersion": "1",
                "rootCategoryNode": {
                    "category": {"categoryId": "-1", "categoryName": "Root"},
                    "childCategoryTreeNodes": [
                        {
                            "category": {"categoryId": "2", "categoryName": "Electronics"},
                            "categoryTreeNodeLevel": 1,
                            "childCategoryTreeNodes": [
                                {"category": {"categoryId": "3", "categoryName": "Phones"}, "leafCategoryTreeNode": True}
                            ],
                        }
                    ],
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(ebay, "_taxonomy_request", fake_request)
    ebay.get_top_categories("EBAY_US")
    result = ebay.get_category_children("EBAY_US", "2")
    assert result["cache"] == "local_tree"
    assert result["children"][0]["name"] == "Phones"
    assert not any("get_category_subtree" in path for path in calls)


def test_cached_tree_skips_metadata_network_call(monkeypatch, tmp_path):
    monkeypatch.setattr(ebay, "_TAXONOMY_CACHE_DIR", tmp_path)
    ebay._TAXONOMY_META_CACHE.clear()
    ebay._TAXONOMY_TREE_MEMORY.clear()
    ebay._TAXONOMY_INDEX_MEMORY.clear()

    cached = {
        "categoryTreeId": "77",
        "categoryTreeVersion": "9",
        "rootCategoryNode": {"category": {"categoryId": "-1", "categoryName": "Root"}, "childCategoryTreeNodes": []},
    }
    (tmp_path / "EBAY_CA_77.json").write_text(__import__('json').dumps(cached), encoding="utf-8")

    def fail_request(path, **kwargs):
        raise AssertionError(f"network should not be used: {path}")

    monkeypatch.setattr(ebay, "_taxonomy_request", fail_request)
    result = ebay.get_top_categories("EBAY_CA")
    assert result["category_tree_id"] == "77"
    assert result["cache"] == "local"


def test_cached_top_categories_can_miss_without_network(monkeypatch, tmp_path):
    # A cache-only page-entry check must never require eBay credentials/network.
    monkeypatch.setattr(ebay, '_TAXONOMY_CACHE_DIR', tmp_path)
    ebay._TAXONOMY_TREE_MEMORY.clear()
    result = ebay.get_top_categories_cached('EBAY_TEST')
    assert result['cached'] is False
    assert result['categories'] == []
