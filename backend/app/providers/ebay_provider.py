from __future__ import annotations

from typing import Any

from .base import ProviderStatus
from ..config import settings
from ..sources.ebay import search_listings


class EbayProvider:
    key = "ebay"
    name = "eBay"

    def status(self) -> ProviderStatus:
        configured = bool(settings.ebay_client_id and settings.ebay_client_secret)
        return ProviderStatus(
            key=self.key,
            name=self.name,
            configured=configured,
            environment=settings.ebay_env,
            supports_taxonomy=True,
            supports_search=configured,
            supports_market_benchmark=configured and settings.ebay_env == "production",
            note=(
                "Sandbox taxonomy/search is available for integration testing; listing prices are blocked from market benchmarks."
                if settings.ebay_env == "sandbox"
                else "Production Browse results may feed benchmarks after comparable filtering."
            ),
        )

    def search(self, **kwargs: Any) -> dict[str, Any]:
        return search_listings(
            query=str(kwargs.get("query") or ""),
            marketplace_id=str(kwargs.get("marketplace_id") or "EBAY_US"),
            limit=int(kwargs.get("limit") or 50),
            category_id=kwargs.get("category_id"),
            sort=kwargs.get("sort"),
            offset=int(kwargs.get("offset") or 0),
        )
