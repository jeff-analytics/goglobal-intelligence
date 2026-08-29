from app.sources.official_tariff import _numeric_rate
from app.storage import save_market_scan, get_market_scan, delete_market_scan


def test_official_tariff_numeric_rate_parser():
    assert _numeric_rate('Free') == 0.0
    assert _numeric_rate('3.5%') == 3.5
    assert _numeric_rate('2.1 cents/kg') is None


def test_market_scan_cache_roundtrip():
    payload = {
        'hs_code': '850811',
        'origin': {'code': '156', 'name': 'China'},
        'markets': [{'market': 'US', 'imports': 123.0}],
        'source': 'UN Comtrade',
    }
    saved = save_market_scan(987654321, payload)
    assert saved['project_id'] == 987654321
    loaded = get_market_scan(987654321)
    assert loaded is not None
    assert loaded['markets'][0]['market'] == 'US'
    assert delete_market_scan(987654321) is True
