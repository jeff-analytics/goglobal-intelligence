import React, { useMemo, useState } from 'react'
import { Check, Globe2, Search } from 'lucide-react'
import world from '../data/world_geo.json'
import { Badge } from './Common'
import { flagEmoji } from '../utils'
import { useI18n } from '../i18n.jsx'

const REGION_KEYS={
  'North America':'northAmerica','South America':'southAmerica','Europe':'europe','Asia':'asia','Africa':'africa','Oceania':'oceania','Other':'other'
}
const REGION_ORDER=['North America','South America','Europe','Asia','Africa','Oceania','Other']

function pathFromRing(ring,w,h){
  let d=''
  let prev=null
  ring.forEach(([lon,lat],i)=>{
    const x=(Number(lon)+180)/360*w
    const y=(90-Number(lat))/180*h
    const jump=prev && Math.abs(Number(lon)-prev[0])>170
    d += (i===0||jump?'M':'L')+`${x.toFixed(1)},${y.toFixed(1)}`
    prev=[Number(lon),Number(lat)]
  })
  return d+'Z'
}
function geometryPath(geom,w,h){
  if(!geom)return ''
  if(geom.type==='Polygon') return (geom.coordinates||[]).map(r=>pathFromRing(r,w,h)).join(' ')
  if(geom.type==='MultiPolygon') return (geom.coordinates||[]).flatMap(p=>p.map(r=>pathFromRing(r,w,h))).join(' ')
  return ''
}

export default function WorldMarketPicker({markets,selected,onToggle}){
  const {locale,t}=useI18n()
  const [region,setRegion]=useState('All')
  const [query,setQuery]=useState('')
  const byCode=useMemo(()=>Object.fromEntries(markets.map(m=>[m.code,m])),[markets])
  const filtered=useMemo(()=>markets.filter(m=>{
    if(region!=='All' && m.region!==region)return false
    const q=query.trim().toLowerCase()
    if(!q)return true
    return String(m.label||'').toLowerCase().includes(q)||String(m.label_zh||'').toLowerCase().includes(q)||String(m.code||'').toLowerCase().includes(q)
  }),[markets,region,query])
  const regionCounts=useMemo(()=>Object.fromEntries(REGION_ORDER.map(r=>[r,markets.filter(m=>m.region===r).length])),[markets])
  const selectedSet=new Set(selected||[])

  return <div className="world-market-picker">
    <div className="world-picker-head">
      <div><b>{t('globalMap')}</b></div>
      <div className="world-picker-search"><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={t('searchCountry')}/></div>
    </div>
    <div className="region-tabs">
      <button className={region==='All'?'active':''} onClick={()=>setRegion('All')}>{t('allRegions')} <span>{markets.length}</span></button>
      {REGION_ORDER.map(r=><button key={r} className={region===r?'active':''} onClick={()=>setRegion(r)}>{t(REGION_KEYS[r])} <span>{regionCounts[r]||0}</span></button>)}
    </div>
    <div className="world-map-wrap">
      <svg viewBox="0 0 1000 500" className="world-map" role="img" aria-label={t('globalMap')}>
        <rect x="0" y="0" width="1000" height="500" rx="14" className="ocean"/>
        {world.features.map(f=>{
          const code=f.properties?.code
          const m=byCode[code]
          if(!m)return null
          const active=selectedSet.has(code)
          const dim=region!=='All' && m.region!==region
          const cls=`country ${active?'selected ':''}${m.featured?'featured ':''}${dim?'dim ':''}${m.trade_supported?'trade-supported':'unsupported'}`
          return <path key={code} d={geometryPath(f.geometry,1000,500)} className={cls} onClick={()=>m.trade_supported&&onToggle(code)}><title>{locale==='zh'?(m.label_zh||m.label):m.label} · {m.featured?t('fullSupport'):t('tradeOnly')}</title></path>
        })}
      </svg>
      <div className="map-legend"><span><i className="legend-dot selected"/> {t('selected')}</span><span><i className="legend-dot featured"/> {t('fullSupport')}</span><span><i className="legend-dot trade"/> {t('tradeOnly')}</span></div>
    </div>
    <div className="country-list-head"><b>{t('regionList')}</b><span>{filtered.length} {locale==='zh'?'个国家/地区':'countries / areas'}</span></div>
    <div className="country-grid">
      {filtered.map(m=>{
        const active=selectedSet.has(m.code)
        return <button key={m.code} disabled={!m.trade_supported} className={active?'selected':''} onClick={()=>onToggle(m.code)}>
          <span className="country-name"><i>{flagEmoji(m.code)}</i><b>{locale==='zh'?(m.label_zh||m.label):m.label}</b><small>{m.code}</small></span>
          <span className="country-meta">{m.featured?<Badge tone="blue">{t('fullSupport')}</Badge>:<small>{t('tradeOnly')}</small>}{active&&<Check size={15}/>}</span>
        </button>
      })}
    </div>
  </div>
}
