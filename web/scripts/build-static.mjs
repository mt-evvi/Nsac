import { copyFile, mkdir } from 'node:fs/promises'
import { build } from 'vite'

process.env.VITE_STATIC_PRESET_ONLY = '1'
const base = process.env.SPHEREX_STATIC_BASE || '/'
if (!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(base)) throw new Error('SPHEREX_STATIC_BASE must be a leading and trailing slash path.')
await build({base, build: {outDir: 'dist-static', emptyOutDir: true}})
await mkdir('dist-static/explore', {recursive: true})
await copyFile('dist-static/index.html', 'dist-static/explore/index.html')
