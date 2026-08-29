from __future__ import annotations

from dataclasses import asdict

from .amazon_provider import AmazonProvider
from .csv_provider import CsvProvider
from .ebay_provider import EbayProvider

PROVIDERS = {
    "ebay": EbayProvider(),
    "csv": CsvProvider(),
    "amazon": AmazonProvider(),
}


def provider_statuses():
    return [asdict(provider.status()) for provider in PROVIDERS.values()]
