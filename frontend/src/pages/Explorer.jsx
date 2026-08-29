import React, { useEffect, useMemo, useState } from 'react'
import { BarChart3, Check, Play, RefreshCw, Save } from 'lucide-react'
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, PageHeader } from '../components/Common'
import { AiRecoveryAction } from '../components/AiRecovery'
import { FLAGS, compactMoney, pct, marketName } from '../utils'
import { useI18n } from '../i18n.jsx'

const METRICS = {
  imports: { label:'Import value', zh:'进口额', kind:'money' },
  cagr: { label:'3Y CAGR', zh:'3年复合增长率', kind:'pct' },
  yoy: { label:'YoY growth', zh:'同比增长', kind:'pct' },
  origin_share: { label:'Origin share', zh:'原产地份额', kind:'pct' },
  origin_exports: { label:'Origin exports', zh:'原产地出口额', kind:'money' },
  origin_export_cagr: { label:'Origin export CAGR', zh:'原产地出口复合增长率', kind:'pct' },
  corridor_exports: { label:'Exports to target market', zh:'对目标市场出口额', kind:'money' },
  corridor_share: { label:'Target share of origin exports', zh:'目标市场占原产地出口', kind:'pct' },
  coverage: { label:'Trade coverage', zh:'贸易覆盖率', kind:'pct' },
  cr3: { label:'Origin-country CR3', zh:'来源国集中度 CR3', kind:'pct' },
  hhi: { label:'Origin-country HHI', zh:'来源国 HHI', kind:'number' },
  tariff: { label:'Tariff', zh:'关税', kind:'pct' },
  evidence_ratio: { label:'Evidence completeness', zh:'证据完整度', kind:'pct' },
}

function formatMetric(key, value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const spec = METRICS[key]
  if (spec?.kind === 'money') return compactMoney(value, 'USD')
  if (spec?.kind === 'pct') return pct(value)
  return Number(value).toFixed(3)
}

function AxisSelect({ label, value, onChange, locale }) {
  return <label className="axis-select"><span>{label}</span><select value={value} onChange={e=>onChange(e.target.value)}>{Object.entries(METRICS).map(([k,v])=><option key={k} value={k}>{locale==='zh'?(v.zh||v.label):v.label}</option>)}</select></label>
}

function ExplorerTooltip({ active, payload, xKey, yKey, locale }) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload
  if (!row) return null
  return <div className="chart-tooltip explorer-tooltip"><b>{FLAGS[row.market] || ''} {row.label}</b><div><span>{locale==='zh'?(METRICS[xKey].zh||METRICS[xKey].label):METRICS[xKey].label}</span><strong>{formatMetric(xKey,row[xKey])}</strong></div><div><span>{locale==='zh'?(METRICS[yKey].zh||METRICS[yKey].label):METRICS[yKey].label}</span><strong>{formatMetric(yKey,row[yKey])}</strong></div><div><span>{locale==='zh'?'证据完整度':'Evidence'}</span><strong>{formatMetric('evidence_ratio',row.evidence_ratio)}</strong></div>{row.pareto_frontier&&<Badge tone="success">{locale==='zh'?'帕累托前沿':'Pareto frontier'}</Badge>}</div>
}

function standoutLabel(type,locale){
  const en={largest_import_market:'Largest observed market',fastest_3y_growth:'Fastest 3Y growth',highest_origin_share:'Highest origin presence',best_coverage:'Best trade coverage',most_diversified_supply:'Most diversified supply'}
  const zh={largest_import_market:'最大进口市场',fastest_3y_growth:'3年增长最快',highest_origin_share:'原产地份额最高',best_coverage:'贸易数据覆盖最好',most_diversified_supply:'供应结构最分散'}
  return (locale==='zh'?zh:en)[type] || type
}

function quadrantLabel(value,locale){
  const en={HIGH_SCALE_HIGH_GROWTH:'High scale · high growth',HIGH_SCALE_LOWER_GROWTH:'High scale · lower growth',SMALLER_HIGH_GROWTH:'Smaller · high growth',SMALLER_LOWER_GROWTH:'Smaller · lower growth'}
  const zh={HIGH_SCALE_HIGH_GROWTH:'高规模 · 高增长',HIGH_SCALE_LOWER_GROWTH:'高规模 · 较低增长',SMALLER_HIGH_GROWTH:'较小规模 · 高增长',SMALLER_LOWER_GROWTH:'较小规模 · 较低增长'}
  return (locale==='zh'?zh:en)[value] || (locale==='zh'?'未分类':'Not classified')
}


function evidenceLabel(key, locale){
  if(locale!=='zh') return String(key||'').replaceAll('_',' ')
  const map={trade:'贸易数据',origin_trade:'原产地贸易',supplier_structure:'来源国结构',tariff:'关税',fx:'汇率',pricing_or_cost:'价格或成本',pricing:'价格基准',cost:'成本数据',tax:'税务'}
  return map[key] || String(key||'').replaceAll('_',' ')
}
function decisionLabel(status, locale){
  if(locale!=='zh') return String(status||'Pending detailed sync').replaceAll('_',' ')
  return ({READY_FOR_DECISION:'可进入决策',CONDITIONAL:'有条件',INSUFFICIENT_EVIDENCE:'证据不足'}[status] || '待详细同步')
}
export default function Explorer({ dashboard, markets, onReload, onGoScan, onGoTrade }) {
  const { t, locale } = useI18n()
  const project = dashboard?.project
  const [data,setData]=useState(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [xKey,setXKey]=useState('cagr')
  const [yKey,setYKey]=useState('imports')
  const [minCoverage,setMinCoverage]=useState(0)
  const [compare,setCompare]=useState([])
  const [applying,setApplying]=useState(false)

  async function load(){
    if(!project?.id)return
    setLoading(true);setError('')
    try{setData(await api(`/api/projects/${project.id}/explorer`))}
    catch(e){setError(e.message);setData(null)}
    finally{setLoading(false)}
  }
  useEffect(()=>{setCompare([]);load()},[project?.id, project?.updated_at])

  const rows=data?.rows||[]
  const visible=useMemo(()=>rows.filter(r=>(r.coverage??0)>=minCoverage && r[xKey]!=null && r[yKey]!=null),[rows,minCoverage,xKey,yKey])
  const comparisonReady=visible.length>=3
  const frontier=comparisonReady?visible.filter(r=>r.pareto_frontier):[]
  const standouts=rows.length>=3?(data?.standouts||[]).map(s=>({...s,row:rows.find(r=>r.market===s.market)})).filter(s=>s.row):[]
  const compareRows=compare.map(code=>rows.find(r=>r.market===code)).filter(Boolean)
  function toggleCompare(code){setCompare(prev=>prev.includes(code)?prev.filter(x=>x!==code):(prev.length<4?[...prev,code]:prev))}
  function useFrontier(){setCompare(frontier.slice(0,4).map(r=>r.market))}
  async function applyShortlist(runDetailed=false){
    if(!compare.length)return
    setApplying(true);setError('')
    try{
      const markets=Array.from(new Set([...(project.markets||[]),...compare]))
      await api(`/api/projects/${project.id}`,{method:'PATCH',body:JSON.stringify({markets})})
      if(runDetailed) await api(`/api/projects/${project.id}/run-analysis`,{method:'POST'})
      await onReload?.(project.id)
      if(runDetailed) onGoTrade?.()
    }catch(e){setError(e.message)}finally{setApplying(false)}
  }

  if(!project) return <PageHeader title={t('opportunityExplorer')} />
  if(!project.hs_code) return <Card><Empty title={locale==='zh'?'HS 未配置':'HS not configured'} /></Card>

  return <div className="page-stack">
    <PageHeader title={t('opportunityExplorer')} actions={<><AiRecoveryAction project={project} scope="explorer" onComplete={async()=>{await onReload?.(project.id);await load()}} label={locale==='zh'?'AI 补全证据':'AI recover evidence'}/><Button icon={RefreshCw} loading={loading} onClick={load}>{locale==='zh'?'刷新证据':'Reload evidence'}</Button><Button icon={BarChart3} variant="primary" onClick={onGoTrade}>{locale==='zh'?'打开详细贸易':'Open detailed trade'}</Button></>} />
    <ErrorBanner error={error}/>
    {!data && !loading ? <Card><Empty title={locale==='zh'?'无数据':'No data'} action={<Button variant="primary" onClick={onGoScan}>{locale==='zh'?'市场扫描':'Market Scan'}</Button>} /></Card> : <>
      {standouts.length?<div className="standout-grid">{standouts.map(s=><Card key={s.type} className="standout-card"><span>{standoutLabel(s.type,locale)}</span><b>{FLAGS[s.market]||''} {marketName(markets,s.market,locale,s.row.label)}</b><strong>{formatMetric(s.field,s.value)}</strong></Card>)}</div>:null}

      {comparisonReady&&<Card><CardHeader title={locale==='zh'?'市场对比':'Market comparison'} meta={`${visible.length}`} actions={<div className="explorer-controls"><AxisSelect label={locale==='zh'?'X 轴':'X axis'} locale={locale} value={xKey} onChange={setXKey}/><AxisSelect label={locale==='zh'?'Y 轴':'Y axis'} locale={locale} value={yKey} onChange={setYKey}/><label className="coverage-filter"><span>{locale==='zh'?'最低覆盖率':'Min coverage'}</span><select value={minCoverage} onChange={e=>setMinCoverage(Number(e.target.value))}><option value={0}>{locale==='zh'?'不限':'Any'}</option><option value={0.5}>50%+</option><option value={0.8}>80%+</option><option value={1}>100%</option></select></label></div>} />
        <div className="explorer-chart"><ResponsiveContainer width="100%" height={390}><ScatterChart margin={{top:20,right:30,bottom:20,left:20}}><CartesianGrid stroke="#d9e1e8"/><XAxis type="number" dataKey={xKey} name={locale==='zh'?(METRICS[xKey].zh||METRICS[xKey].label):METRICS[xKey].label} stroke="#64748b" tickFormatter={v=>formatMetric(xKey,v)}/><YAxis type="number" dataKey={yKey} name={locale==='zh'?(METRICS[yKey].zh||METRICS[yKey].label):METRICS[yKey].label} stroke="#64748b" tickFormatter={v=>formatMetric(yKey,v)} width={82}/><Tooltip content={<ExplorerTooltip xKey={xKey} yKey={yKey} locale={locale}/>}/><Scatter data={visible} fill="#6385a7"/><Scatter data={frontier} fill="#5d9270"/></ScatterChart></ResponsiveContainer><div className="chart-legend"><span><i className="dot regular"/>{locale==='zh'?'市场':'Market'}</span><span><i className="dot frontier"/>{locale==='zh'?'帕累托前沿':'Pareto frontier'}</span></div></div>
      </Card>}

      <div className="two-col explorer-lower">
        <Card><CardHeader title={locale==='zh'?'市场候选':'Market shortlist'} />
          <div className="data-table explorer-table"><div className="tr th"><span></span><span>{locale==='zh'?'市场':'Market'}</span><span>{locale==='zh'?'进口额':'Imports'}</span><span>{locale==='zh'?'3年复合增长率':'3Y CAGR'}</span><span>{locale==='zh'?'原产地份额':'Origin share'}</span><span>{locale==='zh'?'覆盖率':'Coverage'}</span><span>{locale==='zh'?'位置':'Position'}</span></div>{rows.map(r=><button className="tr clickable" key={r.market} onClick={()=>toggleCompare(r.market)}><span className="compare-check">{compare.includes(r.market)?<Check size={14}/>:''}</span><b>{FLAGS[r.market]||''} {marketName(markets,r.market,locale,r.label)}</b><strong>{formatMetric('imports',r.imports)}</strong><span className={r.cagr>0?'positive':r.cagr<0?'negative':''}>{formatMetric('cagr',r.cagr)}</span><span>{formatMetric('origin_share',r.origin_share)}</span><span>{formatMetric('coverage',r.coverage)}</span><span>{rows.length>=3&&r.pareto_frontier?<Badge tone="success">{locale==='zh'?'前沿':'Frontier'}</Badge>:<small>{quadrantLabel(r.quadrant,locale)}</small>}</span></button>)}</div>
        </Card>
        <Card><CardHeader title={locale==='zh'?'证据缺口':'Evidence gaps'} />
          <div className="gap-list">{rows.filter(r=>r.missing_evidence?.length).slice(0,12).map(r=><div key={r.market}><b>{FLAGS[r.market]||''} {marketName(markets,r.market,locale,r.label)}</b><span>{r.missing_evidence.map(x=>evidenceLabel(x,locale)).join(' · ')}</span><em>{formatMetric('evidence_ratio',r.evidence_ratio)}</em></div>)}</div>
        </Card>
      </div>

      <Card><CardHeader title={locale==='zh'?'并排比较':'Side-by-side comparison'} meta={compareRows.length?`${compareRows.length}/4`:''} actions={<div className="comparison-actions"><Button onClick={useFrontier} disabled={!frontier.length}>{locale==='zh'?'使用前沿市场':'Use frontier'}</Button><Button icon={Save} onClick={()=>applyShortlist(false)} loading={applying} disabled={!compare.length}>{locale==='zh'?'加入目标市场':'Add to target markets'}</Button><Button icon={Play} variant="primary" onClick={()=>applyShortlist(true)} loading={applying} disabled={!compare.length}>{locale==='zh'?'加入并同步详细数据':'Add & sync detailed'}</Button></div>} />
        {compareRows.length ? <div className="compare-grid">{compareRows.map(r=><div className="compare-market" key={r.market}><div className="compare-market-head"><b>{FLAGS[r.market]||''} {marketName(markets,r.market,locale,r.label)}</b>{r.selected&&<Badge tone="neutral">{locale==='zh'?'目标市场':'Target market'}</Badge>}</div><div className="compare-metrics"><div><span>{locale==='zh'?'进口额':'Imports'}</span><strong>{formatMetric('imports',r.imports)}</strong></div><div><span>{locale==='zh'?'3年复合增长率':'3Y CAGR'}</span><strong>{formatMetric('cagr',r.cagr)}</strong></div><div><span>{locale==='zh'?'原产地份额':'Origin share'}</span><strong>{formatMetric('origin_share',r.origin_share)}</strong></div><div><span>CR3</span><strong>{formatMetric('cr3',r.cr3)}</strong></div><div><span>HHI</span><strong>{formatMetric('hhi',r.hhi)}</strong></div><div><span>{locale==='zh'?'关税':'Tariff'}</span><strong>{formatMetric('tariff',r.tariff)}</strong></div><div><span>{locale==='zh'?'证据完整度':'Evidence'}</span><strong>{formatMetric('evidence_ratio',r.evidence_ratio)}</strong></div><div><span>{locale==='zh'?'决策状态':'Decision'}</span><strong>{decisionLabel(r.decision_status,locale)}</strong></div></div></div>)}</div> : <Empty title={locale==='zh'?'未选择':'Not selected'}/>}
      </Card>
    </>}
  </div>
}
