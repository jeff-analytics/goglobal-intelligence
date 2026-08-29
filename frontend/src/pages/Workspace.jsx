import React, { useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, ChevronRight, Package, Plus, Search, Tags } from 'lucide-react'
import { api } from '../api'
import { Badge, Button, Card, Empty, ErrorBanner, PageHeader } from '../components/Common'
import { useI18n } from '../i18n.jsx'


const CACHE_TTL=30*24*60*60*1000
function readTaxCache(kind,key){try{const raw=localStorage.getItem(`bm_taxonomy_${kind}_${key}`);if(!raw)return null;const row=JSON.parse(raw);if(Date.now()-Number(row.ts||0)>CACHE_TTL)return null;return row.data||null}catch{return null}}
function writeTaxCache(kind,key,data){try{localStorage.setItem(`bm_taxonomy_${kind}_${key}`,JSON.stringify({ts:Date.now(),data}))}catch{}}

function aspectPriority(a){
  if(a.required) return 0
  if(String(a.usage || '').toUpperCase().includes('RECOMMENDED')) return 1
  return 2
}

export default function Workspace({ projects, markets, onOpen, onCreated, onGoEbay }) {
  const { t, locale } = useI18n()
  const ebayMarkets = useMemo(() => markets.filter(m => m.ebay), [markets])
  const [productText, setProductText] = useState('')
  const [projectFilter, setProjectFilter] = useState('')
  const [marketplace, setMarketplace] = useState(ebayMarkets[0]?.ebay || '')
  const [step, setStep] = useState(1)
  const [suggestions, setSuggestions] = useState([])
  const [selected, setSelected] = useState(null)
  const [aspects, setAspects] = useState([])
  const [answers, setAnswers] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const filtered = useMemo(() => projects.filter(p => !projectFilter || p.title.toLowerCase().includes(projectFilter.toLowerCase())), [projects, projectFilter])
  const keyAspects = useMemo(() => [...aspects].sort((a,b)=>aspectPriority(a)-aspectPriority(b)).slice(0,6), [aspects])

  async function findCategories(){
    const q=productText.trim(); if(q.length<2) return
    setLoading(true); setError(''); setSelected(null); setAspects([]); setAnswers({})
    try{
      if(!marketplace){ setSuggestions([]); setStep(2); return }
      const cacheKey=`${marketplace}::${q.toLowerCase()}`
      const cached=readTaxCache('suggest',cacheKey)
      if(cached){setSuggestions(cached);setStep(2);return}
      const r=await api(`/api/ebay/taxonomy/suggest?marketplace=${encodeURIComponent(marketplace)}&q=${encodeURIComponent(q)}&limit=8`)
      const result=r.suggestions||[];writeTaxCache('suggest',cacheKey,result);setSuggestions(result)
      setStep(2)
    }catch(e){ setError(e.message) }
    finally{ setLoading(false) }
  }

  async function chooseCategory(cat){
    setSelected(cat); setLoading(true); setError(''); setAnswers({})
    try{
      const cacheKey=`${marketplace}::${cat.category_id}`
      const cached=readTaxCache('aspects',cacheKey)
      if(cached){setAspects(cached);setStep(3);return}
      const r=await api(`/api/ebay/taxonomy/aspects?marketplace=${encodeURIComponent(marketplace)}&category_id=${encodeURIComponent(cat.category_id)}`)
      const result=r.aspects||[];writeTaxCache('aspects',cacheKey,result);setAspects(result)
      setStep(3)
    }catch(e){ setAspects([]); setStep(3); setError(e.message) }
    finally{ setLoading(false) }
  }

  function setAspect(name,value){ setAnswers(prev=>({ ...prev, [name]:value })) }

  async function createDraft(withCategory=true){
    const title=productText.trim(); if(title.length<2) return
    setLoading(true); setError('')
    try{
      const useCategory = withCategory && selected
      const market = ebayMarkets.find(m=>m.ebay===marketplace)
      const attrs = useCategory ? {
        ebay_marketplace: marketplace,
        ebay_market_code: market?.code || '',
        ebay_category_id: selected.category_id,
        ebay_category_name: selected.name,
        ebay_category_path: selected.path || [selected.name],
        ebay_aspects: Object.fromEntries(Object.entries(answers).filter(([,v])=>String(v||'').trim()!=='')),
      } : {}
      const project=await api('/api/projects',{method:'POST',body:JSON.stringify({
        product_type_id: useCategory ? `ebay:${marketplace}:${selected.category_id}` : 'generic',
        title,
        description:'',
        origin:'',
        hs_code:'',
        attributes:attrs,
        markets:[],
        assumptions:{},
        status:'draft',
      })})
      resetIntake(); onCreated(project,'setup')
    }catch(e){ setError(e.message) }
    finally{ setLoading(false) }
  }

  function resetIntake(){ setProductText(''); setStep(1); setSuggestions([]); setSelected(null); setAspects([]); setAnswers({}); setError('') }

  return <div className="page-stack">
    <PageHeader title={t('workspaceTitle')} />
    <Card className="intake-card">
      <div className="intake-head"><div><Badge tone="blue">{t('newAnalysis')}</Badge><h2>{step===1?t('whatProduct'):step===2?t('chooseCategory'):t('addAttributes')}</h2></div>{step>1&&<Button icon={ArrowLeft} variant="secondary" onClick={()=>setStep(step-1)}>{t('back')}</Button>}</div>

      {step===1&&<>
        <div className="intake-search-row"><div className="intake-search"><Search size={19}/><input autoFocus value={productText} onChange={e=>setProductText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')findCategories()}} /></div>
          {ebayMarkets.length>0&&<select className="intake-market" value={marketplace} onChange={e=>setMarketplace(e.target.value)}>{ebayMarkets.map(m=><option key={m.ebay} value={m.ebay}>{locale==='zh'?(m.label_zh||m.label):m.label}</option>)}</select>}
          <Button icon={ArrowRight} variant="primary" loading={loading} disabled={productText.trim().length<2||loading} onClick={findCategories}>{t('continue')}</Button>
        </div>
        <div className="intake-actions"><Button icon={Tags} variant="secondary" onClick={onGoEbay}>{t('browseCategories')}</Button><Button variant="ghost" disabled={productText.trim().length<2||loading} onClick={()=>createDraft(false)}>{t('createDraft')}</Button></div>
      </>}

      {step===2&&<div className="intake-stage">
        <div className="intake-query"><span>{t('product')}</span><b>{productText}</b></div>
        {suggestions.length?<div className="category-choice-list">{suggestions.map(s=><button key={s.category_id} onClick={()=>chooseCategory(s)}><div><b>{s.name}</b><small>{(s.path||[]).join(' / ')}</small></div><ChevronRight size={17}/></button>)}</div>:<Empty title={locale==='zh'?'没有返回分类建议':'No category suggestion returned'} action={<div className="empty-actions"><Button variant="primary" onClick={()=>createDraft(false)}>{locale==='zh'?'创建草稿':'Create draft'}</Button><Button variant="secondary" onClick={onGoEbay}>{locale==='zh'?'浏览分类':'Browse categories'}</Button></div>}/>} 
      </div>}

      {step===3&&<div className="intake-stage">
        <div className="selected-category-line"><div><span>{locale==='zh'?'已选分类':'Selected category'}</span><b>{selected?.name}</b><small>{(selected?.path||[]).join(' / ')}</small></div><Badge tone="success">eBay Taxonomy</Badge></div>
        {keyAspects.length?<><div className="aspect-form-grid">{keyAspects.map(a=><label className="aspect-field" key={a.name}><span>{a.name}{a.required&&<em>{locale==='zh'?'eBay 必填':'Required by eBay'}</em>}</span>{a.values?.length&&a.values.length<=40?<select value={answers[a.name]||''} onChange={e=>setAspect(a.name,e.target.value)}><option value="">{locale==='zh'?'未指定':'Not specified'}</option>{a.values.map(v=><option key={v} value={v}>{v}</option>)}</select>:<input value={answers[a.name]||''} onChange={e=>setAspect(a.name,e.target.value)} />}</label>)}</div></>:null}
        <div className="intake-footer"><Button variant="secondary" onClick={()=>createDraft(true)} loading={loading}>{t('skipDetails')}</Button><Button icon={Check} variant="primary" onClick={()=>createDraft(true)} loading={loading}>{t('createAnalysis')}</Button></div>
      </div>}
      <ErrorBanner error={error}/>
    </Card>

    <div className="section-toolbar"><div><h2>{t('projects')}</h2><span>{locale==='zh'?`${filtered.length} 个项目`:`${filtered.length} project(s)`}</span></div><div className="compact-search"><Search size={15}/><input value={projectFilter} onChange={e=>setProjectFilter(e.target.value)} placeholder={t('projectSearch')}/></div></div>
    {filtered.length?<div className="project-grid">{filtered.map(p=><button className="project-card" key={p.id} onClick={()=>onOpen(p.id)}><div className="project-icon"><Package size={20}/></div><div className="project-main"><div><h3>{p.title}</h3><Badge tone={p.status==='active'?'success':'neutral'}>{locale==='zh'?(p.status==='active'?'进行中':'草稿'):(p.status||'draft')}</Badge></div><p>{p.origin||(locale==='zh'?'待确认原产地':'Origin pending')} · {p.hs_code?`HS ${p.hs_code}`:(locale==='zh'?'待确认 HS':'HS pending')} · {p.markets?.length||0} {locale==='zh'?'个市场':'market(s)'}</p></div><ArrowRight size={17}/></button>)}</div>:<Empty title={t('projectsEmpty')}/>}
  </div>
}
