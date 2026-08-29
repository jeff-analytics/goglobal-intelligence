const CONFIGURED_BASE = String(import.meta.env.VITE_API_BASE || '').trim().replace(/\/+$/, '')
const BASE = import.meta.env.DEV ? '' : CONFIGURED_BASE

function formatDetail(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const path = Array.isArray(item.loc) ? item.loc.filter(x => x !== 'body').join('.') : ''
      return `${path ? `${path}: ` : ''}${item.msg || 'Invalid value'}`
    }).join(' · ')
  }
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return ''
}

function wait(ms) { return new Promise(resolve => setTimeout(resolve, ms)) }

async function fetchApi(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase()
  const attempts = method === 'GET' ? 8 : 1
  let lastError
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await fetch(`${BASE}${path}`, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
      })
    } catch (error) {
      lastError = error
      if (attempt + 1 >= attempts) break
      await wait(Math.min(1200, 300 + 200 * attempt))
    }
  }
  const error = new Error('Backend connection unavailable')
  error.cause = lastError
  throw error
}

export async function api(path, options = {}) {
  const response = await fetchApi(path, options)
  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '')

  if (!response.ok) {
    const detail = payload?.detail ?? payload
    const message = formatDetail(detail) || `HTTP ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.payload = payload
    throw error
  }
  return payload
}

export function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function downloadCsv(filename, rows) {
  if (!rows?.length) return
  const keys = [...new Set(rows.flatMap(row => Object.keys(row)))]
  const escape = (value) => {
    if (value == null) return ''
    const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
  }
  const csv = [keys.join(','), ...rows.map(row => keys.map(k => escape(row[k])).join(','))].join('\n')
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export async function apiUpload(path, formData) {
  const response = await fetch(`${BASE}${path}`, { method:'POST', body:formData })
  const payload = await response.json().catch(()=>null)
  if(!response.ok){ const detail=payload?.detail??payload; const error=new Error(formatDetail(detail)||`HTTP ${response.status}`); error.status=response.status; error.payload=payload; throw error }
  return payload
}

export async function downloadFile(path, filename) {
  const response=await fetch(`${BASE}${path}`)
  if(!response.ok){const payload=await response.json().catch(()=>null);throw new Error(formatDetail(payload?.detail??payload)||`HTTP ${response.status}`)}
  const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename||'download';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url)
}
