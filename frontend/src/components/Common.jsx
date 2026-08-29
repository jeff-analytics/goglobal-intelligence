import React from 'react'
import { AlertTriangle, CheckCircle2, Database, Loader2 } from 'lucide-react'
import { cx, localizeRuntimeMessage } from '../utils'
import { useI18n } from '../i18n.jsx'

export function Button({ children, icon: Icon, variant='default', loading=false, className='', ...props }) {
  return <button className={cx('btn', `btn-${variant}`, className)} {...props}>
    {loading ? <Loader2 size={16} className="spin" /> : Icon ? <Icon size={16} /> : null}
    <span>{children}</span>
  </button>
}

export function Badge({ children, tone='neutral' }) { return <span className={cx('badge', `badge-${tone}`)}>{children}</span> }

export function PageHeader({ title, actions }) {
  return <div className="page-header"><div><h1>{title}</h1></div>{actions && <div className="page-actions">{actions}</div>}</div>
}

export function Card({ children, className='' }) { return <section className={cx('card', className)}>{children}</section> }

export function CardHeader({ title, meta, actions }) {
  return <div className="card-header"><div><h2>{title}</h2>{meta && <span>{meta}</span>}</div>{actions && <div className="card-actions">{actions}</div>}</div>
}

export function Field({ label, value, onChange, type='text', placeholder='', disabled=false, options }) {
  return <label className="field"><span>{label}</span>
    {options ? <select value={value ?? ''} onChange={e => onChange?.(e.target.value)} disabled={disabled}>{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
      : <input type={type} value={value ?? ''} placeholder={placeholder} disabled={disabled} onChange={e => onChange?.(e.target.value)} />}
  </label>
}

export function TextArea({ label, value, onChange, placeholder='', rows=4 }) {
  return <label className="field"><span>{label}</span><textarea rows={rows} value={value ?? ''} placeholder={placeholder} onChange={e => onChange?.(e.target.value)} /></label>
}

export function Empty({ title, action }) {
  return <div className="empty"><div className="empty-icon"><Database size={20}/></div><h3>{title}</h3>{action}</div>
}

export function StatusLine({ ok, label, detail }) {
  const Icon = ok ? CheckCircle2 : AlertTriangle
  return <div className={cx('status-line', ok ? 'ok' : 'warn')}><Icon size={16}/><div><b>{label}</b>{detail && <span>{detail}</span>}</div></div>
}

export function ProgressBar({ value=0 }) { return <div className="progress"><i style={{ width:`${Math.max(0,Math.min(100,value*100))}%` }} /></div> }

export function ErrorBanner({ error }) { const {locale}=useI18n(); if (!error) return null; return <div className="error-banner"><AlertTriangle size={16}/><span>{localizeRuntimeMessage(error,locale)}</span></div> }

export function LoadingBlock({ label='Loading…' }) { return <div className="loading-block"><Loader2 className="spin" size={18}/><span>{label}</span></div> }
