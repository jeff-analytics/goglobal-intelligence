from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderStatus:
    key: str
    name: str
    configured: bool
    environment: str
    supports_taxonomy: bool
    supports_search: bool
    supports_market_benchmark: bool
    note: str


class MarketplaceProvider(Protocol):
    key: str
    name: str

    def status(self) -> ProviderStatus: ...
    def search(self, **kwargs: Any) -> dict[str, Any]: ...
