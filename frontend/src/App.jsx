import React, { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import {
  BarChart3, ChevronDown, Compass, Database, Download, FileSpreadsheet, Globe2,
  Languages, Layers3, PackageSearch, Plus, Settings2, Tags, Target, ShieldCheck, Network
} from 'lucide-react'
import { api, downloadFile } from './api'
import { Badge, Button } from './components/Common'
import { AiRecoveryAction } from './components/AiRecovery'
import './styles.css'
import { useI18n } from './i18n.jsx'

const PAGE_LOADERS = {
  workspace: () => import('./pages/Workspace'),
  setup: () => import('./pages/Setup'),
  scan: () => import('./pages/MarketScan'),
  trade: () => import('./pages/TradeTariff'),
  tariffSupply: () => import('./pages/TariffSupply'),
  explorer: () => import('./pages/Explorer'),
  ebay: () => import('./pages/EbayResearch'),
  cost: () => import('./pages/CostMargin'),
  decision: () => import('./pages/Decision'),
  portfolio: () => import('./pages/Portfolio'),
  sources: () => import('./pages/DataSources'),
  backbone: () => import('./pages/DataBackbone'),
}
const Workspace = lazy(PAGE_LOADERS.workspace)
const Setup = lazy(PAGE_LOADERS.setup)
const MarketScan = lazy(PAGE_LOADERS.scan)
const TradeTariff = lazy(PAGE_LOADERS.trade)
const TariffSupply = lazy(PAGE_LOADERS.tariffSupply)
const Explorer = lazy(PAGE_LOADERS.explorer)
const EbayResearch = lazy(PAGE_LOADERS.ebay)
const CostMargin = lazy(PAGE_LOADERS.cost)
const Decision = lazy(PAGE_LOADERS.decision)
const Portfolio = lazy(PAGE_LOADERS.portfolio)
const DataSources = lazy(PAGE_LOADERS.sources)
const DataBackbone = lazy(PAGE_LOADERS.backbone)

const NAV_GROUPS = [
  {
    key: 'research',
    zh: '研究工作流',
    en: 'Research',
    items: [
      { key:'workspace', labelKey:'workspace', icon:Layers3 },
      { key:'setup', labelKey:'setup', icon:Settings2 },
      { key:'scan', labelKey:'scan', icon:Globe2 },
      { key:'explorer', labelKey:'explorer', icon:Compass },
      { key:'trade', labelKey:'trade', icon:BarChart3 },
      { key:'tariffSupply', labelKey:'tariffSupply', icon:Network },
      { key:'ebay', labelKey:'ebay', icon:Tags },
    ],
  },
  {
    key: 'decision',
    zh: '经营决策',
    en: 'Economics',
    items: [
      { key:'cost', labelKey:'cost', icon:PackageSearch },
      { key:'decision', labelKey:'decision', icon:Target },
      { key:'portfolio', labelKey:'portfolio', icon:FileSpreadsheet },
    ],
  },
  {
    key: 'system',
    zh: '数据与系统',
    en: 'Data & System',
    items: [
      { key:'backbone', labelKey:'backbone', icon:ShieldCheck },
      { key:'sources', labelKey:'sources', icon:Database },
    ],
  },
]

function PageLoader({ locale }) {
  return <div className="route-loader"><div className="route-loader-mark"><Layers3 size={20}/></div><div><b>{locale==='zh'?'加载中':'Loading'}</b></div></div>
}

export default function App(){
  const { t, locale, setLocale } = useI18n()
  const [page,setPage]=useState('workspace')
  const [projects,setProjects]=useState([])
  const [markets,setMarkets]=useState([])
  const [activeId,setActiveId]=useState(null)
  const [dashboard,setDashboard]=useState(null)
  const [loading,setLoading]=useState(true)
  const [toast,setToast]=useState(null)
  const [menuOpen,setMenuOpen]=useState(false)
  const activeProject=dashboard?.project || projects.find(p=>p.id===activeId) || null
  const activeNav = useMemo(() => NAV_GROUPS.flatMap(g=>g.items).find(i=>i.key===page), [page])

  async function loadBase(preferredId=null){
    setLoading(true)
    try{
      const [p,m]=await Promise.all([api('/api/projects'),api('/api/markets')])
      const list=p.projects||[]; setProjects(list); setMarkets(m.markets||[])
      const next=preferredId ?? activeId ?? list[0]?.id ?? null
      if(next){ setActiveId(next); setDashboard(await api(`/api/projects/${next}/dashboard`)) }
      else { setActiveId(null); setDashboard(null) }
    }catch(e){ setToast({tone:'danger',text:e.message}) }
    finally{setLoading(false)}
  }
  useEffect(()=>{loadBase()},[])

  async function openProject(id, target='setup'){
    try{ setActiveId(id); setDashboard(await api(`/api/projects/${id}/dashboard`)); setPage(target) }
    catch(e){ setToast({tone:'danger',text:e.message}) }
  }
  async function onCreated(project,target='setup'){
    setToast({tone:'success',text:locale==='zh'?`已创建 ${project.title}`:`Created ${project.title}`})
    await loadBase(project.id); setPage(target)
  }
  function onProjectUpdated(updated){
    if(!updated?.id)return
    setProjects(prev=>prev.map(p=>p.id===updated.id?updated:p))
    setActiveId(updated.id)
    setDashboard(prev=>prev&&prev.project?.id===updated.id?{...prev,project:updated}:prev)
  }
  async function exportProject(){
    if(!activeProject)return
    try{
      await downloadFile(`/api/projects/${activeProject.id}/export.xlsx`,`GoGlobal Intelligence_${activeProject.id}_${activeProject.title.replace(/[^a-z0-9]+/gi,'_')}.xlsx`)
      setToast({tone:'success',text:locale==='zh'?'分析工作簿已导出':'Excel analysis export downloaded'})
    } catch(e){setToast({tone:'danger',text:e.message})}
  }

  function renderPage(){
    const common={ dashboard, markets, onReload:loadBase, onProjectUpdated }
    if(page==='workspace') return <Workspace projects={projects} markets={markets} activeProject={activeProject} onOpen={(id)=>openProject(id,'setup')} onCreated={onCreated} onGoEbay={()=>setPage('ebay')}/>
    if(page==='setup') return <Setup {...common} onGoEbay={()=>setPage('ebay')} onGoTrade={()=>setPage('trade')}/>
    if(page==='scan') return <MarketScan {...common} onGoSetup={()=>setPage('setup')} onGoTrade={()=>setPage('trade')}/>
    if(page==='explorer') return <Explorer {...common} onGoScan={()=>setPage('scan')} onGoTrade={()=>setPage('trade')}/>
    if(page==='trade') return <TradeTariff {...common} onGoSetup={()=>setPage('setup')}/>
    if(page==='tariffSupply') return <TariffSupply {...common}/>
    if(page==='ebay') return <EbayResearch markets={markets} project={activeProject} onCreated={onCreated} onReload={loadBase} onGoSetup={()=>setPage('setup')}/>
    if(page==='cost') return <CostMargin {...common}/>
    if(page==='decision') return <Decision dashboard={dashboard} markets={markets}/>
    if(page==='portfolio') return <Portfolio projects={projects} markets={markets} onReload={loadBase} onOpen={(id)=>openProject(id,'setup')}/>
    if(page==='backbone') return <DataBackbone dashboard={dashboard} markets={markets} onReload={loadBase}/>
    if(page==='sources') return <DataSources dashboard={dashboard}/>
    return null
  }

  if(loading && !projects.length && !dashboard) return <div className="boot"><div className="boot-mark"><Layers3 size={22}/></div><div><b>GoGlobal Intelligence</b></div></div>

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Layers3 size={18}/></div><div><b>GoGlobal Intelligence</b></div></div>
      <nav className="nav-groups">
        {NAV_GROUPS.map(group=><div className="nav-group" key={group.key}>
          <div className="nav-group-title">{locale==='zh'?group.zh:group.en}</div>
          {group.items.map(item=>{const Icon=item.icon;return <button key={item.key} className={page===item.key?'active':''} onMouseEnter={()=>PAGE_LOADERS[item.key]?.()} onFocus={()=>PAGE_LOADERS[item.key]?.()} onClick={()=>setPage(item.key)}><Icon size={16}/><span>{t(item.labelKey)}</span></button>})}
        </div>)}
      </nav>
      <div className="sidebar-foot"><span>v5.4.1</span><Badge tone="neutral">{t('local')}</Badge></div>
    </aside>

    <div className="main-shell">
      <header className="topbar">
        <div className="topbar-context">
          <span className="topbar-page">{activeNav ? t(activeNav.labelKey) : ''}</span>
          <span className="topbar-separator">/</span>
          <div className="project-switcher">
            <button onClick={()=>setMenuOpen(!menuOpen)}><span>{activeProject?.title || t('noProject')}</span><ChevronDown size={14}/></button>
            {activeProject&&<Badge tone={activeProject.status==='active'?'success':'neutral'}>{locale==='zh'?(activeProject.status==='active'?'进行中':'草稿'):(activeProject.status||'draft')}</Badge>}
            {menuOpen&&<div className="project-menu">{projects.length?projects.map(p=><button key={p.id} onClick={()=>{openProject(p.id,page==='workspace'?'setup':page);setMenuOpen(false)}}><span>{p.title}</span><small>{p.hs_code?`HS ${p.hs_code}`:locale==='zh'?'HS 待确认':'HS pending'}</small></button>):<div className="menu-empty">{locale==='zh'?'暂无项目':'No projects'}</div>}</div>}
          </div>
        </div>
        <div className="top-actions">
          <label className="language-switch"><Languages size={15}/><select value={locale} onChange={e=>setLocale(e.target.value)} aria-label={t('language')}><option value="zh">{locale==='zh'?'中文':'Chinese'}</option><option value="en">{locale==='zh'?'英文':'English'}</option></select></label>
          {activeProject&&<AiRecoveryAction project={activeProject} scope="all" onComplete={()=>loadBase(activeProject.id)} label={locale==='zh'?'AI 补全商品':'AI recover product'}/>}
          {activeProject&&<Button icon={Download} variant="secondary" onClick={exportProject}>{t('exportExcel')}</Button>}
          <Button icon={Plus} variant="primary" onClick={()=>setPage('workspace')}>{t('newOpen')}</Button>
        </div>
      </header>
      <main className="content"><Suspense fallback={<PageLoader locale={locale}/>}>{renderPage()}</Suspense></main>
    </div>
    {toast&&<button className={`toast ${toast.tone||''}`} onClick={()=>setToast(null)}>{toast.text}</button>}
  </div>
}
