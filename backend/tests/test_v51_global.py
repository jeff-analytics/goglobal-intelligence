from app.markets import market_list, MARKETS
from app.market_support import support_registry


def test_global_market_universe_and_core_compatibility():
    rows = market_list()
    assert len(rows) >= 240
    assert MARKETS['US']['reporter'] == '842'
    assert MARKETS['UK']['ebay'] == 'EBAY_GB'
    assert MARKETS['UK']['featured'] is True
    assert all(row.get('label') for row in rows)
    assert all('region' in row for row in rows)


def test_global_support_registry_is_explicit_about_missing_connectors():
    rows = support_registry()
    assert len(rows) == len(market_list())
    assert all(row.get('tariff_provider') for row in rows)
    assert all(row.get('tax_provider') for row in rows)
