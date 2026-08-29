import React, { useEffect, useState } from 'react'
import { Calculator, Save, Undo2 } from 'lucide-react'
import { api } from '../api'
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, Field, PageHeader } from '../components/Common'
import { FLAGS, money, pct, marketName, aiRecoveredField, editableNumber } from '../utils'
import { AiRecoveryAction } from '../components/AiRecovery'
import { useI18n } from '../i18n.jsx'

function pricingCacheKey(projectId,marketCode,payload){
  if(!projectId||!marketCode)return ''
  const stable=JSON.stringify(payload||{},Object.keys(payload||{}).sort())
  let hash=0
  for(let i=0;i<stable.length;i++)hash=((hash<<5)-hash+stable.charCodeAt(i))|0
  return `bordermargin:pricing:${projectId}:${marketCode}:${Math.abs(hash)}`
}
function readPricingCache(key){
  if(!key)return {forward:null,reverse:null}
  try{return JSON.parse(localStorage.getItem(key)||'{}')||{}}catch{return {}}
}
function writePricingCache(key,patch){
  if(!key)return
  try{const current=readPricingCache(key);localStorage.setItem(key,JSON.stringify({...current,...patch,updated_at:new Date().toISOString()}))}catch{}
}

export default function CostMargin({ dashboard, markets, onReload, onProjectUpdated }) {
  const { t, locale } = useI18n()
  const project = dashboard?.project
  const snapshots = dashboard?.snapshots || []
  const [marketCode, setMarketCode] = useState(project?.markets?.[0] || '')
  const [a, setA] = useState(project?.assumptions || {})
  const [saving, setSaving] = useState(false)
  const [calculating, setCalculating] = useState(false)
  const [result, setResult] = useState(null)
  const [reverseResult,setReverseResult]=useState(null)
  const [error, setError] = useState('')
  const [taxOverride,setTaxOverride]=useState(null)

  useEffect(()=>{ setA(project?.assumptions || {}); setMarketCode(prev=>(project?.markets||[]).includes(prev)?prev:(project?.markets?.[0] || '')); setError('') },[project?.id, project?.updated_at])
  useEffect(()=>{if(!marketCode){setTaxOverride(null);return} api(`/api/data/tax/override?market=${encodeURIComponent(marketCode)}`).then(r=>setTaxOverride(r.override||null)).catch(()=>setTaxOverride(null))},[marketCode,project?.updated_at])
  const market = markets.find(m=>m.code===marketCode)
  const snap = snapshots.find(s=>s.market===marketCode)
  const sourcedDuty = snap?.tariff?.rate != null ? Number(snap.tariff.rate)/100 : null
  const overrideDuty = snap?.tariff?.override_used && sourcedDuty != null ? sourcedDuty : null
  const storedDuty = a.duty_rate != null ? Number(a.duty_rate) : null
  const dutyRate = overrideDuty ?? storedDuty ?? sourcedDuty
  const dutySource = overrideDuty != null ? (snap?.tariff?.source || (locale==='zh'?'用户覆盖':'User override')) : storedDuty != null ? (locale==='zh'?'已保存业务假设':'Saved business assumption') : sourcedDuty != null ? (snap?.tariff?.source || snap?.tariff?.tariff_type || (locale==='zh'?'已同步关税参考':'Synced tariff reference')) : locale==='zh'?'不可用':'Unavailable'
  const verifiedTaxRate=taxOverride?.rate!=null?Number(taxOverride.rate)/100:null
  const sourcedTaxRate=snap?.tax?.rate!=null?Number(snap.tax.rate)/100:null
  const taxRate=verifiedTaxRate ?? (a.tax_rate!=null?Number(a.tax_rate):null) ?? sourcedTaxRate
  const taxSource=verifiedTaxRate!=null?(locale==='zh'?'已确认市场税率':'Verified market tax override'):a.tax_rate!=null?(locale==='zh'?'已保存业务假设':'Saved business assumption'):sourcedTaxRate!=null?(snap?.tax?.source||(locale==='zh'?'有来源税务证据':'Source-backed tax evidence')):locale==='zh'?'不可用':'Unavailable'
  const benchmark=(a.market_benchmarks||{})[marketCode]||{}
  const sourcedBenchmark=dashboard?.benchmarks?.[marketCode]||null
  const effectiveBenchmark=benchmark.median!=null?benchmark:sourcedBenchmark||{}
  const aiDuty=aiRecoveredField(snap,'tariff.rate')
  const aiTax=aiRecoveredField(snap,'tax.rate')
  const aiBenchmark=benchmark.median==null && /ai/i.test(String(sourcedBenchmark?.source||''))
  const pricingFingerprint={
    factory_cost:a.factory_cost??null,packaging_cost:a.packaging_cost??null,freight_cost:a.freight_cost??null,fulfillment_cost:a.fulfillment_cost??null,
    platform_fee_rate:a.platform_fee_rate??null,target_margin_rate:a.target_margin_rate??null,duty_rate:dutyRate??null,tax_rate:taxRate??null,
    benchmark:effectiveBenchmark.median??null,currency:a.base_currency||market?.currency||'USD'
  }
  const resultCacheKey=pricingCacheKey(project?.id,marketCode,pricingFingerprint)
  useEffect(()=>{
    const cached=readPricingCache(resultCacheKey)
    setResult(cached.forward||null);setReverseResult(cached.reverse||null)
  },[resultCacheKey])

  if (!project) return <PageHeader title={t('costMargin')} />

  function numberField(key, value, percent=false){ const parsed=value===''?null:Number(value); const normalized=parsed==null||!Number.isFinite(parsed)?null:Number((percent?parsed/100:parsed).toFixed(12)); setA({...a,[key]:normalized}); setResult(null);setReverseResult(null) }
  function benchmarkField(key,value){const next=value===''?null:(key==='median'?Number(Number(value).toFixed(12)):value);setA({...a,market_benchmarks:{...(a.market_benchmarks||{}),[marketCode]:{...benchmark,[key]:next}}});setResult(null);setReverseResult(null)}
  async function save(){ setSaving(true); setError(''); try{ const updated=await api(`/api/projects/${project.id}`,{method:'PATCH',body:JSON.stringify({assumptions:a})}); onProjectUpdated?.(updated) }catch(e){setError(e.message)}finally{setSaving(false)} }
  async function calculate(){
    setCalculating(true); setError(''); setResult(null)
    try{
      if(a.factory_cost==null || a.target_margin_rate==null || a.platform_fee_rate==null) throw new Error(locale==='zh'?'请填写工厂成本、平台费率和目标利润率':'Factory cost, platform fee and target margin are required')
      if(dutyRate==null) throw new Error(locale==='zh'?'关税不可用':'Tariff is unavailable')
      if(taxRate==null) throw new Error(locale==='zh'?'进口税率不可用':'Import tax/VAT/GST is unavailable')
      const payload={ factory_cost:Number(a.factory_cost), packaging_cost:Number(a.packaging_cost||0), freight_cost:Number(a.freight_cost||0), fulfillment_cost:Number(a.fulfillment_cost||0), duty_rate:Number(dutyRate), tax_rate:Number(taxRate), platform_fee_rate:Number(a.platform_fee_rate), target_margin_rate:Number(a.target_margin_rate), listing_median:effectiveBenchmark.median==null?null:Number(effectiveBenchmark.median) }
      const next=await api('/api/pricing/calculate',{method:'POST',body:JSON.stringify(payload)});setResult(next);writePricingCache(resultCacheKey,{forward:next})
    }catch(e){setError(e.message)}finally{setCalculating(false)}
  }
  async function reverse(){
    setCalculating(true);setError('');setReverseResult(null)
    try{
      if(effectiveBenchmark.median==null)throw new Error(locale==='zh'?'市场价格基准不可用':'Market price benchmark is unavailable')
      if(a.platform_fee_rate==null || a.target_margin_rate==null)throw new Error(locale==='zh'?'请填写平台费率和目标利润率':'Platform fee and target margin are required')
      if(dutyRate==null) throw new Error(locale==='zh'?'关税不可用':'Tariff is unavailable')
      if(taxRate==null) throw new Error(locale==='zh'?'进口税率不可用':'Import tax/VAT/GST is unavailable')
      const payload={target_selling_price:Number(effectiveBenchmark.median),packaging_cost:Number(a.packaging_cost||0),freight_cost:Number(a.freight_cost||0),fulfillment_cost:Number(a.fulfillment_cost||0),duty_rate:Number(dutyRate),tax_rate:Number(taxRate),platform_fee_rate:Number(a.platform_fee_rate),target_margin_rate:Number(a.target_margin_rate),current_factory_cost:a.factory_cost==null?null:Number(a.factory_cost)}
      const next=await api('/api/pricing/reverse',{method:'POST',body:JSON.stringify(payload)});setReverseResult(next);writePricingCache(resultCacheKey,{reverse:next})
    }catch(e){setError(e.message)}finally{setCalculating(false)}
  }
  const currency=a.base_currency || market?.currency || 'USD'

  return <div className="page-stack">
    <PageHeader title={t('costMargin')} actions={<><AiRecoveryAction project={project} scope="cost" markets={marketCode?[marketCode]:[]} disabled={!marketCode} onComplete={()=>onReload(project.id)} label={locale==='zh'?'AI 补全外部数据':'AI recover external data'}/><Button icon={Save} loading={saving} onClick={save}>{locale==='zh'?'保存假设':'Save assumptions'}</Button></>} />
    <ErrorBanner error={error}/>
    <div className="cost-layout">
      <Card><CardHeader title={locale==='zh'?'业务假设':'Business assumptions'} /><div className="form-grid three">
        <Field label={locale==='zh'?'基础币种':'Base currency'} value={currency} onChange={v=>setA({...a,base_currency:v.toUpperCase()})}/>
        <Field label={locale==='zh'?'工厂成本':'Factory cost'} type="number" value={editableNumber(a.factory_cost)} onChange={v=>numberField('factory_cost',v)}/>
        <Field label={locale==='zh'?'包装成本':'Packaging'} type="number" value={editableNumber(a.packaging_cost)} onChange={v=>numberField('packaging_cost',v)}/>
        <Field label={locale==='zh'?'单件物流':'Freight / unit'} type="number" value={editableNumber(a.freight_cost)} onChange={v=>numberField('freight_cost',v)}/>
        <Field label={locale==='zh'?'单件履约成本':'Fulfillment / unit'} type="number" value={editableNumber(a.fulfillment_cost)} onChange={v=>numberField('fulfillment_cost',v)}/>
        <Field label={locale==='zh'?'平台费 %':'Platform fee %'} type="number" value={editableNumber(a.platform_fee_rate,100)} onChange={v=>numberField('platform_fee_rate',v,true)}/>
        <Field label={locale==='zh'?'目标利润率 %':'Target margin %'} type="number" value={editableNumber(a.target_margin_rate,100)} onChange={v=>numberField('target_margin_rate',v,true)}/>
        <Field label={locale==='zh'?'备用税率 %':'Fallback tax %'} type="number" value={editableNumber(a.tax_rate,100)} onChange={v=>numberField('tax_rate',v,true)} />
      </div></Card>
      <Card><CardHeader title={locale==='zh'?'市场证据与价格基准':'Market evidence & benchmark'} /><div className="market-duty"><label><span>{locale==='zh'?'市场':'Market'}</span><select value={marketCode} onChange={e=>setMarketCode(e.target.value)}>{(project.markets||[]).map(code=><option key={code} value={code}>{FLAGS[code]||''} {marketName(markets,code,locale,code)}</option>)}</select></label><div className={`duty-box ${aiDuty?'ai-filled':''}`}><span>{locale==='zh'?'关税参考':'Duty reference'}</span><strong>{dutyRate!=null?pct(dutyRate):locale==='zh'?'不可用':'Unavailable'}</strong><small>{dutySource}</small></div><div className={`duty-box ${aiTax?'ai-filled':''}`}><span>{locale==='zh'?'税率参考':'Tax reference'}</span><strong>{taxRate!=null?pct(taxRate):locale==='zh'?'不可用':'Unavailable'}</strong><small>{taxSource}</small></div>{sourcedBenchmark?.median!=null&&benchmark.median==null?<div className={`duty-box ${aiBenchmark?'ai-filled':''}`}><span>{locale==='zh'?'研究基准':'Research benchmark'}</span><strong>{money(sourcedBenchmark.median,sourcedBenchmark.currency||market?.currency||currency)}</strong><small>{sourcedBenchmark.source||'—'}</small></div>:null}</div><div className="form-grid two form-pad"><Field label={`${locale==='zh'?'已确认市场价格':'Verified market price'} (${market?.currency||currency})`} type="number" value={editableNumber(benchmark.median)} onChange={v=>benchmarkField('median',v)}/><Field label={locale==='zh'?'价格基准来源 / 备注':'Benchmark source / note'} value={benchmark.source??''} onChange={v=>benchmarkField('source',v)}/></div></Card>
    </div>

    <div className="analysis-action-row"><Button icon={Calculator} variant="primary" loading={calculating} onClick={calculate}>{locale==='zh'?'正向：所需售价':'Forward: required price'}</Button><Button icon={Undo2} variant="secondary" loading={calculating} onClick={reverse}>{locale==='zh'?'反向：可承受成本':'Reverse: allowable cost'}</Button></div>

    <div className="two-col">
      {result ? <Card><CardHeader title={locale==='zh'?'正向定价':'Forward pricing'} meta={dutyRate==null?(locale==='zh'?'未含关税 / 不完整':'Pre-duty / incomplete'):(locale==='zh'?'已包含可用关税参考':'Includes available duty reference')} /><div className="hero-number">{money(result.target_price,currency)}</div><div className="metric-grid"><div><span>{locale==='zh'?'盈亏平衡价':'Break-even'}</span><b>{money(result.break_even_price,currency)}</b></div><div><span>{locale==='zh'?'落地成本':'Landed cost'}</span><b>{money(result.landed_cost_before_platform,currency)}</b></div><div><span>{locale==='zh'?'基准价利润率':'Margin at benchmark'}</span><b>{pct(result.margin_at_listing_median)}</b></div><div><span>{locale==='zh'?'相对基准溢价':'Premium to benchmark'}</span><b>{pct(result.premium_to_listing_median)}</b></div></div></Card> : <Card><Empty title={locale==='zh'?'等待正向计算':'Forward result pending'} /></Card>}
      {reverseResult ? <Card><CardHeader title={locale==='zh'?'反向成本目标':'Reverse cost target'} meta={`${locale==='zh'?'基准价':'Benchmark'} ${money(reverseResult.target_selling_price,market?.currency||currency)}`} /><div className="hero-number">{money(reverseResult.max_factory_cost,currency)}</div><div className="metric-grid"><div><span>{locale==='zh'?'最高落地成本':'Max landed cost'}</span><b>{money(reverseResult.max_landed_cost_before_platform,currency)}</b></div><div><span>{locale==='zh'?'最高税前成本':'Max pre-duty cost'}</span><b>{money(reverseResult.max_pre_duty_operating_cost,currency)}</b></div><div><span>{locale==='zh'?'当前工厂成本':'Current factory cost'}</span><b>{money(reverseResult.current_factory_cost,currency)}</b></div><div><span>{locale==='zh'?'工厂成本空间':'Factory headroom'}</span><b className={reverseResult.factory_cost_headroom>=0?'positive':'negative'}>{money(reverseResult.factory_cost_headroom,currency)}</b></div></div></Card> : <Card><Empty title={locale==='zh'?'等待反向计算':'Reverse result pending'} /></Card>}
    </div>
  </div>
}
