import React,{useEffect,useMemo,useRef,useState} from 'react'
import {ArrowDown,ArrowUp,Network,Play,RefreshCw,Search} from 'lucide-react'
import {api} from '../api'
import {Badge,Button,Card,CardHeader,Empty,ErrorBanner,PageHeader,ProgressBar} from '../components/Common'
import {AiRecoveryAction} from '../components/AiRecovery'
import {FLAGS,compactMoney,pct,marketName} from '../utils'
import {useI18n} from '../i18n.jsx'

function rateText(v,locale){return v==null?(locale==='zh'?'缺失':'Missing'):`${Number(v).toFixed(2)}%`}
function statusTone(v){return v==='available'?'success':v==='ai_recovered'?'warning':v==='error'?'danger':v==='missing'?'warning':'neutral'}

function SupplyNetworkGraph({network,locale,markets}){
  const edges=(network?.edges||[]).slice(0,32)
  if(!edges.length)return <Empty title={locale==='zh'?'暂无可绘制的双边贸易网络':'No bilateral trade network to plot'}/>
  const supplierIds=[...new Set(edges.map(e=>e.source))].slice(0,9)
  const marketIds=[...new Set(edges.map(e=>e.target))].slice(0,10)
  const filtered=edges.filter(e=>supplierIds.includes(e.source)&&marketIds.includes(e.target))
  const sx=145,mx=755,top=34,bottom=326
  const ypos=(i,n)=>n<=1?180:top+(bottom-top)*i/(n-1)
  const sp=Object.fromEntries(supplierIds.map((id,i)=>[id,{x:sx,y:ypos(i,supplierIds.length)}]))
  const mp=Object.fromEntries(marketIds.map((id,i)=>[id,{x:mx,y:ypos(i,marketIds.length)}]))
  const supplierNames=Object.fromEntries((network?.suppliers||[]).map(x=>[x.code,x.name||x.code]))
  const maxShare=Math.max(...filtered.map(e=>Number(e.share_of_market)||0),.01)
  return <div className="trade-network-viz"><svg viewBox="0 0 900 360" role="img" aria-label={locale==='zh'?'供应网络图':'Supply network graph'}>
    {filtered.map((e,i)=>{const a=sp[e.source],b=mp[e.target];if(!a||!b)return null;const share=Number(e.share_of_market)||0;return <line key={`${e.source}-${e.target}-${i}`} x1={a.x+12} y1={a.y} x2={b.x-12} y2={b.y} className="trade-network-edge" style={{strokeWidth:1.2+5*share/maxShare,opacity:.16+.58*share/maxShare}}/>})}
    {supplierIds.map((id,i)=><g key={id} transform={`translate(${sp[id].x},${sp[id].y})`}><circle r="8" className="trade-network-node supplier"/><text x="-15" y="4" textAnchor="end">{String(supplierNames[id]||id).slice(0,24)}</text></g>)}
    {marketIds.map((id,i)=><g key={id} transform={`translate(${mp[id].x},${mp[id].y})`}><circle r="9" className="trade-network-node market"/><text x="15" y="4">{FLAGS[id]||''} {marketName(markets,id,locale,id)}</text></g>)}
  </svg></div>
}

export default function TariffSupply({dashboard,markets,onReload}){
  const {t,locale}=useI18n(); const project=dashboard?.project
  const [supply,setSupply]=useState(null); const [tariffs,setTariffs]=useState([]); const [network,setNetwork]=useState(null)
  const [scope,setScope]=useState('selected'); const [year,setYear]=useState(new Date().getFullYear()-1)
  const [loadingSupply,setLoadingSupply]=useState(false); const [loadingTariff,setLoadingTariff]=useState(false); const [networkLoading,setNetworkLoading]=useState(false)
  const [tariffFilter,setTariffFilter]=useState(''); const [tariffStatus,setTariffStatus]=useState('all'); const [tariffSort,setTariffSort]=useState('market'); const [tariffSortDir,setTariffSortDir]=useState('asc')
  const [job,setJob]=useState(null); const [error,setError]=useState(''); const timer=useRef(null)
  const originCode=job?.origin_code || supply?.origin?.code || project?.attributes?.origin_partner_code || '000'
  const marketMap=useMemo(()=>Object.fromEntries((markets||[]).map(m=>[m.code,m])),[markets])
  const selectedCodes=project?.markets||[]

  async function loadCached(){
    if(!project?.id)return
    setError('')
    try{
      const s=await api(`/api/projects/${project.id}/supply`); setSupply(s.profile||null)
      const code=s.profile?.origin?.code || project?.attributes?.origin_partner_code || '000'
      const qs=new URLSearchParams({hs:project.hs_code||'',origin_code:String(code),year:String(year),project_id:String(project.id)})
      if(scope==='selected'&&selectedCodes.length)qs.set('market_codes',selectedCodes.join(','))
      const tr=await api(`/api/tariff-matrix?${qs}`); setTariffs(tr.rows||[])
      try{const net=await api(`/api/projects/${project.id}/supply-network`);setNetwork(net)}catch(_){setNetwork(null)}
    }catch(e){setError(e.message)}
  }
  useEffect(()=>{loadCached()},[project?.id,project?.updated_at,year,scope])
  useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current)},[])

  async function syncSupply(){
    if(!project?.id)return; setLoadingSupply(true);setError('')
    try{const data=await api(`/api/projects/${project.id}/supply/sync?end_year=${year}&lookback_years=4`,{method:'POST'});setSupply(data);await loadNetwork()}
    catch(e){setError(e.message)}finally{setLoadingSupply(false)}
  }
  async function loadNetwork(){
    if(!project?.id)return
    setNetworkLoading(true)
    try{const net=await api(`/api/projects/${project.id}/supply-network`);setNetwork(net)}
    catch(e){setError(e.message)}finally{setNetworkLoading(false)}
  }
  async function refreshTariffs(code=originCode){
    if(!project?.id)return
    const qs=new URLSearchParams({hs:project.hs_code||'',origin_code:String(code||'000'),year:String(year),project_id:String(project.id)})
    if(scope==='selected'&&selectedCodes.length)qs.set('market_codes',selectedCodes.join(','))
    const tr=await api(`/api/tariff-matrix?${qs}`);setTariffs(tr.rows||[])
  }
  async function poll(jobId){
    try{
      const next=await api(`/api/tariff-matrix/jobs/${jobId}`);setJob(next)
      if(next.status==='completed'||next.status==='failed'){
        setLoadingTariff(false); await refreshTariffs(next.origin_code)
        return
      }
      timer.current=setTimeout(()=>poll(jobId),900)
    }catch(e){setError(e.message);setLoadingTariff(false)}
  }
  async function startTariffScan(){
    if(!project?.id)return;setLoadingTariff(true);setError('')
    try{const j=await api(`/api/projects/${project.id}/tariff-matrix/scan?year=${year}&scope=${scope}`,{method:'POST'});setJob(j);poll(j.job_id)}
    catch(e){setError(e.message);setLoadingTariff(false)}
  }
  if(!project)return <PageHeader title={t('tariffSupply')} />
  if(!project.hs_code)return <Card><Empty title={locale==='zh'?'HS 未配置':'HS not configured'}/></Card>

  const metrics=supply?.metrics||{}; const struct=supply?.destination_structure||{}; const corridors=supply?.target_corridors||[]
  const tariffRows=useMemo(()=>{
    const base=(scope==='selected'?tariffs.filter(x=>selectedCodes.includes(x.market)):tariffs).filter(r=>{
      const name=marketName(markets,r.market,locale,r.label)
      const q=tariffFilter.trim().toLowerCase()
      return (!q || String(r.market||'').toLowerCase().includes(q) || String(name||'').toLowerCase().includes(q)) && (tariffStatus==='all' || r.status===tariffStatus)
    })
    return [...base].sort((a,b)=>{
      let av,bv
      if(tariffSort==='rate'){av=a.rate;bv=b.rate}
      else if(tariffSort==='year'){av=a.year;bv=b.year}
      else {av=marketName(markets,a.market,locale,a.label);bv=marketName(markets,b.market,locale,b.label)}
      if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1
      const delta=typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv),locale==='zh'?'zh':'en')
      return tariffSortDir==='asc'?delta:-delta
    })
  },[tariffs,scope,selectedCodes,tariffFilter,tariffStatus,tariffSort,tariffSortDir,markets,locale])
  return <div className="page-stack tariff-supply-page">
    <PageHeader title={t('tariffSupply')} actions={<AiRecoveryAction project={project} scope="tariff" onComplete={async()=>{await onReload?.(project.id);await loadCached()}} label={locale==='zh'?'AI 补全关税与供给':'AI recover tariff & supply'}/>}/>
    <ErrorBanner error={error}/>
    <div className="tariff-supply-grid">
      <Card><CardHeader title={locale==='zh'?'原产地出口能力':'Origin export capacity'} meta={supply?.synced_at?(locale==='zh'?`同步于 ${new Date(supply.synced_at).toLocaleString()}`:`Synced ${new Date(supply.synced_at).toLocaleString()}`):(locale==='zh'?'UN Comtrade 出口数据':'UN Comtrade exports')} actions={<Button icon={RefreshCw} loading={loadingSupply} onClick={syncSupply}>{locale==='zh'?'同步供应证据':'Sync supply evidence'}</Button>}/>
        {supply?<><div className="metric-grid supply-metrics"><div><span>{locale==='zh'?'原产地':'Origin'}</span><b>{supply.origin?.name||project.origin||'—'}</b></div><div><span>{locale==='zh'?'最新出口额':'Latest exports'}</span><b>{compactMoney(metrics.latest_value,'USD')}</b></div><div><span>{locale==='zh'?'出口复合增长率':'Export CAGR'}</span><b>{pct(metrics.cagr)}</b></div><div><span>{locale==='zh'?'目的地数量':'Destinations'}</span><b>{struct.destination_count??'—'}</b></div><div><span>CR3</span><b>{pct(struct.cr3)}</b></div><div><span>HHI</span><b>{struct.hhi!=null?Number(struct.hhi).toFixed(3):'—'}</b></div></div></>:<Empty title={locale==='zh'?'无数据':'No data'}/>}</Card>

      <Card className="tariff-scan-card"><CardHeader title={locale==='zh'?'全球关税参考扫描':'Global tariff reference scan'} meta="UNCTAD TRAINS / WITS · HS6"/>
        <div className="tariff-scan-command">
          <label><span>{locale==='zh'?'参考年份':'Reference year'}</span><input type="number" min="1988" max="2100" value={year} onChange={e=>setYear(Number(e.target.value)||new Date().getFullYear()-1)}/></label>
          <label><span>{locale==='zh'?'扫描范围':'Scan scope'}</span><select value={scope} onChange={e=>setScope(e.target.value)}><option value="selected">{locale==='zh'?`已选市场 ${selectedCodes.length}`:`Selected markets ${selectedCodes.length}`}</option><option value="global">{locale==='zh'?'全球可用市场':'Global supported markets'}</option></select></label>
          <div className="tariff-scan-stat"><span>{locale==='zh'?'当前矩阵':'Current matrix'}</span><b>{tariffRows.length}</b><small>{locale==='zh'?'条市场记录':'market rows'}</small></div>
          <Button icon={Play} variant="primary" loading={loadingTariff} onClick={startTariffScan}>{locale==='zh'?'开始扫描':'Start scan'}</Button>
        </div>
        <div className="tariff-scan-statusbar">
          <div className="tariff-scan-source"><Network size={16}/><div><b>{job?(locale==='zh'?({queued:'排队中',running:'扫描中',completed:'已完成',failed:'失败'}[job.status]||job.status):job.status):(locale==='zh'?'准备就绪':'Ready')}</b><span>{job?.current_market?(locale==='zh'?`正在处理 ${marketMap[job.current_market]?.label_zh||marketMap[job.current_market]?.label||job.current_market}`:`Processing ${marketMap[job.current_market]?.label||job.current_market}`):(locale==='zh'?'HS6 参考税率矩阵':'HS6 reference tariff matrix')}</span></div></div>
          <div className="tariff-scan-progress"><div><span>{locale==='zh'?'进度':'Progress'}</span><b>{job?.total?`${job.done||0}/${job.total}`:'—'}</b></div><ProgressBar value={job?.total?(job.done||0)/job.total:0}/></div>
        </div>
      </Card>
    </div>

    <Card><CardHeader title={locale==='zh'?'目标市场供给通道':'Target-market supply corridors'}/>{corridors.length?<div className="data-table corridor-table"><div className="tr th"><span>{locale==='zh'?'市场':'Market'}</span><span>{locale==='zh'?'出口额':'Exports'}</span><span>{locale==='zh'?'占原产国出口':'Share of origin exports'}</span><span>{locale==='zh'?'目的地排名':'Destination rank'}</span><span>{locale==='zh'?'观测状态':'Observed'}</span></div>{corridors.map(r=><div className="tr" key={r.market}><b>{FLAGS[r.market]||''} {marketName(markets,r.market,locale,r.label)}</b><span>{compactMoney(r.trade_value,'USD')}</span><span>{pct(r.share)}</span><span>{r.rank??'—'}</span><span><Badge tone={r.observed?'success':'neutral'}>{r.observed?(locale==='zh'?'有观测':'Observed'):(locale==='zh'?'未观测':'Not observed')}</Badge></span></div>)}</div>:<Empty title={locale==='zh'?'无数据':'No data'}/>}</Card>

    <Card className="supply-network-card"><CardHeader title={locale==='zh'?'全球供应网络风险':'Global supply network risk'} meta={network?.summary?.edges?`${network.summary.nodes} nodes · ${network.summary.edges} edges`:null} actions={<Button variant="secondary" icon={RefreshCw} loading={networkLoading} onClick={loadNetwork}>{locale==='zh'?'刷新网络':'Refresh network'}</Button>}/>
      {network?.summary?.edges?<><div className="metric-grid network-kpis"><div><span>{locale==='zh'?'观测供应商':'Observed suppliers'}</span><b>{network.summary.suppliers}</b></div><div><span>{locale==='zh'?'目标市场':'Target markets'}</span><b>{network.summary.markets}</b></div><div><span>{locale==='zh'?'双边贸易边':'Bilateral edges'}</span><b>{network.summary.edges}</b></div><div><span>{locale==='zh'?'观测贸易额':'Observed trade'}</span><b>{compactMoney(network.summary.observed_trade,'USD')}</b></div></div>
        <div className="supply-network-layout"><SupplyNetworkGraph network={network} locale={locale} markets={markets}/><div className="network-risk-panel"><h4>{locale==='zh'?'市场结构脆弱度':'Market structural vulnerability'}</h4>{(network.markets||[]).slice(0,8).map(r=><div className="network-risk-row" key={r.market}><div><b>{FLAGS[r.market]||''} {marketName(markets,r.market,locale,r.market)}</b><span>{locale==='zh'?`${r.supplier_count} 个供应商 · Top1 ${pct(r.top1_share)} · HHI ${Number(r.hhi||0).toFixed(3)}`:`${r.supplier_count} suppliers · Top1 ${pct(r.top1_share)} · HHI ${Number(r.hhi||0).toFixed(3)}`}</span></div><strong>{pct(r.structural_risk)}</strong><div className="network-risk-bar"><i style={{width:`${Math.min(100,Math.max(0,(r.structural_risk||0)*100))}%`}}/></div></div>)}</div></div>
        <div className="network-bottom-grid"><div><h4>{locale==='zh'?'关键供应节点':'Critical supplier nodes'}</h4><div className="network-supplier-list">{(network.suppliers||[]).slice(0,8).map((s,i)=><div key={s.code}><span>{i+1}</span><b>{s.name}</b><small>{locale==='zh'?`覆盖 ${s.market_reach} 个市场`:`Reach ${s.market_reach} markets`}</small><strong>{pct(s.global_share)}</strong><em>BC {Number(s.betweenness||0).toFixed(3)}</em></div>)}</div></div><div><h4>{locale==='zh'?'供应商移除压力测试':'Supplier-removal stress test'}</h4><div className="network-stress-list">{(network.stress_curve||[]).slice(0,8).map(r=><div key={r.removed_suppliers}><span>Top {r.removed_suppliers}</span><div><i style={{width:`${Math.max(0,Math.min(100,(r.remaining_observed_trade_share||0)*100))}%`}}/></div><b>{pct(r.remaining_observed_trade_share)}</b></div>)}</div></div></div>
      </>:<Empty title={locale==='zh'?'先同步多个目标市场的贸易与供给数据':'Sync trade and supply data for multiple target markets first'}/>}</Card>

    <Card><CardHeader title={locale==='zh'?'关税参考矩阵':'Tariff reference matrix'} meta={`${tariffRows.length}`} />
      <div className="research-toolbar tariff-filterbar"><div className="table-search"><Search size={15}/><input value={tariffFilter} onChange={e=>setTariffFilter(e.target.value)}/></div><label><span>{locale==='zh'?'状态':'Status'}</span><select value={tariffStatus} onChange={e=>setTariffStatus(e.target.value)}><option value="all">{locale==='zh'?'全部':'All'}</option><option value="available">{locale==='zh'?'可用':'Available'}</option><option value="ai_recovered">AI</option><option value="missing">{locale==='zh'?'缺失':'Missing'}</option><option value="error">{locale==='zh'?'错误':'Error'}</option><option value="unsupported">{locale==='zh'?'未支持':'Unsupported'}</option></select></label><label><span>{locale==='zh'?'排序':'Sort'}</span><select value={tariffSort} onChange={e=>setTariffSort(e.target.value)}><option value="market">{locale==='zh'?'市场':'Market'}</option><option value="rate">{locale==='zh'?'税率':'Rate'}</option><option value="year">{locale==='zh'?'年份':'Year'}</option></select></label><Button variant="secondary" icon={tariffSortDir==='asc'?ArrowUp:ArrowDown} onClick={()=>setTariffSortDir(x=>x==='asc'?'desc':'asc')}>{tariffSortDir==='asc'?(locale==='zh'?'升序':'Asc'):(locale==='zh'?'降序':'Desc')}</Button></div>
      {tariffRows.length?<div className="data-table tariff-matrix-table"><div className="tr th"><span>{locale==='zh'?'市场':'Market'}</span><span>{locale==='zh'?'参考税率':'Reference rate'}</span><span>{locale==='zh'?'数据年份':'Data year'}</span><span>{locale==='zh'?'类型':'Type'}</span><span>{locale==='zh'?'状态':'Status'}</span><span>{locale==='zh'?'更新时间':'Cached'}</span></div>{tariffRows.map(r=><div className="tr" key={`${r.market}-${r.requested_year}`}><b>{FLAGS[r.market]||''} {marketName(markets,r.market,locale,r.label)}</b><strong className={r.status==='ai_recovered'?'ai-filled-inline':''}>{rateText(r.rate,locale)}</strong><span>{r.year||'—'}{r.fallback_used?<small> · {locale==='zh'?'回退年份':'fallback'}</small>:null}</span><span>{r.tariff_type||'—'}</span><span><Badge tone={statusTone(r.status)}>{locale==='zh'?({available:'可用',ai_recovered:'AI 补全',missing:'缺失',error:'错误',unsupported:'未支持'}[r.status]||r.status):r.status}</Badge></span><span>{r.scanned_at?new Date(r.scanned_at).toLocaleString():'—'}</span></div>)}</div>:<Empty title={locale==='zh'?'无数据':'No data'}/>}</Card>

    {struct.destinations?.length>0&&<Card><CardHeader title={locale==='zh'?'出口目的地结构':'Export destination structure'} meta={`${supply.origin?.name||project.origin||''} · HS ${supply.hs6}`}/><div className="supplier-list destination-list">{struct.destinations.slice(0,15).map((x,i)=><div key={x.partner_code}><span>{i+1}</span><b>{x.partner_name}</b><strong>{compactMoney(x.trade_value,'USD')}</strong><em>{pct(x.share)}</em></div>)}</div></Card>}
  </div>
}
