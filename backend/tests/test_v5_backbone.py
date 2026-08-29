from app.market_support import support_registry, contract_from_snapshot
from app.ai_layer import ai_status


def test_support_registry_covers_all_configured_markets():
    rows = support_registry()
    codes = {r['market'] for r in rows}
    assert {'US','UK','DE','FR','IT','ES','NL','CA','AU','JP','KR','SG'} <= codes
    assert all(r.get('tariff_provider') for r in rows)
    assert all(r.get('tax_provider') for r in rows)


def test_contract_marks_missing_evidence_instead_of_filling_values():
    c = contract_from_snapshot(None, 'CA')
    assert c['trade']['imports'] is None
    assert c['tariff']['rate'] is None
    assert c['tax']['rate'] is None
    assert c['quality']['support_tier'] == 'limited'


def test_contract_normalizes_snapshot():
    snap = {
        'market':'US','synced_at':'2026-08-27T00:00:00+00:00',
        'trade':{'latest_year':2024,'latest_total_imports':100.0,'latest_imports_from_origin':25.0,'latest_origin_share':0.25,'world_metrics':{'yoy':0.1,'cagr':0.05},'history':[]},
        'suppliers':{'supplier_count':4,'cr3':0.8,'cr5':0.9,'hhi':0.3,'suppliers':[]},
        'tariff':{'rate':3.5,'source':'test','year':2026},
        'tariff_official_lookup':{'source':'USITC HTS','status':'resolved','lookup_url':'https://hts.usitc.gov/','local_code':'8504409580'},
        'tax':{'rate':0.0,'source':'State/local sales tax varies'},
        'fx':{'rate':1.0,'source':'ECB'},
        'quality':{'world':{'coverage_ratio':1.0},'origin':{'coverage_ratio':1.0}},
    }
    c=contract_from_snapshot(snap,'US')
    assert c['trade']['imports']==100.0
    assert c['supply']['cr3']==0.8
    assert c['tariff']['rate']==3.5
    assert c['quality']['completeness_ratio']==1.0


def test_ai_layer_exposes_evidence_recovery_mode():
    s=ai_status()
    assert s['mode']=='evidence-recovery'
    assert 'configured' in s
    if s['configured']:
        assert s['model']
    else:
        assert s['model'] == ''
