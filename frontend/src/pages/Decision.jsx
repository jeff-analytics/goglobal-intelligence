import React, { useEffect, useMemo, useState } from 'react'
import {
  BarChart3, Check, CheckCircle2, Clipboard, ExternalLink, Globe2, ListChecks,
  RefreshCw, ShieldAlert, Sparkles, Target, TrendingUp
} from 'lucide-react'
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis
} from 'recharts'
import { api } from '../api'
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, PageHeader } from '../components/Common'
import { FLAGS, compactMoney, money, pct, marketName } from '../utils'
import { useI18n } from '../i18n.jsx'

const tone={READY_FOR_DECISION:'success',CONDITIONAL:'warning',INSUFFICIENT_EVIDENCE:'neutral'}
const aiTone={PROCEED:'success',PROCEED_WITH_CONDITIONS:'warning',HOLD:'danger',INSUFFICIENT_EVIDENCE:'neutral'}

function fallbackCases(dashboard){
  const project=dashboard?.project;if(!project)return []
  const snapshots=dashboard?.snapshots||[];const benchmarks=dashboard?.benchmarks||{};const assumptions=project.assumptions||{}
  return (project.markets||[]).map(market=>{const snap=snapshots.find(x=>x.market===market)||null;const trade=snap?.trade||{};const suppliers=snap?.suppliers||{};const benchmark=benchmarks?.[market]||null;const costReady=assumptions.factory_cost!=null&&assumptions.platform_fee_rate!=null&&assumptions.target_margin_rate!=null;const checks={trade:Boolean((trade.world_metrics||{}).latest_value!=null||trade.latest_total_imports!=null),origin_trade:trade.latest_imports_from_origin!=null,supplier_structure:Boolean(suppliers.supplier_count),tariff:snap?.tariff?.rate!=null,fx:snap?.fx?.rate!=null,pricing_or_cost:Boolean(benchmark?.median!=null||costReady)};const available=Object.values(checks).filter(Boolean).length;const evidenceStatus=available===6?'complete':checks.trade&&available>=3?'partial':'insufficient';const blockers=[];const next_actions=[];if(!snap||(!checks.trade&&available<3)){blockers.push('Market evidence is incomplete');next_actions.push('Sync trade data for this market')}if(!checks.tariff){blockers.push('Tariff reference is unavailable');next_actions.push('Confirm a defensible tariff rate or official local tariff code')}if(!costReady){blockers.push('Private cost inputs are incomplete');next_actions.push('Complete factory cost, platform fee and target margin')}if(benchmark?.median==null){blockers.push('Market price benchmark is unavailable');next_actions.push('Add source-backed marketplace observations or a target market price')}const status=evidenceStatus==='insufficient'?'INSUFFICIENT_EVIDENCE':blockers.length?'CONDITIONAL':'READY_FOR_DECISION';return {market,status,evidence_quality:{available_blocks:available,total_blocks:6,completeness_ratio:available/6,status:evidenceStatus,missing:Object.entries(checks).filter(([,ok])=>!ok).map(([key])=>key)},evidence:{latest_year:trade.latest_year,imports:trade.latest_total_imports,origin_imports:trade.latest_imports_from_origin,origin_share:trade.latest_origin_share,trade_yoy:(trade.world_metrics||{}).yoy,trade_cagr:(trade.world_metrics||{}).cagr,trade_volatility:trade.volatility,supplier_cr3:suppliers.cr3,supplier_cr5:suppliers.cr5,supplier_hhi:suppliers.hhi,tariff_rate:snap?.tariff?.rate},economics:null,blockers,next_actions}}
  )
}

function decisionText(text, locale){if(locale!=='zh')return text;const map={'Market evidence is incomplete':'市场证据不完整','Tariff reference is unavailable':'关税参考不可用','Private cost inputs are incomplete':'企业成本输入不完整','Verified market price benchmark is unavailable':'已验证的市场价格基准不可用','Market price benchmark is unavailable':'市场价格基准不可用','Sync trade data for this market':'同步该市场的贸易数据','Confirm a defensible tariff rate or official local tariff code':'确认可靠的关税税率或当地官方税则编码','Complete factory cost, platform fee and target margin':'补充工厂成本、平台费率和目标利润率','Add source-backed marketplace observations or a target market price':'补充市场价格证据或目标市场价格'};return map[text]||text}

function dateText(value,locale){if(!value)return '—';try{return new Date(value).toLocaleString(locale==='zh'?'zh-CN':'en-US',{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch{return String(value)}}
function shortProvider(saved,locale){const p=saved?.web_research_provider;return p==='native'?(locale==='zh'?'模型原生':'Native web'):p==='tavily'?'Tavily':(locale==='zh'?'本地证据':'Evidence only')}
function decisionLabel(value,locale){return locale==='zh'?({PROCEED:'建议推进',PROCEED_WITH_CONDITIONS:'有条件推进',HOLD:'建议暂缓',INSUFFICIENT_EVIDENCE:'证据不足'}[value]||value):String(value||'').replaceAll('_',' ')}

function ResearchTooltip({active,payload,label}){if(!active||!payload?.length)return null;return <div className="decision-chart-tooltip"><b>{label}</b>{payload.map((x,i)=><div key={i}><span>{x.name}</span><strong>{typeof x.value==='number'?x.value.toFixed(1):x.value}</strong></div>)}</div>}

function DimensionCard({ icon:Icon, title, value, locale }){
  if(!value)return null
  return <section className="decision-insight-card">
    <div className="decision-insight-head"><span className="decision-insight-icon"><Icon size={16}/></span><h3>{title}</h3></div>
    <p>{value.assessment||'—'}</p>
    {value.evidence?.length>0&&<details><summary>{locale==='zh'?'查看证据':'View evidence'} <span>{value.evidence.length}</span></summary><ul>{value.evidence.map((x,i)=><li key={`${x}-${i}`}>{x}</li>)}</ul></details>}
  </section>
}

function ActionChecklist({ items=[], locale }){
  const [checked,setChecked]=useState(new Set())
  if(!items.length)return <div className="decision-empty-inline">—</div>
  return <div className="decision-action-list">{items.map((x,i)=>{const on=checked.has(i);return <button key={`${x}-${i}`} className={on?'done':''} onClick={()=>setChecked(prev=>{const n=new Set(prev);on?n.delete(i):n.add(i);return n})}><span className="decision-action-check">{on?<Check size={14}/>:i+1}</span><span>{x}</span></button>})}</div>
}

function SourcesPanel({ sources=[], locale }){
  const types=useMemo(()=>Array.from(new Set(sources.map(x=>x.source_type||'web'))),[sources])
  const [filter,setFilter]=useState('all')
  const shown=filter==='all'?sources:sources.filter(x=>(x.source_type||'web')===filter)
  if(!sources.length)return <div className="decision-empty-panel">{locale==='zh'?'本次研究未产生新的联网来源':'No new web sources were used in this research run.'}</div>
  return <>
    <div className="source-filter-row"><button className={filter==='all'?'active':''} onClick={()=>setFilter('all')}>{locale==='zh'?'全部来源':'All sources'} <span>{sources.length}</span></button>{types.map(type=><button key={type} className={filter===type?'active':''} onClick={()=>setFilter(type)}>{type} <span>{sources.filter(x=>(x.source_type||'web')===type).length}</span></button>)}</div>
    <div className="decision-source-grid">{shown.map((s,i)=><a key={`${s.url}-${i}`} href={s.url} target="_blank" rel="noreferrer"><div className="decision-source-index">{String(i+1).padStart(2,'0')}</div><div><b>{s.title||s.url}</b><span>{s.used_for||s.source_type||'research'}</span><small>{(()=>{try{return new URL(s.url).hostname}catch{return s.url}})()}</small></div><ExternalLink size={15}/></a>)}</div>
  </>
}

function ResearchReport({ saved, locale, decisionCase, currency='USD' }){
  const r=saved?.result
  const [tab,setTab]=useState('overview')
  const [copied,setCopied]=useState(false)
  if(!r)return null
  const e=decisionCase?.evidence||{}
  const econ=decisionCase?.economics||{}
  const completeness=Math.max(0,Math.min(1,Number(decisionCase?.evidence_quality?.completeness_ratio||0)))
  const evidencePie=[{name:locale==='zh'?'已覆盖':'Covered',value:Math.round(completeness*100)},{name:locale==='zh'?'缺口':'Missing',value:Math.max(0,100-Math.round(completeness*100))}]
  const structureData=[
    {name:locale==='zh'?'原产地份额':'Origin share',value:e.origin_share==null?null:Number(e.origin_share)*100},
    {name:'CR3',value:e.supplier_cr3==null?null:Number(e.supplier_cr3)*100},
    {name:'CR5',value:e.supplier_cr5==null?null:Number(e.supplier_cr5)*100},
  ].filter(x=>Number.isFinite(x.value))
  const priceData=[
    {name:locale==='zh'?'市场中位价':'Market median',value:econ.benchmark_median==null?null:Number(econ.benchmark_median)},
    {name:locale==='zh'?'所需售价':'Required price',value:econ.required_price==null?null:Number(econ.required_price)},
  ].filter(x=>Number.isFinite(x.value))
  const tabs=[['overview',locale==='zh'?'总览':'Overview'],['market',locale==='zh'?'市场':'Market'],['pricing',locale==='zh'?'定价':'Pricing'],['risks',locale==='zh'?'风险':'Risks'],['sources',locale==='zh'?'来源':'Sources'],['actions',locale==='zh'?'行动':'Actions']]
  async function copySummary(){const text=[r.headline,r.executive_summary,r.decision_language].filter(Boolean).join('\n\n');try{await navigator.clipboard.writeText(text);setCopied(true);setTimeout(()=>setCopied(false),1400)}catch{}}
  return <section className="decision-workbench">
    <div className="decision-workbench-head">
      <div className="decision-workbench-title"><div className="research-agent-icon"><Sparkles size={18}/></div><div><span className="eyebrow">{locale==='zh'?'决策研究智能体':'Decision Research Agent'}</span><h2>{r.headline}</h2></div></div>
      <div className="decision-workbench-actions"><div className="research-meta"><Badge tone={aiTone[r.decision]||'neutral'}>{decisionLabel(r.decision,locale)}</Badge><Badge tone={saved.web_research_provider==='none'?'neutral':'success'}><Globe2 size={12}/>{shortProvider(saved,locale)}</Badge></div><Button icon={copied?CheckCircle2:Clipboard} variant="secondary" onClick={copySummary}>{copied?(locale==='zh'?'已复制':'Copied'):(locale==='zh'?'复制摘要':'Copy summary')}</Button></div>
    </div>

    <div className="decision-research-kpis">
      <div><span>{locale==='zh'?'证据覆盖':'Evidence coverage'}</span><b>{Math.round(completeness*100)}%</b><small>{decisionCase?.evidence_quality?.available_blocks||0}/{decisionCase?.evidence_quality?.total_blocks||6}</small></div>
      <div><span>{locale==='zh'?'联网来源':'Web sources'}</span><b>{r.sources?.length||0}</b><small>{shortProvider(saved,locale)}</small></div>
      <div><span>{locale==='zh'?'研究调用':'Research calls'}</span><b>{saved.web_queries||0}</b><small>{locale==='zh'?'联网查询':'web queries'}</small></div>
      <div><span>{locale==='zh'?'生成时间':'Generated'}</span><b className="decision-date-kpi">{dateText(saved.generated_at,locale)}</b><small>{Number(saved.usage?.total_tokens||0)>0?`${saved.usage.total_tokens.toLocaleString()} tokens`:'—'}</small></div>
    </div>

    <div className="decision-tabs" role="tablist">{tabs.map(([key,label])=><button role="tab" aria-selected={tab===key} className={tab===key?'active':''} key={key} onClick={()=>setTab(key)}>{label}</button>)}</div>

    <div className="decision-tab-panel">
      {tab==='overview'&&<div className="decision-overview-layout">
        <div className="decision-summary-panel"><span className="section-kicker">{locale==='zh'?'执行摘要':'Executive summary'}</span><p>{r.executive_summary}</p><div className="decision-language-block"><span>{locale==='zh'?'建议表述':'Decision language'}</span><b>{r.decision_language}</b></div></div>
        <div className="decision-evidence-chart"><div className="decision-section-title"><div><span>{locale==='zh'?'证据状态':'Evidence status'}</span><b>{locale==='zh'?'覆盖与缺口':'Coverage and gaps'}</b></div></div><div className="decision-pie-wrap"><ResponsiveContainer width="100%" height={180}><PieChart><Pie data={evidencePie} dataKey="value" innerRadius={52} outerRadius={72} startAngle={90} endAngle={-270} paddingAngle={2}><Cell fill="#2f6fed"/><Cell fill="#e8edf4"/></Pie><Tooltip content={<ResearchTooltip/>}/></PieChart></ResponsiveContainer><div className="decision-pie-label"><b>{Math.round(completeness*100)}%</b><span>{locale==='zh'?'已覆盖':'covered'}</span></div></div></div>
        <div className="decision-insight-grid decision-overview-insights"><DimensionCard icon={TrendingUp} title={locale==='zh'?'市场需求':'Market demand'} value={r.market_demand} locale={locale}/><DimensionCard icon={BarChart3} title={locale==='zh'?'供给与竞争':'Supply & competition'} value={r.supply_competition} locale={locale}/><DimensionCard icon={ShieldAlert} title={locale==='zh'?'市场准入':'Market access'} value={r.market_access} locale={locale}/><DimensionCard icon={Target} title={locale==='zh'?'价格与经济性':'Pricing & economics'} value={r.pricing_economics} locale={locale}/></div>
      </div>}

      {tab==='market'&&<div className="decision-two-panel">
        <div className="decision-chart-panel"><div className="decision-section-title"><div><span>{locale==='zh'?'市场结构':'Market structure'}</span><b>{locale==='zh'?'供应集中度与原产地位置':'Supply concentration and origin position'}</b></div></div>{structureData.length?<ResponsiveContainer width="100%" height={260}><BarChart data={structureData} layout="vertical" margin={{left:12,right:24,top:8,bottom:8}}><CartesianGrid stroke="#e8edf3" horizontal={false}/><XAxis type="number" domain={[0,100]} tickFormatter={v=>`${v}%`} tickLine={false} axisLine={false}/><YAxis type="category" dataKey="name" width={110} tickLine={false} axisLine={false}/><Tooltip content={<ResearchTooltip/>}/><Bar dataKey="value" name="%" fill="#4f78a3" radius={[0,6,6,0]}/></BarChart></ResponsiveContainer>:<div className="decision-empty-panel">{locale==='zh'?'当前缺少可视化所需的市场结构数据':'Market-structure data is not available for this chart.'}</div>}</div>
        <div className="decision-insight-stack"><DimensionCard icon={TrendingUp} title={locale==='zh'?'市场需求判断':'Market demand assessment'} value={r.market_demand} locale={locale}/><DimensionCard icon={BarChart3} title={locale==='zh'?'供给与竞争判断':'Supply & competition assessment'} value={r.supply_competition} locale={locale}/></div>
      </div>}

      {tab==='pricing'&&<div className="decision-two-panel">
        <div className="decision-chart-panel"><div className="decision-section-title"><div><span>{locale==='zh'?'经济性':'Economics'}</span><b>{locale==='zh'?'所需售价与市场基准':'Required price vs market benchmark'}</b></div>{econ.premium_to_median!=null&&<Badge tone={econ.premium_to_median<=0?'success':'warning'}>{locale==='zh'?'价差':'Gap'} {pct(econ.premium_to_median)}</Badge>}</div>{priceData.length>=2?<ResponsiveContainer width="100%" height={260}><BarChart data={priceData} margin={{left:8,right:18,top:12,bottom:8}}><CartesianGrid stroke="#e8edf3" vertical={false}/><XAxis dataKey="name" tickLine={false} axisLine={false}/><YAxis tickLine={false} axisLine={false}/><Tooltip formatter={v=>money(v,currency)}/><Bar dataKey="value" name={locale==='zh'?'价格':'Price'} fill="#2f6fed" radius={[7,7,0,0]}/></BarChart></ResponsiveContainer>:<div className="decision-empty-panel">{locale==='zh'?'当前缺少完整的市场价格与成本结果':'A complete market benchmark and pricing result is required for this chart.'}</div>}</div>
        <div className="decision-insight-stack"><DimensionCard icon={Target} title={locale==='zh'?'价格与经济性判断':'Pricing & economics assessment'} value={r.pricing_economics} locale={locale}/><div className="decision-number-grid"><div><span>{locale==='zh'?'所需售价':'Required price'}</span><b>{money(econ.required_price,currency)}</b></div><div><span>{locale==='zh'?'市场中位价':'Market median'}</span><b>{money(econ.benchmark_median,currency)}</b></div><div><span>{locale==='zh'?'价格缺口':'Price gap'}</span><b className={econ.premium_to_median<=0?'positive':'negative'}>{pct(econ.premium_to_median)}</b></div><div><span>{locale==='zh'?'关税参考':'Tariff reference'}</span><b>{e.tariff_rate==null?'—':`${Number(e.tariff_rate).toFixed(2)}%`}</b></div></div></div>
      </div>}

      {tab==='risks'&&<div className="decision-risk-layout">
        <section><div className="decision-section-title"><div><span>{locale==='zh'?'AI 识别':'AI assessment'}</span><b>{locale==='zh'?'关键风险':'Key risks'}</b></div><Badge tone={r.risks?.length?'warning':'success'}>{r.risks?.length||0}</Badge></div>{r.risks?.length?<ul className="decision-risk-list">{r.risks.map((x,i)=><li key={`${x}-${i}`}><span>{i+1}</span><p>{x}</p></li>)}</ul>:<div className="decision-empty-panel">—</div>}</section>
        <section><div className="decision-section-title"><div><span>{locale==='zh'?'确定性规则':'Deterministic checks'}</span><b>{locale==='zh'?'主要阻碍':'Blockers'}</b></div><Badge tone={decisionCase?.blockers?.length?'warning':'success'}>{decisionCase?.blockers?.length||0}</Badge></div>{decisionCase?.blockers?.length?<ul className="decision-risk-list deterministic">{decisionCase.blockers.map((x,i)=><li key={`${x}-${i}`}><span>{i+1}</span><p>{decisionText(x,locale)}</p></li>)}</ul>:<div className="decision-empty-panel">—</div>}</section>
        <section className="decision-gap-panel"><div className="decision-section-title"><div><span>{locale==='zh'?'验证状态':'Validation'}</span><b>{locale==='zh'?'尚未验证':'Evidence gaps'}</b></div><Badge tone={r.evidence_gaps?.length?'neutral':'success'}>{r.evidence_gaps?.length||0}</Badge></div>{r.evidence_gaps?.length?<ul>{r.evidence_gaps.map((x,i)=><li key={`${x}-${i}`}>{x}</li>)}</ul>:<div className="decision-empty-panel">—</div>}</section>
      </div>}

      {tab==='sources'&&<><SourcesPanel sources={r.sources||[]} locale={locale}/>{r.research_plan?.length>0&&<details className="decision-plan-details"><summary>{locale==='zh'?'查看研究计划':'View research plan'} <span>{r.research_plan.length}</span></summary><ol>{r.research_plan.map((x,i)=><li key={`${x}-${i}`}>{x}</li>)}</ol></details>}</>}

      {tab==='actions'&&<div className="decision-actions-layout"><section><div className="decision-section-title"><div><span>{locale==='zh'?'建议执行':'Recommended execution'}</span><b>{locale==='zh'?'下一步行动':'Next actions'}</b></div><ListChecks size={18}/></div><ActionChecklist items={r.next_actions||[]} locale={locale}/></section><section><div className="decision-section-title"><div><span>{locale==='zh'?'系统规则':'System checks'}</span><b>{locale==='zh'?'确定性下一步':'Deterministic next actions'}</b></div></div><ActionChecklist items={(decisionCase?.next_actions||[]).map(x=>decisionText(x,locale))} locale={locale}/></section></div>}
    </div>
  </section>
}

export default function Decision({ dashboard, markets }){
  const { t, locale } = useI18n();const project=dashboard?.project
  const [cases,setCases]=useState(()=>fallbackCases(dashboard));const [loading,setLoading]=useState(false);const [error,setError]=useState('');const [research,setResearch]=useState({});const [aiLoading,setAiLoading]=useState('');const [confirmMarket,setConfirmMarket]=useState('');const [researchCaps,setResearchCaps]=useState(null)
  async function load(){if(!project)return;setLoading(true);setError('');const fallback=fallbackCases(dashboard);try{const r=await api(`/api/projects/${project.id}/decision-cases`);const nextCases=r.cases||[];setCases(nextCases);const pairs=await Promise.all(nextCases.map(async c=>{try{const b=await api(`/api/projects/${project.id}/ai/research?market=${c.market}&locale=${locale}`);if(b.capabilities)setResearchCaps(b.capabilities);return [c.market,b.research]}catch{return [c.market,null]}}));setResearch(Object.fromEntries(pairs))}catch(e){if(fallback.length){setCases(fallback);setError('')}else setError(e.message)}finally{setLoading(false)}}
  useEffect(()=>{setCases(fallbackCases(dashboard));setResearch({});setConfirmMarket('')},[project?.id])
  useEffect(()=>{load()},[project?.id,project?.updated_at,dashboard?.snapshots?.length,locale])
  async function generate(market){if(confirmMarket!==market){setConfirmMarket(market);return}setConfirmMarket('');setAiLoading(market);setError('');try{const r=await api(`/api/projects/${project.id}/ai/research?market=${market}&locale=${locale}`,{method:'POST'});setResearch(prev=>({...prev,[market]:r.research}));if(r.capabilities)setResearchCaps(r.capabilities)}catch(e){setError(e.message)}finally{setAiLoading('')}}
  if(!project)return <PageHeader title={t('decisionCases')}/>
  return <div className="page-stack decision-page"><PageHeader title={t('decisionCases')} actions={<Button icon={RefreshCw} loading={loading} onClick={load}>{locale==='zh'?'刷新':'Refresh'}</Button>}/><ErrorBanner error={error}/>{!cases.length&&!loading?<Card><Empty title={locale==='zh'?'暂无决策案例':'No decision case yet'}/></Card>:<div className="decision-grid">{cases.map(c=>{const market=markets.find(m=>m.code===c.market);const e=c.evidence||{};const econ=c.economics||{};const saved=research[c.market];const confirming=confirmMarket===c.market;const webReady=researchCaps?.web_search_available;return <Card key={c.market} className="decision-card"><CardHeader title={`${FLAGS[c.market]||''} ${marketName(markets,c.market,locale,market?.label||c.market)}`} actions={<div className="decision-card-actions"><Badge tone={tone[c.status]||'neutral'}>{locale==='zh'?({'READY_FOR_DECISION':'可进入决策','CONDITIONAL':'有条件','INSUFFICIENT_EVIDENCE':'证据不足'}[c.status]||c.status):c.status.replaceAll('_',' ')}</Badge><Button icon={Sparkles} variant={confirming?'primary':'secondary'} loading={aiLoading===c.market} onClick={()=>generate(c.market)}>{confirming?(locale==='zh'?'确认研究':'Confirm research'):(saved?(locale==='zh'?'重新研究':'Run again'):(locale==='zh'?'AI 决策研究':'AI decision research'))}</Button></div>}/><div className="evidence-strip"><div><span>{locale==='zh'?'证据完整度':'Evidence'}</span><b>{c.evidence_quality?.available_blocks}/{c.evidence_quality?.total_blocks}</b></div><div><span>{locale==='zh'?'进口额':'Imports'}</span><b>{compactMoney(e.imports,'USD')}</b></div><div><span>{locale==='zh'?'原产地份额':'Origin share'}</span><b>{pct(e.origin_share)}</b></div><div><span>CR3</span><b>{pct(e.supplier_cr3)}</b></div></div>{econ.required_price!=null&&<div className="economics-box"><div><span>{locale==='zh'?'所需售价':'Required price'}</span><b>{money(econ.required_price,market?.currency||'USD')}</b></div><div><span>{locale==='zh'?'市场基准中位价':'Benchmark median'}</span><b>{money(econ.benchmark_median,market?.currency||'USD')}</b></div><div><span>{locale==='zh'?'溢价 / 缺口':'Premium / gap'}</span><b className={econ.premium_to_median<=0?'positive':'negative'}>{pct(econ.premium_to_median)}</b></div></div>}<div className="decision-body"><div><h3>{locale==='zh'?'主要阻碍':'Blockers'}</h3>{c.blockers?.length?<ul>{c.blockers.map(x=><li key={x}>{decisionText(x,locale)}</li>)}</ul>:<p>—</p>}</div><div><h3>{locale==='zh'?'下一步':'Next actions'}</h3>{c.next_actions?.length?<ol>{c.next_actions.map(x=><li key={x}>{decisionText(x,locale)}</li>)}</ol>:<p>—</p>}</div></div>{confirming&&<div className="research-confirm-note"><Globe2 size={15}/><span>{webReady?(locale==='zh'?'将使用当前证据并执行已配置的联网研究。':'This run will use current evidence and the configured web research provider.'):(locale==='zh'?'当前未配置联网研究，将只使用已有证据。':'Web research is not configured; this run will use existing evidence only.')}</span></div>}<ResearchReport saved={saved} locale={locale} decisionCase={c} currency={market?.currency||'USD'}/></Card>})}</div>}</div>
}
