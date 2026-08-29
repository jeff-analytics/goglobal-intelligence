import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, CheckCircle2, ChevronRight, Loader2, PackagePlus, RefreshCw, Search, Tags, Upload } from 'lucide-react'
import { api, apiUpload } from '../api'
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, PageHeader } from '../components/Common'
import { AiRecoveryAction } from '../components/AiRecovery'
import { FLAGS, money, pct } from '../utils'
import { useI18n } from '../i18n.jsx'

const SORTS = [
  { value:'', label:'Best match' },
  { value:'price', label:'Price low to high' },
  { value:'-price', label:'Price high to low' },
  { value:'newlyListed', label:'Newly listed' },
]

// Module-level cache survives page navigation inside the SPA. The backend also keeps a
// disk copy of the full eBay taxonomy, so returning to this page should be immediate.
const TOP_CACHE = new Map()
const CHILD_CACHE = new Map()
const ASPECT_CACHE = new Map()
const SUGGESTION_CACHE = new Map()
const cacheKey = (...parts) => parts.map(x=>String(x ?? '')).join('::')

const BROWSER_CACHE_TTL=30*24*60*60*1000
function readBrowserCache(kind,key){
  try{const raw=localStorage.getItem(`bm_taxonomy_${kind}_${key}`);if(!raw)return null;const row=JSON.parse(raw);if(Date.now()-Number(row.ts||0)>BROWSER_CACHE_TTL){localStorage.removeItem(`bm_taxonomy_${kind}_${key}`);return null}return row.data||null}catch{return null}
}
function writeBrowserCache(kind,key,data){try{localStorage.setItem(`bm_taxonomy_${kind}_${key}`,JSON.stringify({ts:Date.now(),data}))}catch{}}

export default function EbayResearch({ markets, project, onCreated, onReload, onGoSetup }) {
  const { t, locale } = useI18n()
  const ebayMarkets = useMemo(()=>markets.filter(m=>m.ebay),[markets])
  const defaultMarketplace = project?.attributes?.ebay_marketplace || localStorage.getItem('bm_last_ebay_marketplace') || ebayMarkets[0]?.ebay || ''
  const [marketplace, setMarketplace] = useState(defaultMarketplace)
  const [top, setTop] = useState([])
  const [rows, setRows] = useState([])
  const [crumbs, setCrumbs] = useState([])
  const [categoryQuery, setCategoryQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [selected, setSelected] = useState(null)
  const [aspects, setAspects] = useState([])
  const [loadingTree, setLoadingTree] = useState(false)
  const [treeBrowseStarted,setTreeBrowseStarted]=useState(false)
  const [loadingAspects, setLoadingAspects] = useState(false)
  const [navigatingId, setNavigatingId] = useState('')
  const [categoryError, setCategoryError] = useState('')
  const [listingQuery, setListingQuery] = useState(project?.title || '')
  const [excluded,setExcluded]=useState('')
  const [sort, setSort] = useState('')
  const [limit, setLimit] = useState(25)
  const [offset, setOffset] = useState(0)
  const [listings, setListings] = useState(null)
  const [loadingListings, setLoadingListings] = useState(false)
  const [listingError, setListingError] = useState('')
  const [saving, setSaving] = useState(false)
  const [uploadFile,setUploadFile]=useState(null)
  const [uploadVerified,setUploadVerified]=useState(false)
  const [uploading,setUploading]=useState(false)
  const [uploadResult,setUploadResult]=useState(null)
  const [aiBenchmark,setAiBenchmark]=useState(null)
  const requestSeq = useRef(0)
  const aspectSeq = useRef(0)
  const market = ebayMarkets.find(m=>m.ebay===marketplace)

  function categoryErrorText(error){
    const message=String(error?.message||error||'')
    if(message.includes('eBay credentials are not loaded')||message.includes('EBAY_CLIENT_ID')||message.includes('EBAY_CLIENT_SECRET')){
      return locale==='zh'?'eBay API 未配置':'eBay API not configured'
    }
    if(message.includes('invalid_client')||message.includes('401')){
      return locale==='zh'?'eBay OAuth 验证失败':'eBay OAuth failed'
    }
    return message
  }

  useEffect(()=>{
    if(marketplace) localStorage.setItem('bm_last_ebay_marketplace', marketplace)
    const seq = ++requestSeq.current
    const mp = marketplace
    setSelected(null)
    setAspects([])
    setSuggestions([])
    setCrumbs([])
    setOffset(0)
    setListings(null)
    setUploadResult(null)
    setNavigatingId('')
    setCategoryError('')
    const cached = TOP_CACHE.get(marketplace) || readBrowserCache('top',marketplace)
    if(cached){
      TOP_CACHE.set(marketplace,cached)
      setTop(cached)
      setRows(cached)
      setTreeBrowseStarted(true)
      setLoadingTree(false)
    }else{
      setTop([])
      setRows([])
      setTreeBrowseStarted(false)
      setLoadingTree(false)
      // This call is guaranteed to be local-only on the backend. It checks the
      // disk taxonomy cache and never waits on eBay. If there is no cache, the
      // page remains search-first and the user decides when to load the tree.
      api(`/api/ebay/taxonomy/top?marketplace=${encodeURIComponent(mp)}&cached_only=true`).then(r=>{
        if(seq!==requestSeq.current) return
        const categories=r.categories||[]
        if(categories.length){TOP_CACHE.set(mp,categories);writeBrowserCache('top',mp,categories);setTop(categories);setRows(categories);setTreeBrowseStarted(true)}
      }).catch(()=>{})
    }
  },[marketplace])

  useEffect(()=>{setListingQuery(project?.title||'')},[project?.id])
  useEffect(()=>{if(!project?.id||!market?.code){setAiBenchmark(null);return}api(`/api/projects/${project.id}/dashboard`).then(d=>setAiBenchmark(d?.benchmarks?.[market.code]||null)).catch(()=>setAiBenchmark(null))},[project?.id,market?.code,project?.updated_at])

  async function loadTop(force=false, mp=marketplace, existingSeq=null) {
    if(!mp) return
    if(!force && TOP_CACHE.has(mp)){
      const cached=TOP_CACHE.get(mp)
      setTop(cached); setRows(cached); setLoadingTree(false)
      return
    }
    const seq=existingSeq ?? ++requestSeq.current
    setLoadingTree(true); setCategoryError('')
    try {
      const r=await api(`/api/ebay/taxonomy/top?marketplace=${mp}&force=${force?'true':'false'}`)
      if(seq!==requestSeq.current || mp!==marketplace) return
      const categories=r.categories||[]
      TOP_CACHE.set(mp,categories); writeBrowserCache('top',mp,categories)
      setTreeBrowseStarted(true); setTop(categories); setRows(categories); setCrumbs([]); setSelected(null); setAspects([])
    } catch(e){
      if(seq===requestSeq.current) setCategoryError(categoryErrorText(e))
    } finally{
      if(seq===requestSeq.current) setLoadingTree(false)
    }
  }

  async function searchCategories(e) {
    e?.preventDefault()
    const q=categoryQuery.trim()
    if(!q) return
    const key=cacheKey(marketplace,q.toLowerCase())
    const storedSuggestion=SUGGESTION_CACHE.get(key)||readBrowserCache('suggest',key)
    if(storedSuggestion){SUGGESTION_CACHE.set(key,storedSuggestion);setSuggestions(storedSuggestion);return}
    const seq=++requestSeq.current
    setLoadingTree(true); setCategoryError('')
    try {
      const r=await api(`/api/ebay/taxonomy/suggest?marketplace=${marketplace}&q=${encodeURIComponent(q)}&limit=15`)
      if(seq!==requestSeq.current) return
      const result=r.suggestions||[]
      SUGGESTION_CACHE.set(key,result); writeBrowserCache('suggest',key,result)
      setSuggestions(result)
    } catch(e){ if(seq===requestSeq.current) setCategoryError(categoryErrorText(e)) }
    finally{ if(seq===requestSeq.current) setLoadingTree(false) }
  }

  async function loadChildren(cat, nextCrumbs) {
    const key=cacheKey(marketplace,cat.category_id)
    setSelected(null); setAspects([]); setSuggestions([])
    const storedChildren=CHILD_CACHE.get(key)||readBrowserCache('children',key)
    if(storedChildren){
      CHILD_CACHE.set(key,storedChildren)
      setCrumbs(nextCrumbs)
      setRows(storedChildren)
      setNavigatingId('')
      return
    }
    const seq=++requestSeq.current
    setNavigatingId(cat.category_id); setCategoryError('')
    try {
      const r=await api(`/api/ebay/taxonomy/children?marketplace=${marketplace}&category_id=${encodeURIComponent(cat.category_id)}`)
      if(seq!==requestSeq.current) return
      const children=r.children||[]
      CHILD_CACHE.set(key,children); writeBrowserCache('children',key,children)
      setCrumbs(nextCrumbs); setRows(children)
    } catch(e){ if(seq===requestSeq.current) setCategoryError(categoryErrorText(e)) }
    finally{ if(seq===requestSeq.current) setNavigatingId('') }
  }

  async function openCategory(cat) {
    if(cat.leaf){ await chooseCategory(cat); return }
    const next=[...crumbs,{category_id:cat.category_id,name:cat.name}]
    await loadChildren(cat,next)
  }

  async function chooseCategory(cat) {
    const picked={ ...cat, path:cat.path || [...crumbs.map(c=>c.name), cat.name] }
    setSelected(picked)
    setSuggestions([])
    setCategoryError('')
    const key=cacheKey(marketplace,cat.category_id)
    const storedAspects=ASPECT_CACHE.get(key)||readBrowserCache('aspects',key)
    if(storedAspects){ASPECT_CACHE.set(key,storedAspects);setAspects(storedAspects);setLoadingAspects(false);return}
    const seq=++aspectSeq.current
    setLoadingAspects(true)
    try {
      const r=await api(`/api/ebay/taxonomy/aspects?marketplace=${marketplace}&category_id=${encodeURIComponent(cat.category_id)}`)
      if(seq!==aspectSeq.current) return
      const result=r.aspects||[]
      ASPECT_CACHE.set(key,result); writeBrowserCache('aspects',key,result)
      setAspects(result)
    } catch(e){ if(seq===aspectSeq.current){setCategoryError(categoryErrorText(e));setAspects([])} }
    finally{ if(seq===aspectSeq.current)setLoadingAspects(false) }
  }

  async function jump(index) {
    if(index<0){
      ++requestSeq.current
      setCrumbs([]); setRows(TOP_CACHE.get(marketplace)||top); setSelected(null); setAspects([]); setSuggestions([]); setNavigatingId('')
      return
    }
    const target=crumbs[index]
    const next=crumbs.slice(0,index+1)
    await loadChildren(target,next)
  }

  async function useCategory() {
    if(!selected) return
    setSaving(true); setCategoryError('')
    const attrs={ ebay_marketplace:marketplace, ebay_market_code:market?.code||'', ebay_category_id:selected.category_id, ebay_category_name:selected.name, ebay_category_path:selected.path || [selected.name] }
    try {
      if(project){
        await api(`/api/projects/${project.id}`, { method:'PATCH', body:JSON.stringify({ product_type_id:`ebay:${marketplace}:${selected.category_id}`, attributes:{ ...(project.attributes||{}), ...attrs } }) })
        await onReload(project.id); onGoSetup()
      } else {
        const p=await api('/api/projects', { method:'POST', body:JSON.stringify({ product_type_id:`ebay:${marketplace}:${selected.category_id}`, title:selected.name, description:'', origin:'', hs_code:'', attributes:attrs, markets:market?.code?[market.code]:[], assumptions:{}, status:'draft' }) })
        onCreated(p,'setup')
      }
    } catch(e){ setCategoryError(categoryErrorText(e)) }
    finally{ setSaving(false) }
  }

  async function searchListings(nextOffset=0) {
    if(!listingQuery.trim()) return
    setLoadingListings(true); setListingError('')
    try {
      const params=new URLSearchParams({ q:listingQuery.trim(), marketplace, limit:String(limit), offset:String(nextOffset) })
      if(sort) params.set('sort',sort)
      const cat=selected?.category_id||project?.attributes?.ebay_category_id
      if(cat)params.set('category_id',cat)
      if(excluded.trim())params.set('excluded',excluded.trim())
      if(project?.id)params.set('project_id',String(project.id))
      const r=await api(`/api/data/listings/comparables?${params.toString()}`)
      setListings(r); setOffset(nextOffset)
    } catch(e){ setListingError(e.message) }
    finally{ setLoadingListings(false) }
  }

  async function uploadObservations(){
    if(!uploadFile||!project||!market)return
    setUploading(true);setListingError('')
    try{
      const fd=new FormData();fd.append('file',uploadFile);fd.append('project_id',String(project.id));fd.append('market',market.code);fd.append('query',listingQuery||project.title);fd.append('verified_market_data',String(uploadVerified));fd.append('excluded_terms',excluded)
      const r=await apiUpload('/api/marketplace/listings/upload',fd);setUploadResult(r)
    }catch(e){setListingError(e.message)}finally{setUploading(false)}
  }

  const comp=listings?.comparable_set
  return <div className="page-stack">
    <PageHeader title={t('ebayResearch')} actions={<>{project&&market&&<AiRecoveryAction project={project} scope="marketplace" markets={[market.code]} onComplete={async()=>{await onReload?.(project.id);const d=await api(`/api/projects/${project.id}/dashboard`);setAiBenchmark(d?.benchmarks?.[market.code]||null)}} label={locale==='zh'?'AI 查找市场价格':'AI find market prices'}/>}<Badge tone="warning">{locale==='zh'?((listings?.environment||'sandbox')==='sandbox'?'沙盒':listings?.environment):(listings?.environment||'Sandbox')}</Badge></>} />
    <div className="ebay-layout">
      <div className="ebay-left"><Card>
        <CardHeader title={t('categoryTaxonomy')} meta={market ? `${FLAGS[market.code]||''} ${locale==='zh'?(market.label_zh||market.label):market.label}` : marketplace} actions={<Button icon={RefreshCw} loading={loadingTree} onClick={()=>loadTop(true)}>{t('refreshTaxonomy')}</Button>} />
        <div className="toolbar-row"><label><span>{t('marketplace')}</span><select value={marketplace} onChange={e=>setMarketplace(e.target.value)}>{ebayMarkets.map(m=><option key={m.ebay} value={m.ebay}>{locale==='zh'?(m.label_zh||m.label):m.label} · {m.ebay}</option>)}</select></label><label className="search-field"><span>{t('searchCategories')}</span><form className="search-box" onSubmit={searchCategories}><Search size={16}/><input value={categoryQuery} onChange={e=>setCategoryQuery(e.target.value)} /><button>{t('search')}</button></form></label></div>
        <ErrorBanner error={categoryError}/>
        {selected&&<div className="category-selected-banner"><div><span>{t('selectedCategory')}</span><b>{selected.name}</b><small>{(selected.path||[selected.name]).join(' / ')}</small></div><div className="category-selected-actions">{loadingAspects?<span className="category-loading"><Loader2 className="spin" size={14}/> {t('loadingAttributes')}</span>:<span className="category-ready"><CheckCircle2 size={14}/>{aspects.length} {locale==='zh'?'个属性':'attributes'}</span>}<Button icon={PackagePlus} variant="primary" loading={saving} onClick={useCategory}>{project?t('attachProject'):t('createProject')}</Button></div></div>}
        {suggestions.length ? <div className="suggestions">{suggestions.map(s=><button key={s.category_id} onClick={()=>chooseCategory(s)}><div><b>{s.name}</b><small>{(s.path||[]).join(' / ')}</small></div><ChevronRight size={16}/></button>)}</div> : null}
        <div className="crumbs"><button onClick={()=>jump(-1)}>{t('allCategories')}</button>{crumbs.map((c,i)=><React.Fragment key={c.category_id}><ChevronRight size={13}/><button onClick={()=>jump(i)}>{c.name}</button></React.Fragment>)}</div>
        {navigatingId&&<div className="category-nav-progress"><Loader2 className="spin" size={14}/> {t('openingCategory')}</div>}
        {loadingTree && !rows.length ? <div className="loading-block"><Loader2 className="spin" size={18}/> {t('loadingTaxonomy')}</div> : rows.length ? <div className="category-list">{rows.map(cat=><button key={cat.category_id} className={`${selected?.category_id===cat.category_id?'selected ':''}${navigatingId===cat.category_id?'loading':''}`} disabled={!!navigatingId} onClick={()=>openCategory(cat)}><div><b>{cat.name}</b><small>ID {cat.category_id}{cat.child_count?` · ${cat.child_count} ${locale==='zh'?'个子分类':'subcategories'}`:''}</small></div>{navigatingId===cat.category_id?<Loader2 className="spin" size={16}/>:cat.leaf?<CheckCircle2 size={16}/>:<ChevronRight size={16}/>}</button>)}</div> : !suggestions.length ? <div className="taxonomy-idle taxonomy-idle-compact"><Tags size={22}/><Button variant="secondary" onClick={()=>loadTop(false)} loading={loadingTree}>{t('browseAll')}</Button></div> : null}
        {selected&&aspects.length>0&&<div className="aspect-inline"><div className="aspect-inline-head"><b>{t('categoryAttributes')}</b><span>{aspects.length}</span></div><div className="aspect-table">{aspects.slice(0,12).map(a=><div key={a.name}><span>{a.name}</span>{a.required?<Badge tone="warning">{t('required')}</Badge>:<Badge>{t('optional')}</Badge>}<small>{a.values?.slice(0,4).join(', ')}</small></div>)}</div>{aspects.length>12&&<div className="more-row">+ {aspects.length-12} {locale==='zh'?'个更多属性':'more attributes'}</div>}</div>}
      </Card></div>
      <div className="ebay-right"><Card><CardHeader title={t('comparableResearch')} /><div className="listing-controls v4"><label><span>{t('query')}</span><input value={listingQuery} onChange={e=>setListingQuery(e.target.value)} /></label><label><span>{t('excludedTerms')}</span><input value={excluded} onChange={e=>setExcluded(e.target.value)}/></label><label><span>{t('sort')}</span><select value={sort} onChange={e=>setSort(e.target.value)}>{SORTS.map(s=><option key={s.value} value={s.value}>{locale==='zh'?(s.value===''?t('bestMatch'):s.value==='price'?t('priceLow'):s.value==='-price'?t('priceHigh'):t('newlyListed')):s.label}</option>)}</select></label><label><span>{t('pageSize')}</span><select value={limit} onChange={e=>setLimit(Number(e.target.value))}><option value={10}>10</option><option value={25}>25</option><option value={50}>50</option></select></label><Button icon={Search} variant="primary" loading={loadingListings} onClick={()=>searchListings(0)} disabled={!listingQuery.trim()}>{t('search')}</Button></div><ErrorBanner error={listingError}/>{!listings ? <Empty title={locale==='zh'?'无数据':'No data'} /> : <><div className="comparable-kpis"><div><span>{t('inputSample')}</span><b>{comp?.input_count||0}</b></div><div><span>{t('retainedSample')}</span><b>{comp?.accepted_count||0}</b></div><div><span>{t('retention')}</span><b>{pct(comp?.retention_ratio)}</b></div><div><span>{t('medianPrice')}</span><b>{listings.benchmark_allowed?money(comp?.summary?.median,listings.items?.[0]?.currency||'USD'):t('sandboxBlocked')}</b></div></div><div className="rejection-chips">{Object.entries(comp?.rejection_reasons||{}).map(([k,v])=><Badge key={k}>{k}: {v}</Badge>)}</div><div className="listing-table"><div className="tr th"><span>{t('title')}</span><span>{t('condition')}</span><span>{t('match')}</span><span>{t('price')}</span></div>{(comp?.accepted||[]).slice(0,limit).map((x,i)=><div className="tr" key={x.item_id||i}><div><b>{x.title}</b><small>{x.category_id?`${locale==='zh'?'分类':'Category'} ${x.category_id}`:''}</small></div><span>{x.condition||'—'}</span><span>{pct(x.query_overlap)}</span><strong>{x.price!=null?`${x.price} ${x.currency||''}`:'—'}</strong></div>)}</div><div className="pager"><Button icon={ArrowLeft} disabled={offset<=0||loadingListings} onClick={()=>searchListings(Math.max(0,offset-limit))}>{t('previous')}</Button><span>{offset+1}–{offset+(listings.returned||0)}</span><Button icon={ArrowRight} disabled={(listings.returned||0)<limit||loadingListings} onClick={()=>searchListings(offset+limit)}>{t('next')}</Button></div></>}</Card>
        {project&&market&&aiBenchmark?.source_backed&&<Card><CardHeader title={locale==='zh'?'公开市场证据':'Public market evidence'} meta={`${aiBenchmark.observation_count||0}`} /><div className="comparable-kpis source-backed-kpis"><div><span>{locale==='zh'?'样本':'Observations'}</span><b>{aiBenchmark.observation_count||0}</b></div><div><span>P25</span><b>{money(aiBenchmark.p25,aiBenchmark.currency||market.currency)}</b></div><div><span>{locale==='zh'?'中位价':'Median'}</span><b>{money(aiBenchmark.median,aiBenchmark.currency||market.currency)}</b></div><div><span>P75</span><b>{money(aiBenchmark.p75,aiBenchmark.currency||market.currency)}</b></div></div></Card>}
        {project&&market&&<Card><CardHeader title={locale==='zh'?'市场观测':'Market observations'}/><div className="verified-upload verified-upload-v536"><label><span>{locale==='zh'?'文件':'File'}</span><input type="file" accept=".csv,.xlsx,.xlsm" onChange={e=>setUploadFile(e.target.files?.[0]||null)}/></label><label><span>{locale==='zh'?'用途':'Usage'}</span><select value={uploadVerified?'benchmark':'store'} onChange={e=>setUploadVerified(e.target.value==='benchmark')}><option value="store">{locale==='zh'?'仅保存':'Store only'}</option><option value="benchmark">{locale==='zh'?'价格基准':'Price benchmark'}</option></select></label><Button icon={Upload} variant="secondary" loading={uploading} disabled={!uploadFile} onClick={uploadObservations}>{locale==='zh'?'导入':'Import'}</Button></div>{uploadResult&&<div className="upload-summary"><Badge tone={uploadResult.verified_market_data?'success':'neutral'}>{uploadResult.verified_market_data?(locale==='zh'?'价格基准':'Benchmark'):(locale==='zh'?'已保存':'Stored')}</Badge><span>{uploadResult.comparable_set?.accepted_count||0}</span><span>{locale==='zh'?'中位价':'Median'} {uploadResult.verified_market_data?money(uploadResult.comparable_set?.summary?.median,uploadResult.currency||market.currency):'—'}</span></div>}</Card>}
      </div>
    </div>
  </div>
}
