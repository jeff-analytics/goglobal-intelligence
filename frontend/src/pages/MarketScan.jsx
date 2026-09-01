import React, { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Download, Play, RefreshCw, Save, Search, Target } from 'lucide-react'
import { api, downloadCsv } from '../api'
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, PageHeader } from '../components/Common'
import { AiRecoveryAction } from '../components/AiRecovery'
import { FLAGS, compactMoney, currentAnalysisYears, pct, marketName } from '../utils'
import { useI18n } from '../i18n.jsx'

const sortOptions=[['imports','Imports','进口额'],['cagr','3Y CAGR','3年增速'],['origin_share','Origin share','原产地份额'],['coverage_ratio','Coverage','覆盖率'],['latest_year','Latest year','最新年份']]
const paretoOptions=[
  ['imports','max','Demand / imports','市场需求 / 进口额'],['cagr','max','Growth','增长'],['margin_at_benchmark','max','Margin at market price','市场价格下毛利率'],
  ['tariff','min','Tariff burden','关税负担'],['hhi','min','Supply concentration','供应集中度'],['evidence_ratio','max','Evidence completeness','证据完整度']
]

export default function MarketScan({ dashboard, markets, onReload, onGoSetup, onGoTrade }) {
  const { t, locale } = useI18n()
  const project = dashboard?.project
  const [rows, setRows] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(project?.markets || [])
  const [filter, setFilter] = useState('')
  const [minCoverage,setMinCoverage]=useState(0)
  const [sortKey,setSortKey]=useState('imports')
  const [sortDir,setSortDir]=useState('desc')
  const [scanMeta, setScanMeta] = useState(null)
  const [pareto,setPareto]=useState(null)
  const [paretoLoading,setParetoLoading]=useState(false)
  const [paretoKeys,setParetoKeys]=useState(['imports','cagr','margin_at_benchmark','tariff','hhi'])
  const years = currentAnalysisYears()
  useEffect(()=>{ setSelected(project?.markets || []); setRows(null); setScanMeta(null); setPareto(null); setError('') },[project?.id])
  useEffect(()=>{
    if(!project?.id || !project?.hs_code) return
    loadCachedOrScan()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[project?.id, project?.hs_code, project?.origin])

  const visible = useMemo(() => {
    const out=(rows || []).filter(r => {
      const name=marketName(markets,r.market,locale,r.label)
      return (!filter || name.toLowerCase().includes(filter.toLowerCase()) || r.market.toLowerCase().includes(filter.toLowerCase())) && (r.coverage_ratio||0)>=minCoverage
    })
    out.sort((a,b)=>{
      const av=a?.[sortKey], bv=b?.[sortKey]
      if(av==null&&bv==null)return 0
      if(av==null)return 1
      if(bv==null)return -1
      const delta=Number(av)-Number(bv)
      return sortDir==='asc'?delta:-delta
    })
    return out
  }, [rows, filter, markets, locale,minCoverage,sortKey,sortDir])

  if (!project) return <PageHeader title={t('marketScan')} />
  if (!project.hs_code) return <Card><Empty title={locale==='zh'?'HS 未配置':'HS not configured'} action={<Button variant="primary" onClick={onGoSetup}>{locale==='zh'?'项目设置':'Project Setup'}</Button>} /></Card>

  async function loadCachedOrScan() {
    setLoading(true); setError('')
    try {
      const cached = await api(`/api/projects/${project.id}/market-scan`)
      if(cached?.cached && !cached?.stale && cached?.scan){ setRows(cached.scan.markets || []); setScanMeta(cached.scan); return }
      await scan(true)
    } catch(e) { setError(e.message) }
    finally { setLoading(false) }
  }

  async function scan(fromLoad=false) {
    if(!fromLoad){ setLoading(true); setError('') }
    try {
      const r = await api(`/api/projects/${project.id}/market-scan?lookback_years=5`, { method:'POST' })
      setRows(r.markets || []); setScanMeta(r)
    } catch(e) { setError(e.message) }
    finally { if(!fromLoad) setLoading(false) }
  }

  function toggle(code) { setSelected(selected.includes(code) ? selected.filter(x=>x!==code) : [...selected, code]) }
  function toggleVisible(){
    const codes=visible.map(x=>x.market)
    const all=codes.length>0&&codes.every(x=>selected.includes(x))
    setSelected(all?selected.filter(x=>!codes.includes(x)):[...new Set([...selected,...codes])])
  }

  async function save() {
    setSaving(true); setError('')
    try { await api(`/api/projects/${project.id}`, { method:'PATCH', body:JSON.stringify({ markets:selected }) }); await onReload(project.id) }
    catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }


  async function runPareto(){
    if(paretoKeys.length<2){setError(locale==='zh'?'至少选择两个目标维度':'Select at least two objectives');return}
    setParetoLoading(true);setError('')
    try{
      const objectives=paretoOptions.filter(x=>paretoKeys.includes(x[0])).map(([key,direction])=>({key,direction}))
      const r=await api(`/api/projects/${project.id}/pareto`,{method:'POST',body:JSON.stringify({objectives})})
      setPareto(r)
    }catch(e){setError(e.message)}finally{setParetoLoading(false)}
  }
  function togglePareto(key){setParetoKeys(x=>x.includes(key)?x.filter(v=>v!==key):[...x,key])}
  async function run() {
    setRunning(true); setError('')
    try {
      await api(`/api/projects/${project.id}`, { method:'PATCH', body:JSON.stringify({ markets:selected }) })
      await api(`/api/projects/${project.id}/run-analysis?start_year=${years.start}&end_year=${years.end}`, { method:'POST' })
      await onReload(project.id); onGoTrade?.()
    } catch(e) { setError(e.message) }
    finally { setRunning(false) }
  }

  const exportRows=(rows||[]).map(r=>({market:r.market,label:r.label,latest_year:r.latest_year,imports:r.imports,yoy:r.yoy,cagr:r.cagr,origin_imports:r.origin_imports,origin_share:r.origin_share,coverage_ratio:r.coverage_ratio,source:r.source}))
  const observed=(rows||[]).filter(r=>r.available).length

  return <div className="page-stack">
    <PageHeader title={t('marketScan')} actions={<><AiRecoveryAction project={project} scope="market_scan" markets={selected} disabled={!selected.length} onComplete={async()=>{await onReload(project.id);await loadCachedOrScan()}} label={locale==='zh'?'AI 补全市场':'AI recover markets'}/><Button icon={RefreshCw} loading={loading} onClick={scan}>{locale==='zh'?'刷新':'Refresh'}</Button><Button icon={Save} loading={saving} disabled={!selected.length} onClick={save}>{locale==='zh'?'保存':'Save'}</Button><Button icon={Play} variant="primary" loading={running} disabled={!selected.length} onClick={run}>{locale==='zh'?'详细分析':'Detailed analysis'}</Button></>} />
    <ErrorBanner error={error}/>
    <Card><CardHeader title={locale==='zh'?'市场证据':'Market evidence'} meta={rows ? `${observed}/${rows.length}${scanMeta?.scanned_at ? ` · ${new Date(scanMeta.scanned_at).toLocaleString()}` : ''}` : null} actions={rows && <Button icon={Download} variant="secondary" onClick={()=>downloadCsv(`goglobal-market-scan-${project.id}.csv`, exportRows)}>CSV</Button>} />
      {rows&&<div className="research-toolbar">
        <div className="table-search"><Search size={15}/><input value={filter} onChange={e=>setFilter(e.target.value)} placeholder={locale==='zh'?'市场':'Market'}/></div>
        <label><span>{locale==='zh'?'覆盖率':'Coverage'}</span><select value={minCoverage} onChange={e=>setMinCoverage(Number(e.target.value))}><option value={0}>{locale==='zh'?'全部':'All'}</option><option value={0.5}>50%+</option><option value={0.8}>80%+</option><option value={1}>100%</option></select></label>
        <label><span>{locale==='zh'?'排序':'Sort'}</span><select value={sortKey} onChange={e=>setSortKey(e.target.value)}>{sortOptions.map(([v,en,zh])=><option value={v} key={v}>{locale==='zh'?zh:en}</option>)}</select></label>
        <Button variant="secondary" icon={sortDir==='desc'?ArrowDown:ArrowUp} onClick={()=>setSortDir(x=>x==='desc'?'asc':'desc')}>{sortDir==='desc'?(locale==='zh'?'降序':'Desc'):(locale==='zh'?'升序':'Asc')}</Button>
        <Button variant="secondary" onClick={toggleVisible}>{visible.length&&visible.every(x=>selected.includes(x))?(locale==='zh'?'取消当前':'Clear visible'):(locale==='zh'?'选择当前':'Select visible')}</Button>
      </div>}
      {!rows ? <Empty title={loading ? (locale==='zh'?'加载中':'Loading') : (locale==='zh'?'暂无数据':'No data')} /> : <div className="data-table scan-table multi-scan">
        <div className="tr th"><span></span><span>{locale==='zh'?'市场':'Market'}</span><span>{locale==='zh'?'最新年份':'Latest year'}</span><span>{locale==='zh'?'进口额':'Imports'}</span><span>{locale==='zh'?'同比':'YoY'}</span><span>{locale==='zh'?'3年复合增速':'3Y CAGR'}</span><span>{locale==='zh'?'原产地份额':'Origin share'}</span><span>{locale==='zh'?'覆盖率':'Coverage'}</span></div>
        {visible.map(r => {const af=r.ai_recovered_fields||[];return <div className="tr" key={r.market}><span><input type="checkbox" checked={selected.includes(r.market)} onChange={()=>toggle(r.market)}/></span><b>{FLAGS[r.market] || '🌐'} {marketName(markets,r.market,locale,r.label)} {af.length?<Badge tone="warning">AI</Badge>:null}</b><span>{r.latest_year||'—'}</span><strong className={af.includes('imports')?'ai-filled-inline':''}>{r.imports != null ? compactMoney(r.imports, 'USD') : '—'}</strong><span className={`${r.yoy>0?'positive':r.yoy<0?'negative':''} ${af.includes('yoy')?'ai-filled-inline':''}`.trim()}>{pct(r.yoy)}</span><span className={`${r.cagr>0?'positive':r.cagr<0?'negative':''} ${af.includes('cagr')?'ai-filled-inline':''}`.trim()}>{pct(r.cagr)}</span><span className={af.includes('origin_share')?'ai-filled-inline':''}>{pct(r.origin_share)}</span><span><Badge tone={r.coverage_ratio===1?'success':r.coverage_ratio>0?'warning':'neutral'}>{pct(r.coverage_ratio,0)}</Badge></span></div>})}
      </div>}
    </Card>

    <Card className="pareto-card"><CardHeader title={locale==='zh'?'Pareto 多目标市场筛选':'Pareto multi-objective screening'} meta={pareto?`${pareto.frontier?.length||0} ${locale==='zh'?'个前沿市场':'frontier markets'}`:null} actions={<Button icon={Target} variant="primary" loading={paretoLoading} onClick={runPareto}>{locale==='zh'?'运行非支配排序':'Run non-dominated sort'}</Button>}/>
      <div className="pareto-objectives">{paretoOptions.map(([key,,en,zh])=><label key={key} className={paretoKeys.includes(key)?'active':''}><input type="checkbox" checked={paretoKeys.includes(key)} onChange={()=>togglePareto(key)}/><span>{locale==='zh'?zh:en}</span></label>)}</div>
      {pareto?<><div className="pareto-frontier-strip"><span>{locale==='zh'?'第一前沿':'Front 1'}</span>{(pareto.frontier||[]).map(code=><Badge key={code} tone="success">{FLAGS[code]||'🌐'} {marketName(markets,code,locale,code)}</Badge>)}{!(pareto.frontier||[]).length?<span>—</span>:null}</div>
        <div className="data-table pareto-table"><div className="tr th"><span>{locale==='zh'?'市场':'Market'}</span><span>{locale==='zh'?'前沿层级':'Front'}</span><span>{locale==='zh'?'拥挤距离':'Crowding'}</span><span>{locale==='zh'?'结论':'Reason'}</span></div>{(pareto.ranked||[]).slice(0,24).map(r=><div className="tr" key={r.market}><b>{FLAGS[r.market]||'🌐'} {marketName(markets,r.market,locale,r.label||r.market)}</b><span><Badge tone={r.pareto_rank===1?'success':r.pareto_rank===2?'warning':'neutral'}>F{r.pareto_rank}</Badge></span><span>{r.crowding_distance==null?'Boundary':Number(r.crowding_distance).toFixed(2)}</span><span>{r.pareto_rank===1?(locale==='zh'?'当前目标组合下未被其他市场支配':'Not dominated on selected objectives'):(r.explanation?.dominated_by?(locale==='zh'?`被 ${marketName(markets,r.explanation.dominated_by,locale,r.explanation.dominated_by)} 支配`:`Dominated by ${marketName(markets,r.explanation.dominated_by,locale,r.explanation.dominated_by)}`):(locale==='zh'?'次级非支配前沿':'Lower non-dominated front'))}</span></div>)}</div>
        {(pareto.incomplete||[]).length>0?<div className="pareto-incomplete"><Badge tone="warning">{pareto.incomplete.length}</Badge><span>{locale==='zh'?'个市场因所选维度数据不完整未参与排序':'markets excluded because selected objective data are incomplete'}</span></div>:null}</>:<Empty title={locale==='zh'?'选择至少两个维度后运行筛选':'Choose at least two objectives and run screening'}/>}
    </Card>
  </div>
}
