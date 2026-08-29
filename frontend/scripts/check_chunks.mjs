import fs from 'node:fs'
import path from 'node:path'

const dist = path.resolve('dist', 'assets')
const limit = 500 * 1024
if (!fs.existsSync(dist)) {
  console.error('[chunk-check] dist/assets not found')
  process.exit(1)
}
const js = fs.readdirSync(dist).filter(name => name.endsWith('.js'))
const rows = js.map(name => ({ name, bytes: fs.statSync(path.join(dist, name)).size })).sort((a,b)=>b.bytes-a.bytes)
const bad = rows.filter(row => row.bytes > limit)
console.log('[chunk-check] largest JavaScript chunks:')
for (const row of rows.slice(0,8)) console.log(`  ${row.name.padEnd(42)} ${(row.bytes/1024).toFixed(1)} KB`)
if (bad.length) {
  console.error(`[chunk-check] ${bad.length} chunk(s) exceed 500 KB. Build rejected.`)
  process.exit(1)
}
console.log('[chunk-check] OK: every JavaScript chunk is <= 500 KB.')
