from __future__ import annotations

from typing import Any

from .base import ProviderStatus


class AmazonProvider:
    key = "amazon"
    name = "Amazon SP-API"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            key=self.key,
            name=self.name,
            configured=False,
            environment="not-configured",
            supports_taxonomy=True,
            supports_search=True,
            supports_market_benchmark=True,
            note="Provider interface is reserved. SP-API requires a selling-partner application and authorization before live use.",
        )

    def search(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Amazon SP-API is not configured in this build")
