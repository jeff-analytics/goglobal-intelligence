import React, { useEffect, useMemo, useState } from 'react'
import { Download, FileSpreadsheet, RefreshCw, Search, Upload } from 'lucide-react'
import { api, apiUpload, downloadFile } from '../api'
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, PageHeader } from '../components/Common'
import { FLAGS, compactMoney, pct, marketName } from '../utils'
import { PortfolioAiRecoveryAction } from '../components/AiRecovery'
import { useI18n } from '../i18n.jsx'

function statusTone(status){return status==='READY_FOR_DECISION'?'success':status==='CONDITIONAL'?'warning':'neutral'}

export default function Portfolio({projects,markets=[],onReload,onOpen}){
  const { locale, t } = useI18n()
  const [file,setFile]=useState(null);const[loading,setLoading]=useState(false);const[result,setResult]=useState(null);const[error,setError]=useState('')
  const [matrix,setMatrix]=useState(null);const[matrixLoading,setMatrixLoading]=useState(false);const[query,setQuery]=useState('')
  const batches=useMemo(()=>{const m={};for(const p of projects){const b=p.attributes?.portfolio_batch_id;if(!b)continue;(m[b] ||= []).push(p)}return m},[projects])
  async function upload(){if(!file)return;setLoading(true);setError('');try{const fd=new FormData();fd.append('file',file);const r=await apiUpload('/api/portfolio/import',fd);setResult(r);await onReload();await loadMatrix()}catch(e){setError(e.message)}finally{setLoading(false)}}
  async function loadMatrix(){setMatrixLoading(true);try{setMatrix(await api('/api/portfolio/matrix'))}catch(e){setError(e.message)}finally{setMatrixLoading(false)}}
  useEffect(()=>{loadMatrix()},[projects.length])
  const matrixRows=useMemo(()=>{const q=query.trim().toLowerCase();return (matrix?.rows||[]).filter(r=>!q||String(r.sku||'').toLowerCase().includes(q)||String(r.title||'').toLowerCase().includes(q)||String(r.hs_code||'').toLowerCase().includes(q))},[matrix,query])
  return <div className="page-stack"><PageHeader title={t('portfolioTitle')} actions={<><PortfolioAiRecoveryAction onComplete={async()=>{await onReload?.();await loadMatrix()}}/><Button icon={RefreshCw} loading={matrixLoading} onClick={loadMatrix}>{locale==='zh'?'刷新矩阵':'Refresh matrix'}</Button><Button icon={Download} variant="secondary" onClick={()=>downloadFile('/api/portfolio/template.csv','BorderMargin_portfolio_template.csv')}>{locale==='zh'?'模板':'Template'}</Button></>}/><ErrorBanner error={error}/>
    <Card><CardHeader title={t('importSku')}/><div className="portfolio-upload"><label className="file-drop"><FileSpreadsheet size={24}/><div><b>{file?.name||t('chooseFile')}</b></div><input type="file" accept=".csv,.xlsx" onChange={e=>setFile(e.target.files?.[0]||null)}/></label><Button icon={Upload} variant="primary" loading={loading} disabled={!file} onClick={upload}>{t('importDrafts')}</Button></div>{result&&<div className="import-result"><Badge tone="success">{result.created_count} {t('created')}</Badge><Badge tone={result.rejected_count?'warning':'neutral'}>{result.rejected_count} {t('rejected')}</Badge><span>{t('batch')} {result.batch_id}</span>{result.rejected?.length>0&&<div className="rejected-list">{result.rejected.map(r=><div key={r.row_number}><b>{t('row')} {r.row_number}</b><span>{r.errors.join(' · ')}</span></div>)}</div>}</div>}</Card>

    <Card><CardHeader title={t('portfolioMatrix')} meta={matrix?`${matrixRows.length}/${matrix.count} · ${matrix.markets.length} ${locale==='zh'?'市场':'markets'}`:(locale==='zh'?'加载中':'Loading')} actions={matrix?.rows?.length?<div className="table-search"><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)}/></div>:null} />
      {matrixRows.length ? <div className="portfolio-matrix-wrap"><table className="portfolio-matrix"><thead><tr><th>{locale==='zh'?'商品':'Product'}</th><th>HS</th>{matrix.markets.map(m=><th key={m}>{FLAGS[m]||''} {marketName(markets,m,locale,m)}</th>)}</tr></thead><tbody>{matrixRows.map(r=><tr key={r.project_id}><td><button className="portfolio-link" onClick={()=>onOpen(r.project_id)}><b>{r.sku||r.title}</b><span>{r.sku?r.title:r.origin||''}</span></button></td><td>{r.hs_code||t('pending')}</td>{matrix.markets.map(m=>{const c=r.cells?.[m];return <td key={m}>{c?<div className="matrix-cell"><Badge tone={statusTone(c.status)}>{locale==='zh'?({'READY_FOR_DECISION':'可进入决策','CONDITIONAL':'有条件','INSUFFICIENT_EVIDENCE':'证据不足','PENDING':'待处理'}[c.status||'PENDING']||'待处理'):(c.status||'PENDING').replaceAll('_',' ')}</Badge><span>{locale==='zh'?'证据完整度':'Evidence'} {pct(c.evidence_ratio,0)}</span>{c.imports!=null&&<small>{compactMoney(c.imports,'USD')}</small>}</div>:<span className="muted-cell">{locale==='zh'?'未选择':'Not selected'}</span>}</td>})}</tr>)}</tbody></table></div> : <Empty title={t('noMatrix')} />}
    </Card>

    <Card><CardHeader title={t('portfolioBatches')} meta={locale==='zh'?`${Object.keys(batches).length} 个导入批次`:`${Object.keys(batches).length} imported batch(es)`}/>{Object.keys(batches).length?<div className="portfolio-batches">{Object.entries(batches).map(([batch,items])=><div className="portfolio-batch" key={batch}><div className="portfolio-batch-head"><b>{batch}</b><span>{items.length} {locale==='zh'?'个 SKU':'SKU'}</span></div><div className="portfolio-items">{items.map(p=><button key={p.id} onClick={()=>onOpen(p.id)}><div><b>{p.attributes?.portfolio_sku||p.title}</b><span>{p.title}</span></div><small>{p.hs_code?`HS ${p.hs_code}`:locale==='zh'?'HS 待确认':'HS pending'} · {p.markets?.length||0} {locale==='zh'?'个市场':'markets'}</small></button>)}</div></div>)}</div>:<Empty title={t('noPortfolio')} />}</Card>
  </div>
}
