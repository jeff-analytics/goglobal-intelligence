import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Play, Save, Search, Tags, WandSparkles } from 'lucide-react'
import { api } from '../api'
import { Badge, Button, Card, CardHeader, ErrorBanner, Field, PageHeader, ProgressBar, StatusLine, TextArea } from '../components/Common'
import { FLAGS, currentAnalysisYears } from '../utils'
import WorldMarketPicker from '../components/WorldMarketPicker.jsx'
import { useI18n } from '../i18n.jsx'

function useAnchoredOverlay(anchorRef, active) {
  const [style,setStyle]=useState(null)
  useEffect(()=>{
    if(!active){setStyle(null);return}
    const update=()=>{
      const el=anchorRef.current
      if(!el) return
      const r=el.getBoundingClientRect()
      const viewportPad=12
      const maxWidth=Math.max(260, window.innerWidth - viewportPad*2)
      setStyle({
        position:'fixed',
        left:Math.max(viewportPad,Math.min(r.left,window.innerWidth-viewportPad-Math.min(r.width,maxWidth))),
        top:r.bottom+6,
        width:Math.min(r.width,maxWidth),
      })
    }
    update()
    window.addEventListener('resize',update)
    window.addEventListener('scroll',update,true)
    return()=>{
      window.removeEventListener('resize',update)
      window.removeEventListener('scroll',update,true)
    }
  },[anchorRef,active])
  return style
}

function OriginPicker({ value, onChange }) {
  const { locale } = useI18n()
  const [items,setItems]=useState([])
  const [loading,setLoading]=useState(false)
  const [open,setOpen]=useState(false)
  const inputRef=useRef(null)
  const menuStyle=useAnchoredOverlay(inputRef,open&&items.length>0)
  useEffect(()=>{
    if(!open){setItems([]);return}
    const q=String(value||'').trim()
    if(!q){setItems([]);return}
    const id=setTimeout(async()=>{
      setLoading(true)
      try{ const r=await api(`/api/reference/partners?q=${encodeURIComponent(q)}&limit=8`); setItems(r.items||[]) }
      catch{ setItems([]) }
      finally{ setLoading(false) }
    },220)
    return()=>clearTimeout(id)
  },[value,open])
  const menu=open&&items.length>0&&menuStyle&&createPortal(
    <div className="origin-menu origin-menu-portal" style={menuStyle}>
      {items.map(x=><button type="button" key={`${x.code}-${x.name}`} onMouseDown={e=>e.preventDefault()} onClick={()=>{setOpen(false);setItems([]);onChange(x.name)}}><b>{x.name}</b><span>{x.iso3||x.iso2||x.code}</span></button>)}
    </div>,
    document.body
  )
  return <><label className="field origin-picker"><span>{locale==='zh'?'原产地':'Origin'}</span><input ref={inputRef} value={value||''} onFocus={()=>setOpen(true)} onBlur={()=>setTimeout(()=>setOpen(false),120)} onChange={e=>{setOpen(true);onChange(e.target.value)}} autoComplete="off" />{loading&&open&&<small>{locale==='zh'?'搜索中…':'Searching…'}</small>}</label>{menu}</>
}

function HsCodePicker({value,onChange}){
  const {locale}=useI18n()
  const [items,setItems]=useState([])
  const [loading,setLoading]=useState(false)
  const [open,setOpen]=useState(false)
  const inputRef=useRef(null)
  const menuStyle=useAnchoredOverlay(inputRef,open&&items.length>0)
  useEffect(()=>{
    if(!open){setItems([]);return}
    const q=String(value||'').trim()
    if(!q){setItems([]);return}
    const id=setTimeout(async()=>{
      setLoading(true)
      try{const r=await api(`/api/hs/search?q=${encodeURIComponent(q)}&limit=12`);setItems(r.items||[])}
      catch{setItems([])}finally{setLoading(false)}
    },180)
    return()=>clearTimeout(id)
  },[value,open])
  const menu=open&&items.length>0&&menuStyle&&createPortal(
    <div className="hs-autocomplete-menu hs-autocomplete-portal" style={{...menuStyle,width:Math.min((menuStyle.width||0)*1.55,760)}}>
      {items.map(x=><button type="button" key={x.code} onMouseDown={e=>e.preventDefault()} onClick={()=>{setOpen(false);setItems([]);onChange(x.code)}}><strong>{x.code}</strong><span title={x.description}>{x.description}</span></button>)}
    </div>,
    document.body
  )
  return <><label className="field hs-code-picker"><span>{locale==='zh'?'确认的 HS / 海关编码':'Confirmed HS / customs code'}</span><input ref={inputRef} value={value||''} inputMode="numeric" autoComplete="off" onFocus={()=>setOpen(true)} onBlur={()=>setTimeout(()=>setOpen(false),120)} onChange={e=>{setOpen(true);onChange(e.target.value)}}/>{loading&&open&&<small>{locale==='zh'?'匹配 HS…':'Matching HS…'}</small>}</label>{menu}</>
}


export default function Setup({ dashboard, markets, onReload, onGoEbay, onGoTrade }) {
  const { t, locale } = useI18n()
  const project = dashboard?.project
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [runResult, setRunResult] = useState(null)
  const [hsLoading,setHsLoading]=useState(false)
  const [hsCandidates,setHsCandidates]=useState([])
  const [hsCandidatesOpen,setHsCandidatesOpen]=useState(false)
  const [hsRankMeta,setHsRankMeta]=useState(null)
  const [aiHsLoading,setAiHsLoading]=useState(false)
  const years = currentAnalysisYears()

  useEffect(() => {
    if (!project) { setForm(null); return }
    setForm({ title:project.title || '', description:project.description || '', origin:project.origin || '', hs_code:project.hs_code || '', markets:project.markets || [], attributes:project.attributes || {}, product_type_id:project.product_type_id || 'generic' })
    setRunResult(null); setError(''); setHsCandidates([]); setHsCandidatesOpen(false); setHsRankMeta(null)
  }, [project?.id, project?.updated_at])

  const selectedMarketObjects = useMemo(() => markets.filter(m => form?.markets?.includes(m.code)), [markets, form?.markets])

  // Readiness is derived from the current draft form, so it reacts immediately
  // while the user types/selects values. Saving is only for persistence.
  const readiness = useMemo(() => {
    if (!form) return { progress: 0, checks: {}, completed: 0, total: 4 }
    const hsClean = String(form.hs_code || '').replace(/[^0-9A-Za-z]/g, '')
    const assumptions = project?.assumptions || {}
    const checks = {
      product: Boolean(String(form.title || '').trim()),
      category: Boolean(form.attributes?.ebay_category_id || (form.product_type_id && form.product_type_id !== 'generic')),
      hs_code: hsClean.length >= 6,
      origin: Boolean(String(form.origin || '').trim()),
      markets: Boolean(form.markets?.length),
      cost_inputs: assumptions.factory_cost != null && assumptions.target_margin_rate != null,
    }
    const required = ['product', 'hs_code', 'origin', 'markets']
    const completed = required.filter(key => checks[key]).length
    return { checks, progress: completed / required.length, completed, total: required.length }
  }, [form, project?.assumptions])
  if (!project || !form) return <PageHeader title={t('setupTitle')} />

  function toggleMarket(code) {
    const current = form.markets || []
    setForm({ ...form, markets: current.includes(code) ? current.filter(x=>x!==code) : [...current, code] })
  }

  async function save() {
    setSaving(true); setError('')
    try { await api(`/api/projects/${project.id}`, { method:'PATCH', body:JSON.stringify(form) }); await onReload(project.id) }
    catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function suggestHs(){
    setHsLoading(true);setError('');setHsCandidates([]);setHsCandidatesOpen(false);setHsRankMeta(null)
    try{ const r=await api(`/api/hs/suggest?project_id=${project.id}&limit=8`); const items=r.candidates||[]; setHsCandidates(items); setHsCandidatesOpen(items.length>0); setHsRankMeta(r) }
    catch(e){setError(e.message)} finally{setHsLoading(false)}
  }

  async function suggestHsAi(){
    setAiHsLoading(true);setError('');setHsCandidates([]);setHsCandidatesOpen(false);setHsRankMeta(null)
    try{const r=await api(`/api/projects/${project.id}/ai/hs-candidates?limit=8`,{method:'POST'});const items=r.candidates||[];setHsCandidates(items);setHsCandidatesOpen(items.length>0);setHsRankMeta({ranking_model:'ai_source_research'});if(!items.length)setError(locale==='zh'?'AI 未找到可验证的 HS6 候选':'AI found no verified HS6 candidates')}
    catch(e){setError(e.message)}finally{setAiHsLoading(false)}
  }

  function useHs(item){
    if(hsRankMeta?.query_context && hsRankMeta?.ranking_model && hsRankMeta.ranking_model!=='ai_source_research'){
      api('/api/hs/feedback',{method:'POST',body:JSON.stringify({project_id:project.id,query_text:hsRankMeta.query_context,selected_code:item.code,candidate_codes:hsCandidates.map(x=>x.code)})}).catch(()=>{})
    }
    setForm({...form,hs_code:item.code}); setHsCandidates([]); setHsCandidatesOpen(false); setHsRankMeta(null)
  }

  async function run() {
    setRunning(true); setError(''); setRunResult(null)
    try {
      await api(`/api/projects/${project.id}`, { method:'PATCH', body:JSON.stringify(form) })
      const result = await api(`/api/projects/${project.id}/run-analysis?start_year=${years.start}&end_year=${years.end}`, { method:'POST' })
      setRunResult(result); await onReload(project.id); onGoTrade?.()
    } catch(e) { setError(e.message) }
    finally { setRunning(false) }
  }

  const ebayAspects = form.attributes?.ebay_aspects || {}

  return <div className="page-stack">
    <PageHeader title={t('setupTitle')} actions={<><Button icon={Save} loading={saving} onClick={save}>{locale==='zh'?'保存':'Save'}</Button><Button icon={Play} variant="primary" loading={running} disabled={String(form.hs_code||'').replace(/[^0-9A-Za-z]/g,'').length < 6 || !String(form.origin||'').trim() || !form.markets.length} onClick={run}>{locale==='zh'?'运行分析':'Run analysis'}</Button></>} />
    <ErrorBanner error={error}/>

    <div className="setup-layout">
      <div className="setup-main">
        <Card><CardHeader title={locale==='zh'?'商品':'Product'} />
          <div className="form-grid two"><Field label={locale==='zh'?'商品名称':'Product name'} value={form.title} onChange={v=>setForm({...form,title:v})}/><OriginPicker value={form.origin} onChange={v=>setForm({...form,origin:v})}/></div>
          <div className="form-pad"><TextArea label={locale==='zh'?'商品说明 / 备注':'Description / notes'} value={form.description} onChange={v=>setForm({...form,description:v})} /></div>
        </Card>

        <Card className="classification-card"><CardHeader title={locale==='zh'?'商品分类与 HS':'Classification'} actions={<><Button icon={Search} variant="secondary" loading={hsLoading} onClick={suggestHs}>{locale==='zh'?'查找 HS6':'Find HS6'}</Button><Button icon={WandSparkles} variant="secondary" loading={aiHsLoading} onClick={suggestHsAi}>{locale==='zh'?'AI 查找 HS6':'AI find HS6'}</Button><Button icon={Tags} variant="secondary" onClick={onGoEbay}>{form.attributes?.ebay_category_id?(locale==='zh'?'修改 eBay 分类':'Change eBay category'):(locale==='zh'?'选择 eBay 分类':'Choose eBay category')}</Button></>} />
          <div className="classification-grid"><div><HsCodePicker value={form.hs_code} onChange={v=>{setHsCandidates([]);setHsCandidatesOpen(false);setForm({...form,hs_code:v})}}/></div><Field label={locale==='zh'?'eBay 商品分类':'eBay category'} value={form.attributes?.ebay_category_name || ''} disabled/></div>
          {hsCandidatesOpen&&hsCandidates.length>0&&<div className="hs-candidates"><div className="hs-candidates-head"><b>{locale==='zh'?'HS6 候选':'HS6 candidates'}</b>{hsRankMeta?.ranking_model&&hsRankMeta.ranking_model!=='ai_source_research'?<div className="hs-rank-method"><Badge>BM25</Badge><Badge>Embedding</Badge><Badge tone={hsRankMeta.ranking_model==='pairwise_logistic_ltr'?'success':'neutral'}>Learning-to-Rank</Badge>{hsRankMeta.feedback_count>0?<span>{locale==='zh'?`${hsRankMeta.feedback_count} 条确认反馈`:`${hsRankMeta.feedback_count} confirmations`}</span>:null}</div>:null}</div>{hsCandidates.map(x=><button type="button" key={x.code} onClick={()=>useHs(x)}><div><strong>{x.code}</strong><span>{x.description}</span>{x.score_breakdown?<small className="hs-score-breakdown">BM25 {Math.round((x.score_breakdown.bm25||0)*100)} · Emb {Math.round((x.score_breakdown.embedding||0)*100)} · Coverage {Math.round((x.score_breakdown.token_coverage||0)*100)}{(x.score_breakdown.negation_conflict||0)>0?` · ${locale==='zh'?'冲突':'Conflict'} ${Math.round(x.score_breakdown.negation_conflict*100)}`:''}</small>:null}</div><Badge tone={x.relative_confidence>=.75?'success':x.relative_confidence>=.45?'warning':'neutral'}>{Math.round((x.relative_confidence||0)*100)}% {locale==='zh'?'相对匹配':'relative match'}</Badge></button>)}</div>}
          {form.attributes?.ebay_category_path?.length ? <div className="path-line">{form.attributes.ebay_category_path.join(' / ')}</div> : null}
          {Object.keys(ebayAspects).length>0 && <div className="aspect-summary">{Object.entries(ebayAspects).map(([k,v])=><div key={k}><span>{k}</span><b>{String(v)}</b></div>)}</div>}
        </Card>

        <Card><CardHeader title={t('targetMarkets')} meta={`${form.markets.length} ${t('selected')}`} />
          <WorldMarketPicker markets={markets} selected={form.markets} onToggle={toggleMarket}/>
        </Card>
      </div>

      <aside className="setup-side">
        <Card><CardHeader title={locale==='zh'?'设置完整度':'Setup readiness'} meta={locale==='zh'?`${readiness.completed}/${readiness.total} 项必填已完成`:`${readiness.completed}/${readiness.total} required`} /><div className="readiness-score"><strong>{Math.round((readiness.progress || 0)*100)}%</strong><ProgressBar value={readiness.progress || 0}/></div>
          <div className="status-list"><StatusLine ok={readiness.checks?.product} label={locale==='zh'?'商品':'Product'}/><StatusLine ok={readiness.checks?.hs_code} label={locale==='zh'?'HS 编码':'HS code'}/><StatusLine ok={readiness.checks?.origin} label={locale==='zh'?'原产地':'Origin'}/><StatusLine ok={readiness.checks?.markets} label={locale==='zh'?'目标市场':'Target markets'}/><StatusLine ok={readiness.checks?.category} label={locale==='zh'?'Marketplace 分类':'Marketplace category'}/><StatusLine ok={readiness.checks?.cost_inputs} label={locale==='zh'?'成本输入':'Cost inputs'}/></div>
        </Card>
        <Card><CardHeader title={locale==='zh'?'已选市场':'Selected markets'} />{selectedMarketObjects.length ? <div className="simple-list">{selectedMarketObjects.map(m=><div key={m.code}><b>{FLAGS[m.code]} {locale==='zh'?(m.label_zh||m.label):m.label}</b><span>{m.currency}</span></div>)}</div> : <div className="muted-pad">—</div>}</Card>
        {runResult && <Card><CardHeader title={locale==='zh'?'最近一次分析':'Last run'} /><div className="run-summary"><Badge tone={runResult.failed ? 'warning':'success'}>{runResult.succeeded} {locale==='zh'?'成功':'succeeded'}</Badge><span>{runResult.failed} {locale==='zh'?'失败':'failed'}</span><span>{(runResult.duration_ms/1000).toFixed(1)}s</span></div><Button variant="secondary" onClick={onGoTrade}>{locale==='zh'?'查看结果':'Open results'}</Button></Card>}
      </aside>
    </div>
  </div>
}
