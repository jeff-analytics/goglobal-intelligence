import React,{useEffect,useMemo,useState} from 'react'
import {ExternalLink,RefreshCw,Search} from 'lucide-react'
import {api} from '../api'
import {Badge,Button,Card,CardHeader,Empty,ErrorBanner,PageHeader,ProgressBar} from '../components/Common'
import {FLAGS,compactMoney,pct,localizeRuntimeMessage} from '../utils'
import {AiRecoveryAction} from '../components/AiRecovery'
import { useI18n } from '../i18n.jsx'

const tierTone={decision_ready_core:'success',research_ready:'warning',limited:'neutral'}
const sourceTone={live:'success',cached:'blue','stale-cache':'warning',error:'danger',idle:'neutral',ok:'success'}

function formatTime(value,locale){
  if(!value)return '—'
  try{return new Date(value).toLocaleString(locale==='zh'?'zh-CN':'en-US',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch{return '—'}
}
function modeName(value,locale){
  if(locale!=='zh')return value||'—'
  return ({api:'API',scrape:'网页采集',manual:'人工',public:'公开',cached:'缓存'}[value]||value||'—')
}
function providerName(value,locale){
  if(locale!=='zh')return value
  return ({'UN Comtrade':'UN Comtrade','UNCTAD TRAINS / WITS':'WITS / TRAINS','ECB':'ECB','eBay':'eBay','Official Tariff':'官方税则'}[value]||value)
}
function statusName(value,locale){
  if(locale!=='zh') return String(value||'idle').replace('-', ' ')
  return ({live:'实时',cached:'缓存','stale-cache':'历史缓存',error:'异常',idle:'未调用',ok:'正常'}[value]||value||'未调用')
}

function formatLatency(value){
  const n=Number(value)
  if(!Number.isFinite(n))return '—'
  return n>=1000?`${(n/1000).toFixed(n>=10000?1:2)} s`:`${Math.round(n)} ms`
}
function runtimeStatus(s,locale){
  const err=String(s?.last_error||'').toLowerCase()
  if(s?.provider==='UNCTAD TRAINS / WITS'&&s?.status==='error')return locale==='zh'?'暂不可用':'Unavailable'
  if(s?.status==='error'&&String(s?.last_error||'').includes('WITS_NETWORK_PAUSED'))return locale==='zh'?'已暂停':'Paused'
  if(s?.status==='error'&&err.includes('timed out'))return locale==='zh'?'超时':'Timeout'
  if(s?.status==='error'&&(err.includes('connection failed')||err.includes('connectionerror')||err.includes('name resolution')))return locale==='zh'?'连接失败':'Connection failed'
  return statusName(s?.status,locale)
}
function compactSourceError(value,locale){
  const raw=String(value||'').trim()
  if(!raw)return ''
  const low=raw.toLowerCase()
  const localized=localizeRuntimeMessage(raw,locale)
  if(localized!==raw)return localized
  return raw.length>140?`${raw.slice(0,137)}…`:raw
}

export default function DataBackbone({dashboard,markets,onReload}){
  const { t, locale } = useI18n()
  const project=dashboard?.project
  const [support,setSupport]=useState([])
  const [contracts,setContracts]=useState([])
  const [runtime,setRuntime]=useState({sources:[]})
  const [aiEvidence,setAiEvidence]=useState([])
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [showAll,setShowAll]=useState(false)
  const [supportQuery,setSupportQuery]=useState('')
  const [supportMode,setSupportMode]=useState('all')
  const marketMap=useMemo(()=>Object.fromEntries(markets.map(m=>[m.code,m])),[markets])
  async function load(){
    setLoading(true);setError('')
    try{
      const [s,r]=await Promise.all([api('/api/data/backbone/support'),api('/api/data/runtime')])
      setSupport(s.markets||[]);setRuntime(r||{sources:[]})
      if(project){const [b,a]=await Promise.all([api(`/api/projects/${project.id}/backbone`),api(`/api/projects/${project.id}/ai/evidence`)]);setContracts(b.markets||[]);setAiEvidence(a.records||[])}else{setContracts([]);setAiEvidence([])}
    }catch(e){setError(e.message)}finally{setLoading(false)}
  }
  useEffect(()=>{load()},[project?.id,project?.updated_at,dashboard?.snapshots?.length])
  const visibleSupport=(showAll?support:support.filter(r=>marketMap[r.market]?.featured)).filter(r=>{const q=supportQuery.trim().toLowerCase();const name=locale==='zh'?(r.label_zh||r.label):(r.label||r.label_zh);const matches=!q||String(r.market||'').toLowerCase().includes(q)||String(name||'').toLowerCase().includes(q);const modeOk=supportMode==='all'||r.tariff_mode===supportMode;return matches&&modeOk})
  return <div className="page-stack">
    <PageHeader title={t('dataBackbone')} actions={<>{project&&<AiRecoveryAction project={project} scope="backbone" onComplete={async()=>{await onReload?.(project.id);await load()}} label={locale==='zh'?'AI 修复数据缺口':'AI recover data gaps'}/>}<Button icon={RefreshCw} loading={loading} onClick={load}>{locale==='zh'?'刷新':'Refresh'}</Button></>}/>
    <ErrorBanner error={error}/>

    <div className="runtime-grid">
      {(runtime.sources||[]).map(s=><Card className="runtime-card" key={s.provider}>
        <div className="runtime-card-head"><b>{providerName(s.provider,locale)}</b><Badge tone={sourceTone[s.status]||'neutral'}>{runtimeStatus(s,locale)}</Badge></div>
        <div className="runtime-card-kpis"><div><span>{locale==='zh'?'最近成功':'Last success'}</span><strong>{formatTime(s.last_success_at,locale)}</strong></div><div><span>{locale==='zh'?'请求':'Requests'}</span><strong>{s.provider==='UN Comtrade'&&runtime.comtrade_daily_limit?`${s.network_requests_today||0}/${runtime.comtrade_daily_limit}`:(s.network_requests_today||0)}</strong></div><div><span>{locale==='zh'?'缓存率':'Cache ratio'}</span><strong>{s.cache_hit_ratio==null?'—':`${Math.round(s.cache_hit_ratio*100)}%`}</strong></div><div><span>{locale==='zh'?'缓存条目':'Cache entries'}</span><strong>{s.cache_entries||0}</strong></div></div>
        {(s.last_latency_ms!=null||s.failures_today>0||s.stale_hits_today>0)&&<div className="runtime-foot">{s.last_latency_ms!=null&&!(s.provider==='UNCTAD TRAINS / WITS'&&s.status==='error')?<span>{formatLatency(s.last_latency_ms)}</span>:null}{s.failures_today>0&&<Badge tone="danger">{s.failures_today} {locale==='zh'?'失败':'failed'}</Badge>}{s.stale_hits_today>0&&<Badge tone="warning">{s.stale_hits_today} {locale==='zh'?'历史缓存':'stale'}</Badge>}</div>}{s.status==='error'&&s.last_error&&<div className="runtime-source-error">{compactSourceError(s.last_error,locale)}</div>}
      </Card>)}
    </div>

    {project?<Card><CardHeader title={locale==='zh'?'项目证据':'Project evidence'} meta={`${project.title}${aiEvidence.length?` · AI ${aiEvidence.length}`:''}`}/>{contracts.length?<div className="contract-grid">{contracts.map(c=><div className="contract-card" key={c.market}><div className="contract-head"><b>{FLAGS[c.market]||''} {locale==='zh'?(markets.find(m=>m.code===c.market)?.label_zh||c.label):c.label}</b><Badge tone={tierTone[c.quality?.support_tier]||'neutral'}>{locale==='zh'?({'decision_ready_core':'决策可用','research_ready':'研究可用','limited':'有限'}[c.quality?.support_tier||'limited']||c.quality?.support_tier):String(c.quality?.support_tier||'limited').replaceAll('_',' ')}</Badge></div><ProgressBar value={c.quality?.completeness_ratio||0}/><div className="contract-metrics"><div><span>{locale==='zh'?'进口额':'Imports'}</span><b>{compactMoney(c.trade?.imports,'USD')}</b></div><div><span>{locale==='zh'?'原产地份额':'Origin share'}</span><b>{pct(c.trade?.origin_share)}</b></div><div><span>CR3</span><b>{pct(c.supply?.cr3)}</b></div><div><span>{locale==='zh'?'关税':'Tariff'}</span><b>{c.tariff?.rate!=null?`${Number(c.tariff.rate).toFixed(2)}%`:locale==='zh'?'缺失':'Missing'}</b></div></div><div className="contract-links">{c.tariff?.official_url&&<a href={c.tariff.official_url} target="_blank" rel="noreferrer"><ExternalLink size={13}/> {locale==='zh'?'关税':'Tariff'}</a>}{c.tax?.official_url&&<a href={c.tax.official_url} target="_blank" rel="noreferrer"><ExternalLink size={13}/> {locale==='zh'?'税务':'Tax'}</a>}</div></div>)}</div>:<Empty title={locale==='zh'?'暂无数据':'No data'}/>}</Card>:null}

    <Card><CardHeader title={locale==='zh'?'市场支持':'Market support'} meta={`${visibleSupport.length}/${showAll?support.length:support.filter(r=>marketMap[r.market]?.featured).length}`} actions={<div className="support-toolbar"><div className="table-search"><Search size={15}/><input value={supportQuery} onChange={e=>setSupportQuery(e.target.value)}/></div><select value={supportMode} onChange={e=>setSupportMode(e.target.value)}><option value="all">{locale==='zh'?'全部模式':'All modes'}</option><option value="api">API</option><option value="scrape">{locale==='zh'?'网页采集':'Scrape'}</option><option value="manual">{locale==='zh'?'人工':'Manual'}</option></select><Button variant="secondary" onClick={()=>setShowAll(!showAll)}>{showAll?(locale==='zh'?'重点市场':'Featured'):(locale==='zh'?`全部 ${support.length}`:`All ${support.length}`)}</Button></div>}/>
      <div className="backbone-table"><div className="backbone-row header"><span>{locale==='zh'?'市场':'Market'}</span><span>{locale==='zh'?'贸易':'Trade'}</span><span>{locale==='zh'?'关税来源':'Tariff source'}</span><span>{locale==='zh'?'模式':'Mode'}</span><span>{locale==='zh'?'税务来源':'Tax source'}</span><span>{locale==='zh'?'税则位数':'Code digits'}</span></div>{visibleSupport.map(r=><div className="backbone-row" key={r.market}><b>{FLAGS[r.market]||''} {locale==='zh'?(r.label_zh||r.label):r.label}</b><span>UN Comtrade</span><span>{r.tariff_provider||'—'}</span><span><Badge tone={r.tariff_mode==='api'||r.tariff_mode==='scrape'?'success':'neutral'}>{modeName(r.tariff_mode,locale)}</Badge></span><span>{r.tax_provider||'—'}</span><span>{r.local_code_digits||'—'}</span></div>)}</div>
    </Card>
  </div>
}
