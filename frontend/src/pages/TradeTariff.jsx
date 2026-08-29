import React, { useEffect, useMemo, useState } from 'react'
import { Download, ExternalLink, RefreshCw, Save, Search, Trash2 } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, downloadCsv } from '../api'
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, PageHeader } from '../components/Common'
import { FLAGS, compactMoney, currentAnalysisYears, pct, snapshotRow, marketName, localizeRuntimeMessage, aiRecoveredField } from '../utils'
import { useI18n } from '../i18n.jsx'
import { AiRecoveryAction } from '../components/AiRecovery'

function TooltipBox({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return <div className="chart-tooltip"><b>{label}</b>{payload.map((p,i)=><div key={i}><span>{p.name}</span><strong>{compactMoney(p.value,'USD')}</strong></div>)}</div>
}

export default function TradeTariff({ dashboard, markets, onReload, onGoSetup }) {
  const { t, locale } = useI18n()
  const project = dashboard?.project
  const snapshots = dashboard?.snapshots || []
  const [selectedMarket, setSelectedMarket] = useState(project?.markets?.[0] || '')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [official, setOfficial] = useState(null)
  const [officialLoading, setOfficialLoading] = useState(false)
  const [override, setOverride] = useState(null)
  const [manualRate, setManualRate] = useState('')
  const [manualYear, setManualYear] = useState('')
  const [manualNote, setManualNote] = useState('')
  const [tariffSaving, setTariffSaving] = useState(false)
  const [taxState,setTaxState]=useState({override:null,source:'',official_url:''})
  const [taxRate,setTaxRate]=useState('')
  const [taxYear,setTaxYear]=useState('')
  const [taxNote,setTaxNote]=useState('')
  const [taxSaving,setTaxSaving]=useState(false)
  const [aiEvidence,setAiEvidence]=useState([])
  const years = currentAnalysisYears()
  const marketMap = useMemo(()=>Object.fromEntries(markets.map(m=>[m.code,m])),[markets])
  useEffect(()=>setSelectedMarket(project?.markets?.[0] || ''),[project?.id])
  useEffect(()=>{ if(selectedMarket && project?.hs_code) {loadTariffState();loadTaxState();loadAiEvidence()} },[selectedMarket, project?.id, project?.hs_code])
  const rows = (project?.markets || []).map(code => snapshotRow(code, marketMap[code], snapshots.find(s=>s.market===code)))
  const snap = snapshots.find(s=>s.market===selectedMarket) || null
  const history = (snap?.trade?.history || []).map(r=>({ year:r.year, imports:r.total_imports, origin:r.imports_from_origin }))
  const suppliers=snap?.suppliers?.suppliers||[]
  const tariff=snap?.tariff||null
  const aiTariff=aiRecoveredField(snap,'tariff.rate') || aiRecoveredField(snap,'tariff.local_code')
  const aiTax=aiRecoveredField(snap,'tax.rate')

  if (!project) return <PageHeader title={t('tradeSuppliers')} />
  if (!project.hs_code) return <Card><Empty title={locale==='zh'?'需要 HS 编码':'HS code required'} action={<Button variant="primary" onClick={onGoSetup}>{locale==='zh'?'打开项目设置':'Open Project Setup'}</Button>} /></Card>


  async function loadTariffState(){
    try{
      const r=await api(`/api/data/tariff/override?market=${encodeURIComponent(selectedMarket)}&hs=${encodeURIComponent(project.hs_code.slice(0,6))}`)
      const o=r.override||null
      setOverride(o)
      setManualRate(o?.rate ?? '')
      setManualYear(o?.reference_year ?? '')
      setManualNote(o?.note ?? '')
    }catch{}
  }

  async function loadTaxState(){
    try{const r=await api(`/api/data/tax/override?market=${encodeURIComponent(selectedMarket)}`);const o=r.override||null;setTaxState(r);setTaxRate(o?.rate??'');setTaxYear(o?.reference_year??'');setTaxNote(o?.note??'')}catch{}
  }
  async function saveManualTax(){
    if(taxRate===''||Number(taxRate)<0)return;setTaxSaving(true);setError('');try{const r=await api('/api/data/tax/override',{method:'POST',body:JSON.stringify({market:selectedMarket,rate:Number(taxRate),reference_year:taxYear===''?null:Number(taxYear),note:taxNote||null})});setTaxState({...taxState,override:r.override});await onReload(project.id)}catch(e){setError(e.message)}finally{setTaxSaving(false)}
  }
  async function clearManualTax(){setTaxSaving(true);setError('');try{await api(`/api/data/tax/override?market=${encodeURIComponent(selectedMarket)}`,{method:'DELETE'});setTaxState({...taxState,override:null});setTaxRate('');setTaxYear('');setTaxNote('');await onReload(project.id)}catch(e){setError(e.message)}finally{setTaxSaving(false)}}

  async function lookupOfficial(){
    setOfficialLoading(true); setError('')
    try{ setOfficial(await api(`/api/data/tariff/official?market=${encodeURIComponent(selectedMarket)}&code=${encodeURIComponent(project.hs_code)}&origin=${encodeURIComponent(project.origin||'')}`)) }
    catch(e){ setError(e.message) }
    finally{ setOfficialLoading(false) }
  }

  async function saveManualTariff(){
    if(manualRate==='' || Number(manualRate)<0) return
    setTariffSaving(true); setError('')
    try{
      const r=await api('/api/data/tariff/override',{method:'POST',body:JSON.stringify({market:selectedMarket,hs_code:project.hs_code.slice(0,6),rate:Number(manualRate),reference_year:manualYear===''?null:Number(manualYear),note:manualNote||null})})
      setOverride(r.override||null)
      await refreshAll()
    }catch(e){setError(e.message)}
    finally{setTariffSaving(false)}
  }

  async function clearManualTariff(){
    setTariffSaving(true); setError('')
    try{
      await api(`/api/data/tariff/override?market=${encodeURIComponent(selectedMarket)}&hs=${encodeURIComponent(project.hs_code.slice(0,6))}`,{method:'DELETE'})
      setOverride(null); setManualRate(''); setManualYear(''); setManualNote('')
      await refreshAll()
    }catch(e){setError(e.message)}
    finally{setTariffSaving(false)}
  }

  async function loadAiEvidence(){
    if(!project?.id||!selectedMarket)return
    try{const r=await api(`/api/projects/${project.id}/ai/evidence?market=${encodeURIComponent(selectedMarket)}`);setAiEvidence(r.records||[])}catch{}
  }

  async function refreshAll() {
    setRunning(true); setError('')
    try { await api(`/api/projects/${project.id}/run-analysis?start_year=${years.start}&end_year=${years.end}`, { method:'POST' }); await onReload(project.id) }
    catch(e){ setError(e.message) }
    finally{ setRunning(false) }
  }

  const exportRows = rows.map(r=>({ market:r.market, label:r.label, latest_year:r.latest_year, imports:r.imports, origin_imports:r.origin_imports, origin_share:r.origin_share, trend:r.trend, volatility:r.volatility, supplier_cr3:r.supplier_cr3, supplier_cr5:r.supplier_cr5, supplier_hhi:r.supplier_hhi, tariff_rate:r.tariff_rate, coverage:r.coverage, synced_at:r.synced_at }))

  return <div className="page-stack">
    <PageHeader title={t('tradeSuppliers')} actions={<><Button icon={Download} variant="secondary" disabled={!rows.length} onClick={()=>downloadCsv(`bordermargin-trade-${project.id}.csv`, exportRows)}>CSV</Button><AiRecoveryAction project={project} scope="trade" markets={selectedMarket?[selectedMarket]:[]} onComplete={async()=>{await onReload(project.id);await loadAiEvidence()}} label={locale==='zh'?'AI 补全当前市场':'AI recover current market'}/><Button icon={RefreshCw} variant="primary" loading={running} disabled={!project.markets?.length} onClick={refreshAll}>{locale==='zh'?'刷新市场':'Refresh markets'}</Button></>} />
    <ErrorBanner error={error}/>
    <Card><CardHeader title={locale==='zh'?'市场观测':'Market observations'} meta={`${snapshots.length}/${project.markets.length} ${locale==='zh'?'个市场已同步':'market(s) synced'}`} />
      <div className="data-table trade-table v4"><div className="tr th"><span>{locale==='zh'?'市场':'Market'}</span><span>{locale==='zh'?'年份':'Year'}</span><span>{locale==='zh'?'进口额':'Imports'}</span><span>{locale==='zh'?'原产地份额':'Origin share'}</span><span>{locale==='zh'?'趋势':'Trend'}</span><span>CR3</span><span>{locale==='zh'?'关税':'Tariff'}</span><span>{locale==='zh'?'覆盖率':'Coverage'}</span></div>
        {rows.map(r=>{const af=r.ai_fields||[];const aiTrade=af.includes('trade.history')||af.includes('trade.latest_total_imports');const aiShare=af.includes('trade.history')||af.includes('trade.latest_origin_share');const aiCr3=af.includes('supply.cr3')||af.includes('supply.top_suppliers');const aiDuty=af.includes('tariff.rate');return <button className="tr clickable" key={r.market} onClick={()=>setSelectedMarket(r.market)}><b>{FLAGS[r.market] || '🌐'} {marketName(markets,r.market,locale,r.label)}</b><span>{r.latest_year || '—'}</span><strong className={aiTrade?'ai-filled-inline':''}>{compactMoney(r.imports,'USD')}</strong><span className={aiShare?'ai-filled-inline':''}>{pct(r.origin_share)}</span><span className={r.trend>0?'positive':r.trend<0?'negative':''}>{pct(r.trend)}</span><span className={aiCr3?'ai-filled-inline':''}>{pct(r.supplier_cr3)}</span><span className={aiDuty?'ai-filled-inline':''}>{r.tariff_rate!=null ? pct(r.tariff_rate) : locale==='zh'?'不可用':'Unavailable'}</span><span><Badge tone={r.coverage===1?'success':r.coverage>0?'warning':'neutral'}>{r.coverage!=null ? pct(r.coverage,0) : locale==='zh'?'无数据':'No data'}</Badge></span></button>})}
      </div>
    </Card>

    <div className="two-col">
      <Card><CardHeader title={locale==='zh'?'进口历史':'Import history'} meta={snap ? `${FLAGS[snap.market] || ''} ${marketName(markets,snap.market,locale,snap.market_label)}` : (locale==='zh'?'暂无数据快照':'No snapshot')} />{history.length ? <div className="chart-wrap"><ResponsiveContainer width="100%" height={300}><BarChart data={history}><CartesianGrid stroke="#d9e1e8" vertical={false}/><XAxis dataKey="year" stroke="#64748b" tickLine={false}/><YAxis stroke="#64748b" tickLine={false} tickFormatter={v=>v>=1e9?`${(v/1e9).toFixed(0)}B`:v>=1e6?`${(v/1e6).toFixed(0)}M`:v}/><Tooltip content={<TooltipBox/>}/><Bar dataKey="imports" name={locale==='zh'?'进口总额':'Total imports'} fill="#5f86ad" radius={[4,4,0,0]}/><Bar dataKey="origin" name={snap?.origin?.name ? (locale==='zh'?`来自 ${snap.origin.name} 的进口额`:`Imports from ${snap.origin.name}`) : locale==='zh'?'原产地进口额':'Imports from origin'} fill="#5d9270" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer></div> : <Empty title={locale==='zh'?'暂无历史数据':'No history available'} />}</Card>
      <Card><CardHeader title={locale==='zh'?'来源国结构':'Origin-country structure'} meta={snap?.suppliers?.year ? `UN Comtrade ${snap.suppliers.year}` : '—'} />{suppliers.length?<><div className="supplier-summary"><div><span>{locale==='zh'?'来源国数量':'Origin countries'}</span><b>{snap.suppliers.supplier_count}</b></div><div><span>CR3</span><b>{pct(snap.suppliers.cr3)}</b></div><div><span>CR5</span><b>{pct(snap.suppliers.cr5)}</b></div><div><span>HHI</span><b>{snap.suppliers.hhi!=null?Number(snap.suppliers.hhi).toFixed(3):'—'}</b></div></div><div className="supplier-list">{suppliers.map((x,i)=><div key={x.partner_code}><span>{i+1}</span><b>{x.partner_name}</b><strong>{compactMoney(x.trade_value,'USD')}</strong><em>{pct(x.share)}</em></div>)}</div></>:<Empty title={locale==='zh'?'无数据':'No data'}/>}</Card>
    </div>

    <Card><CardHeader title={locale==='zh'?'关税':'Tariff'} meta={`${FLAGS[selectedMarket] || ''} ${locale==='zh'?(marketMap[selectedMarket]?.label_zh||marketMap[selectedMarket]?.label||selectedMarket):(marketMap[selectedMarket]?.label||selectedMarket)}`} actions={<Button icon={Search} loading={officialLoading} disabled={!selectedMarket} onClick={lookupOfficial}>{locale==='zh'?'查询官方来源':'Check official source'}</Button>} />
      <div className="tariff-options">
        <div className={`tariff-option ${aiTariff?'ai-filled':''}`}>
          <span>{locale==='zh'?'已连接税率':'Connected rate'}</span>
          <strong>{tariff?.rate!=null ? `${Number(tariff.rate).toFixed(2)}%` : locale==='zh'?'不可用':'Unavailable'}</strong>
          <small>{tariff?.source || '—'}</small>
          {tariff?.year && <em>{locale==='zh'?'参考年份':'Reference year'} {tariff.year}</em>}
          {(snap?.tariff_official_lookup?.local_code||tariff?.nomenclature) && <em>{locale==='zh'?'当地税则编码':'Local tariff code'} {snap?.tariff_official_lookup?.local_code||tariff?.nomenclature}</em>}
        </div>
        <div className="tariff-option">
          <span>{locale==='zh'?'当前官方查询':'Official current lookup'}</span>
          <strong>{official?.rate!=null ? `${Number(official.rate).toFixed(2)}%` : official?.status ? official.status.replaceAll('_',' ') : locale==='zh'?'尚未查询':'Not checked'}</strong>
          <small>{official?.source || '—'}</small>
          {official?.candidates?.length>0 && <em>{locale==='zh'?`返回 ${official.candidates.length} 条候选税则行`:`${official.candidates.length} candidate tariff line(s) returned`}</em>}
          {official?.local_code_requirement && <em>{locale==='zh'?`需要 ${official.local_code_requirement} 位当地税则编码`:`Local code: ${official.local_code_requirement} digits / level required`}</em>}
          {official?.lookup_url && <a href={official.lookup_url} target="_blank" rel="noreferrer"><ExternalLink size={13}/> {locale==='zh'?'打开官方来源':'Open official source'}</a>}
        </div>
        <div className="tariff-manual">
          <div className="tariff-manual-head"><span>{locale==='zh'?'人工确认税率':'Verified manual rate'}</span>{override&&<Badge tone="warning">{locale==='zh'?'人工覆盖已启用':'Override active'}</Badge>}</div>
          <div className="tariff-fields"><label><small>{locale==='zh'?'税率 %':'Rate %'}</small><input type="number" min="0" max="100" value={manualRate} onChange={e=>setManualRate(e.target.value)}/></label><label><small>{locale==='zh'?'参考年份':'Reference year'}</small><input type="number" value={manualYear} onChange={e=>setManualYear(e.target.value)}/></label></div>
          <label className="tariff-note"><small>{locale==='zh'?'来源 / 备注':'Source / note'}</small><input value={manualNote} onChange={e=>setManualNote(e.target.value)}/></label>
          <div className="tariff-actions"><Button icon={Save} variant="primary" loading={tariffSaving} disabled={manualRate===''} onClick={saveManualTariff}>{locale==='zh'?'保存确认税率':'Save verified rate'}</Button>{override&&<Button icon={Trash2} variant="secondary" loading={tariffSaving} onClick={clearManualTariff}>{locale==='zh'?'移除人工覆盖':'Remove override'}</Button>}</div>
        </div>
      </div>
    </Card>

    <Card><CardHeader title={locale==='zh'?'进口税 / VAT / GST':'Import tax / VAT / GST'} meta={`${FLAGS[selectedMarket] || ''} ${locale==='zh'?(marketMap[selectedMarket]?.label_zh||marketMap[selectedMarket]?.label||selectedMarket):(marketMap[selectedMarket]?.label||selectedMarket)}`} />
      <div className="tariff-options tax-options">
        <div className={`tariff-option ${aiTax?'ai-filled':''}`}><span>{locale==='zh'?'当前税率':'Current rate'}</span><strong>{snap?.tax?.rate!=null?`${Number(snap.tax.rate).toFixed(2)}%`:'—'}</strong><small>{snap?.tax?.source||'—'}</small>{(snap?.tax?.reference_year||snap?.tax?.observed_at)&&<em>{locale==='zh'?'参考时间':'Reference'} {snap.tax.reference_year||snap.tax.observed_at}</em>}</div>
        <div className="tariff-option"><span>{locale==='zh'?'官方税务来源':'Official tax source'}</span><strong>{taxState?.source || (locale==='zh'?'来源登记':'Source registry')}</strong>{taxState?.official_url&&<a href={taxState.official_url} target="_blank" rel="noreferrer"><ExternalLink size={13}/> {locale==='zh'?'打开官方税务来源':'Open official tax source'}</a>}</div>
        <div className="tariff-manual"><div className="tariff-manual-head"><span>{locale==='zh'?'人工确认税率':'Verified tax rate'}</span>{taxState?.override&&<Badge tone="warning">{locale==='zh'?'人工覆盖已启用':'Override active'}</Badge>}</div><div className="tariff-fields"><label><small>{locale==='zh'?'税率 %':'Rate %'}</small><input type="number" min="0" max="100" value={taxRate} onChange={e=>setTaxRate(e.target.value)}/></label><label><small>{locale==='zh'?'参考年份':'Reference year'}</small><input type="number" value={taxYear} onChange={e=>setTaxYear(e.target.value)}/></label></div><label className="tariff-note"><small>{locale==='zh'?'来源 / 备注':'Source / note'}</small><input value={taxNote} onChange={e=>setTaxNote(e.target.value)}/></label><div className="tariff-actions"><Button icon={Save} variant="primary" loading={taxSaving} disabled={taxRate===''} onClick={saveManualTax}>{locale==='zh'?'保存确认税率':'Save verified tax'}</Button>{taxState?.override&&<Button icon={Trash2} variant="secondary" loading={taxSaving} onClick={clearManualTax}>{locale==='zh'?'移除人工覆盖':'Remove override'}</Button>}</div></div>
      </div>
    </Card>

    {aiEvidence.length>0&&<Card><CardHeader title={locale==='zh'?'AI 证据':'AI evidence'} meta={`${aiEvidence.length}`} />
      <div className="data-table ai-evidence-table"><div className="tr th"><span>{locale==='zh'?'字段':'Field'}</span><span>{locale==='zh'?'值':'Value'}</span><span>{locale==='zh'?'来源':'Source'}</span><span>{locale==='zh'?'等级':'Level'}</span><span>{locale==='zh'?'置信度':'Confidence'}</span><span>{locale==='zh'?'时间':'Updated'}</span></div>
        {aiEvidence.slice(0,24).map(r=><div className="tr" key={`${r.id}-${r.field_name}`}><b>{r.field_name}</b><span>{typeof r.value==='object'?JSON.stringify(r.value):String(r.value??'—')}</span><span>{r.source_url?<a href={r.source_url} target="_blank" rel="noreferrer">{r.source_name||(locale==='zh'?'来源':'Source')}</a>:(r.source_name||'—')}</span><span><Badge tone={r.evidence_level==='B'?'success':r.evidence_level==='C'?'warning':'neutral'}>{r.evidence_level||'—'}</Badge></span><span>{r.confidence||'—'}</span><span>{r.retrieved_at?new Date(r.retrieved_at).toLocaleString():'—'}</span></div>)}
      </div>
    </Card>}

    <Card><CardHeader title={locale==='zh'?'数据质量':'Source quality'} /><div className="detail-grid quality-detail">{snap ? <><div><span>{locale==='zh'?'请求区间':'Requested period'}</span><b>{snap.start_year}–{snap.end_year}</b></div><div><span>{locale==='zh'?'最新观测':'Latest observation'}</span><b>{snap.trade?.latest_year || '—'}</b></div><div><span>{locale==='zh'?'贸易覆盖率':'Trade coverage'}</span><b>{pct(snap.quality?.world?.coverage_ratio,0)}</b></div><div><span>{locale==='zh'?'原产地数据覆盖率':'Origin coverage'}</span><b>{pct(snap.quality?.origin?.coverage_ratio,0)}</b></div><div><span>{locale==='zh'?'关税来源':'Tariff source'}</span><b>{snap.tariff?.source || (locale==='zh'?'不可用':'Unavailable')}</b></div><div><span>{locale==='zh'?'最近同步':'Last sync'}</span><b>{snap.synced_at ? new Date(snap.synced_at).toLocaleString() : '—'}</b></div></>:<Empty title={locale==='zh'?'暂无来源详情':'No source detail'}/>}</div></Card>
  </div>
}
