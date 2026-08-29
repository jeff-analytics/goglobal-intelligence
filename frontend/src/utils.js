export function flagEmoji(code) {
  let c=String(code||'').toUpperCase()
  if(c==='UK') c='GB'
  if(!/^[A-Z]{2}$/.test(c)) return '🌐'
  return String.fromCodePoint(...[...c].map(ch=>127397+ch.charCodeAt(0)))
}
export const FLAGS = new Proxy({}, { get:(_,key)=>flagEmoji(String(key)) })

export function cx(...items) { return items.filter(Boolean).join(' ') }

export function compactMoney(value, currency = 'USD') {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency,
      notation: Math.abs(n) >= 1e6 ? 'compact' : 'standard',
      maximumFractionDigits: Math.abs(n) >= 1e6 ? 2 : 0,
    }).format(n)
  } catch {
    return `${n.toLocaleString()} ${currency}`
  }
}

export function money(value, currency = 'USD', digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  try {
    return new Intl.NumberFormat('en-US', { style:'currency', currency, maximumFractionDigits:digits }).format(Number(value))
  } catch {
    return `${Number(value).toFixed(digits)} ${currency}`
  }
}

export function pct(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(digits)}%`
}

export function editableNumber(value, scale = 1, maxFractionDigits = 8) {
  if (value == null || value === '') return ''
  const n = Number(value) * Number(scale || 1)
  if (!Number.isFinite(n)) return ''
  const digits = Math.max(0, Math.min(12, Number(maxFractionDigits) || 0))
  const rounded = Number(n.toFixed(digits))
  return String(Object.is(rounded, -0) ? 0 : rounded)
}

export function cleanHs6(value) {
  return String(value || '').replace(/[^a-zA-Z0-9]/g, '').slice(0, 6)
}

export function currentAnalysisYears() {
  const end = new Date().getFullYear() - 1
  return { start: end - 4, end }
}


export function aiRecoveredField(snapshot, field) {
  const applied = snapshot?.ai_recovery?.applied_fields || []
  if (applied.includes(field)) return true
  if (field === 'tariff.rate') return String(snapshot?.tariff?.source_type || '').includes('ai-recovered')
  if (field === 'tax.rate') return String(snapshot?.tax?.source_type || '').includes('ai-recovered')
  if (field === 'fx.rate') return String(snapshot?.fx?.source_type || '').includes('ai-recovered')
  return false
}

export function snapshotRow(code, market, snapshot) {
  const t = snapshot?.trade || {}
  const trend = t.world_metrics?.yoy ?? t.world_metrics?.cagr ?? null
  return {
    market: code,
    label: market?.label || snapshot?.market_label || code,
    currency: market?.currency || snapshot?.currency || null,
    latest_year: t.latest_year ?? null,
    imports: t.latest_total_imports ?? null,
    origin_imports: t.latest_imports_from_origin ?? null,
    origin_share: t.latest_origin_share ?? null,
    origin_name: snapshot?.origin?.name || null,
    trend,
    tariff_rate: snapshot?.tariff?.rate != null ? Number(snapshot.tariff.rate) / 100 : null,
    tariff_source: snapshot?.tariff?.source || snapshot?.tariff?.tariff_type || null,
    fx_rate: snapshot?.fx?.rate ?? null,
    coverage: snapshot?.quality?.world?.coverage_ratio ?? null,
    volatility: t.volatility ?? null,
    supplier_cr3: snapshot?.suppliers?.cr3 ?? null,
    supplier_cr5: snapshot?.suppliers?.cr5 ?? null,
    supplier_hhi: snapshot?.suppliers?.hhi ?? null,
    supplier_count: snapshot?.suppliers?.supplier_count ?? null,
    synced_at: snapshot?.synced_at ?? null,
    ai_fields: snapshot?.ai_recovery?.applied_fields || [],
    snapshot,
  }
}

export function marketName(markets, code, locale='en', fallback='') {
  const row = Array.isArray(markets) ? markets.find(m => m.code === code) : null
  if (locale === 'zh') return row?.label_zh || row?.label || fallback || code
  return row?.label || fallback || code
}


export function localizeRuntimeMessage(value, locale='en') {
  const raw = String(value || '').trim()
  if (!raw || locale !== 'zh') return raw
  const low = raw.toLowerCase()
  if (raw.includes('MODEL_INVALID_JSON') || low.includes('model response was not valid json')) return '模型返回格式异常'
  if (raw.includes('MODEL_EMPTY_RESPONSE') || low.includes('model returned no usable content')) return '模型未返回可用内容'
  if (raw.includes('MODEL_WEB_RESEARCH_INCOMPLETE') || low.includes('web research') && low.includes('incomplete')) return '联网检索未完成'
  if (raw.includes('NO_WEB_SEARCH_CAPABILITY')) return '当前模型协议不支持联网检索'
  if (raw.includes('NO_READABLE_OFFICIAL_SOURCE')) return '没有可读取的官方来源'
  if (low.includes('incomplete brief json')) return 'AI 简报返回字段不完整'
  if (raw.includes('WITS_NETWORK_PAUSED')) return 'WITS / TRAINS 实时请求已暂停'
  if (low.includes('timed out') || low.includes('timeout')) return '请求超时'
  if (low.includes('backend connection unavailable') || low.includes('failed to fetch') || low.includes('networkerror')) return '后端连接暂时不可用'
  if (low.includes('connection failed') || low.includes('connectionerror') || low.includes('name resolution')) return '无法连接数据源'
  if (low.includes('authentication failed') || low.includes('unauthorized') || low.includes('invalid api key')) return 'API 认证失败'
  if (low.includes('rate limit') || low.includes('too many requests')) return 'API 请求频率受限'
  if (low.includes('model') && (low.includes('not found') || low.includes('does not exist'))) return '模型不可用'
  return raw
}
