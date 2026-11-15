import './style.css'
import { installAnalysis } from './analysis.ts'

const staticOnly = import.meta.env.VITE_STATIC_PRESET_ONLY === '1'
const appBase = staticOnly ? import.meta.env.BASE_URL : '/'

export type Frame = {
  frameId: string; productId: string; obsId: string; slotKey: string; startUtc: string; endUtc: string
  visitId: string; surveyPass?: string | number; release: string; detector: number; archiveUrl: string
  imageUrl?: string; archiveDoi?: string; wavelengthUm?: number; bandwidthUm?: number; coverageFraction?: number; validFraction?: number
  flags?: string[]; warnings?: string[]; stretch?: number[]; representation?: string; coaddAnchor?: string
}
export type Query = { raDeg: number; decDeg: number; fovArcmin: number; start?: string; end?: string; wavelengthUm?: number; detector?: number }
export type Manifest = { seriesId: string; pipelineVersion?: string; query: Query; grid: {width: number; height: number; crpix: number[]; crval: number[]; cd: number[][]}; frames: Frame[]; count?: number; nextCursor?: string; counts: Record<string, number>; searchStatus: string }
export type Envelope<T> = { status: 'succeeded' | 'partial'; data: T; warnings: string[] }
type Job<T> = Envelope<T> | { status: 'running' | 'queued'; jobId: string; stage: string; pollAfterMs: number } | { status: 'failed'; error: { code: string; message: string } }
const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T
const input = (id: string) => el<HTMLInputElement>(id)
const select = (id: string) => el<HTMLSelectElement>(id)
const button = (id: string) => el<HTMLButtonElement>(id)
const known = new Map([
  ['barnard', { name: 'Barnard’s Star', raDeg: 269.45, decDeg: 4.768, fovArcmin: 3 }],
  ['epsilon-indi-b', { name: 'Epsilon Indi B', raDeg: 331.09656943, decDeg: -56.80083957, fovArcmin: 3 }],
  ['wise-0855', { name: 'WISE 0855', raDeg: 133.75977, decDeg: -7.24218, fovArcmin: 5 }],
  ['wise-0855-nasa', { name: 'WISE 0855 (NASA coordinates)', raDeg: 133.79512917, decDeg: -7.24514722, fovArcmin: 6 }],
  ['rw-aurigae', { name: 'RW Aurigae', raDeg: 76.95654167, decDeg: 30.40144444, fovArcmin: 3 }],
  ['r-draconis', { name: 'R Draconis', raDeg: 248.16761, decDeg: 66.75498, fovArcmin: 3 }],
])
const day = 86400000
const canvasA = el<HTMLCanvasElement>('canvas-a')
const canvasB = el<HTMLCanvasElement>('canvas-b')
const slider = input('scrubber')
let manifest: Manifest | undefined
let preset: string | undefined
let slots: Frame[][] = []
let shown: Frame | undefined
let paired: Frame | undefined
let viewMode = 'single'
let rendered: ImageBitmap | undefined
let renderedPair: ImageBitmap | undefined
let request = new AbortController()
let frameRequest = new AbortController()
let queryId = 0
let selectionId = 0
let playing = false
let timekeeper = 0
let debounce = 0
let zoom = 1
let pan = [0, 0]
let comparisonAsset: ImageBitmap | undefined
let blinkB = false
let blinkTimer = 0
let lastWarnings: string[] = []
const failures = new Map<string, string>()
const prepared = new Map<string, Frame>()
const raster = new Map<string, ImageBitmap>()
type RasterLoad = {controller: AbortController; promise: Promise<ImageBitmap>; consumers: number}
const rasterLoads = new Map<string, RasterLoad>()
const transfers = new Set<Promise<void>>()
const transferLimit = 3
const variantLimit = 8
const encodedRasterLimit = 256 * 1024
const rasterSideLimit = 128

class ServiceError extends Error {
  constructor(message: string, readonly code = '', readonly wait = 1) { super(message) }
}
function note(message: string, kind = '') {
  const status = el('status')
  status.textContent = message
  status.dataset.kind = kind
  const retry = document.getElementById('retry-observation'); if (retry) retry.hidden = kind !== 'error'
}
function formatTime(time: string) { return `${time.replace('T', ' ').replace(/\.\d+Z$/, 'Z').replace(/Z$/, '')} UTC` }
function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason)
    const abort = () => { window.clearTimeout(timer); reject(signal.reason) }
    const timer = window.setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, ms)
    signal.addEventListener('abort', abort, { once: true })
  })
}
function sameOrigin(path: string, prefix: string) {
  const url = new URL(path, location.origin)
  if (url.origin !== location.origin || !url.pathname.startsWith(prefix)) throw new Error('The viewer received an invalid asset URL.')
  return url.pathname + url.search
}
function waitFor<T>(promise: Promise<T>, signal?: AbortSignal) {
  if (!signal) return promise
  return new Promise<T>((resolve, reject) => {
    const stop = () => { signal.removeEventListener('abort', stop); reject(signal.reason) }
    signal.addEventListener('abort', stop, {once: true})
    if (signal.aborted) stop()
    void promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', stop))
  })
}
async function transfer<T>(work: () => Promise<T>, signal?: AbortSignal, priority: 'auto' | 'low' = 'auto') {
  while (transfers.size >= transferLimit) {
    if (priority === 'low') throw new Error('Playback skipped prefetch while the browser was busy.')
    await waitFor(Promise.race(transfers), signal)
  }
  signal?.throwIfAborted()
  const result = work()
  const complete = result.then(() => {}, () => {}).finally(() => { transfers.delete(complete) })
  transfers.add(complete)
  return result
}
export function coordinate(raw: string, ra: boolean): number {
  const value = raw.trim().replaceAll('−', '-')
  const plain = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)
  let n = Number(value)
  if (!plain) {
    const parts = value.match(/^([+-]?)(\d{1,3})(?:\s*[:\s]\s*|[hd°]\s*)(\d{1,2})(?:(?:\s*[:\s]\s*|[m′']\s*)(\d{1,2}(?:\.\d+)?)(?:[s″"])?|[m′'])?$/i)
    if (!parts || (ra && /[d°-]/i.test(value)) || (!ra && /h/i.test(value))) throw new Error(`Enter ${ra ? 'right ascension' : 'declination'} in decimal degrees or sexagesimal.`)
    const minutes = Number(parts[3]), seconds = Number(parts[4] ?? 0)
    if (minutes >= 60 || seconds >= 60) throw new Error('Minutes and seconds must be less than 60.')
    n = (Number(parts[2]) + minutes / 60 + seconds / 3600) * (parts[1] === '-' ? -1 : 1) * (ra ? 15 : 1)
  }
  if (!Number.isFinite(n) || (ra ? n < 0 || n >= 360 : Math.abs(n) > 90)) throw new Error(ra ? 'Right ascension must be at least 0° and below 360°.' : 'Declination must be between −90° and +90°.')
  return ra ? Number(n.toFixed(7)) % 360 : Number(n.toFixed(7))
}
async function data<T>(url: string, signal: AbortSignal, body?: object, announce = true): Promise<Envelope<T>> {
  let job: string | undefined
  try {
    for (let round = 0; ; round++) {
      const path = job ? `/api/v1/jobs/${job}` : url
      const init: RequestInit = { signal }
      if (!job && body) Object.assign(init, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const {ok, status, json} = await transfer(async () => {
        const response = await fetch(path, init)
        return {ok: response.ok, status: response.status,
          json: response.ok ? await response.json() : await response.json().catch(() => ({}))}
      }, signal)
      if (!ok) {
        const problem = json
        if (problem.code === 'SESSION_BUSY' && round < 4) { await delay(1000, signal); continue }
        throw new ServiceError(problem.message ?? `The service returned HTTP ${status}.`, problem.code, problem.retryAfterSec)
      }
      const result = json as Job<T>
      if (result.status === 'succeeded' || result.status === 'partial') return result
      if (result.status === 'failed') throw new ServiceError(result.error.message, result.error.code)
      if (!('jobId' in result) || !/^[\w-]{1,80}$/.test(result.jobId)) throw new Error('Invalid job response.')
      job = result.jobId
      const maxPolls = url.endsWith('/spectra') ? 54 : 40
      if (round >= maxPolls) throw new Error('The request exceeded its browser polling deadline.')
      if (announce) note(result.status === 'queued' ? 'Waiting for a processing slot…' : `${result.stage.charAt(0).toUpperCase()}${result.stage.slice(1)}…`)
      await delay(Math.max(1000, result.pollAfterMs, round > 10 ? 3000 : 0), signal)
    }
  } finally {
    if (job && signal.aborted) {
      void transfer(async () => {
        const response = await fetch(`/api/v1/jobs/${job}`, {method: 'DELETE', keepalive: true})
        await response.body?.cancel()
      }).catch(() => {})
    }
  }
}
function fill(query: Query) {
  for (const [id, value] of Object.entries({ ra: query.raDeg, dec: query.decDeg, fov: query.fovArcmin,
    start: query.start, end: query.end, wavelength: query.wavelengthUm, detector: query.detector })) {
    const field = el<HTMLInputElement | HTMLSelectElement>(id)
    if (id === 'fov' && ![...select(id).options].some(option => Number(option.value) === value)) select(id).add(new Option(`${value}′`, String(value)))
    field.value = value == null ? '' : String(value)
  }
}
function validate(query: Query) {
  if (!(query.fovArcmin >= 1 && query.fovArcmin <= 8)) throw new Error('Choose a field width of 1′–8′.')
  if (query.start && query.end && query.end < query.start) throw new Error('The end date must be on or after the start date.')
  if ([query.start, query.end].some(value => value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value))) throw new Error('Enter a valid UTC date.')
  if (query.detector !== undefined && (![1, 2, 3, 4, 5, 6].includes(query.detector))) throw new Error('Choose a detector between 1 and 6.')
  if (query.wavelengthUm !== undefined && !(query.wavelengthUm >= .7 && query.wavelengthUm <= 5.1)) throw new Error('Choose a wavelength between 0.7 and 5.1 µm.')
  return query
}
function urlFor(query: Query, example?: string) {
  const params = new URLSearchParams({ ra: `${query.raDeg}`, dec: `${query.decDeg}`, fov: `${query.fovArcmin}` })
  for (const [key, value] of Object.entries({ preset: example, start: query.start, end: query.end, wave: query.wavelengthUm,
    detector: query.detector, interval: select('interval').value,
    a: shown?.coaddAnchor ?? shown?.productId, b: paired?.coaddAnchor ?? paired?.productId,
    aCoadd: shown?.representation === 'coadd' ? shown.frameId : undefined,
    bCoadd: paired?.representation === 'coadd' ? paired.frameId : undefined, mode: viewMode, marks: shareMarkParameter })) {
    if (value) params.set(key, String(value))
  }
  return `${appBase}explore${staticOnly ? '/' : ''}?${params}`
}
function share() {
  if (manifest) history.replaceState(null, '', urlFor(manifest.query, preset))
}
function surveyPass(frame: Frame) {
  const value = String(frame.surveyPass ?? '').trim()
  return value ? (/^\d+$/.test(value) ? `Survey ${value}` : value) : undefined
}
function buckets() {
  if (!manifest) return []
  const mode = select('interval').value
  const start = Date.parse(manifest.query.start ?? manifest.frames[0]?.slotKey ?? '')
  const groups = new Map<string | number, Frame[]>()
  const frames = [...manifest.frames].sort((a, b) => a.slotKey.localeCompare(b.slotKey))
  for (const frame of frames) {
    const pass = mode === 'passes' ? surveyPass(frame) : undefined
    const dateKey = mode === 'dates' || mode === 'passes' ? frame.slotKey : Math.floor((Date.parse(frame.slotKey) - start) / (day * (mode === 'week' ? 7 : 30)))
    const key = pass ? `pass:${pass}` : dateKey
    const group = groups.get(key) ?? []
    group.push(frame)
    groups.set(key, group)
  }
  return [...groups.values()]
}
function slotIndex(frame?: Frame) {
  if (!frame) return -1
  return slots.findIndex(group => group.some(item =>
    item.frameId === frame.frameId || (frame.coaddAnchor && item.productId === frame.coaddAnchor)))
}
function rebuildTimeline() {
  const interval = select('interval')
  const passes = interval.querySelector<HTMLOptionElement>('[value=passes]')!
  passes.disabled = interval.value !== 'passes' && !manifest?.frames.some(surveyPass)
  slots = buckets()
}
function timelineLabel(frame: Frame) {
  const time = formatTime(frame.startUtc)
  return select('interval').value === 'passes' ? `${time} · ${surveyPass(frame) ?? 'Unverified survey pass'}` : time
}
function timeline(index: number, frame?: Frame) {
  slider.max = String(Math.max(0, slots.length - 1))
  slider.value = String(Math.max(0, index))
  slider.disabled = slots.length < 2
  const first = manifest?.query.start ?? slots[0]?.[0].slotKey
  const last = manifest?.query.end ?? slots.at(-1)?.[0].slotKey
  el('date-first').textContent = first ?? ''
  el('date-last').textContent = last ?? ''
  el('date-label').textContent = frame ? timelineLabel(frame) : '—'
  slider.setAttribute('aria-valuetext', frame ? timelineLabel(frame) : 'No observation')
  const calendar = el('calendar')
  calendar.replaceChildren()
  if (first && last) {
    const start = Date.parse(first), span = Math.max(day, Date.parse(last) - start)
    for (const [tickIndex, slot] of slots.entries()) {
      const tick = document.createElement('span')
      const representative = tickIndex === index && frame ? frame : slot[0]
      tick.style.left = `${Math.max(0, Math.min(100, 100 * (Date.parse(representative.slotKey) - start) / span))}%`
      tick.dataset.current = String(tickIndex === index)
      tick.dataset.failed = String(slot.every(item => failures.has(item.frameId)))
      tick.title = timelineLabel(representative)
      calendar.append(tick)
    }
  }
  const group = slots[index] ?? []
  const exposures = select('pointing')
  exposures.replaceChildren(...group.map(item => new Option(`${formatTime(item.startUtc)} · D${item.detector}`, item.frameId)))
  if (frame) exposures.value = group.find(item => item.frameId === frame.frameId || item.productId === frame.coaddAnchor)?.frameId ?? ''
  el('pointing-label').hidden = group.length < 2
  button('next').disabled = index >= slots.length - 1
  button('previous').disabled = index <= 0
  button('play').disabled = slots.length < 2
  const summary = `${manifest?.counts.observationDates ?? 0} archive dates · ${prepared.size} prepared in this session · ${slots.length} occupied intervals`
  const playbackNote = slots.length === 1
    ? (manifest?.counts.observationDates === 1 ? 'Only one usable date is available in this selection. Playback requires at least two dates.'
      : 'Only one occupied interval is available. Change the interval to browse individual dates.')
    : summary
  const hasUnknown = select('interval').value === 'passes' && slots.some(group => !surveyPass(group[0]))
  el('timeline-note').textContent = hasUnknown ? `${playbackNote} Observations without a verified pass label are grouped by actual UTC date.` : playbackNote
}
async function fetchRaster(url: string, signal: AbortSignal, priority: 'auto' | 'low') {
  const response = await fetch(url, {signal, priority, redirect: 'error'})
  if (!response.ok || !response.body) {
    await response.body?.cancel()
    throw new Error('The prepared observation image is unavailable.')
  }
  const reader = response.body.getReader()
  const data = new Uint8Array(encodedRasterLimit)
  const header = new DataView(data.buffer)
  let size = 0
  let checkedHeader = false
  let complete = false
  try {
    if (Number(response.headers.get('Content-Length')) > data.length) throw new Error('The prepared image exceeds the transfer limit.')
    while (true) {
      const {value, done} = await reader.read()
      if (done) { complete = true; break }
      if (size + value.length > data.length) throw new Error('The prepared image exceeds the transfer limit.')
      data.set(value, size)
      size += value.length
      if (!checkedHeader && size >= 24) {
        if (header.getUint32(0) !== 0x89504e47 || header.getUint32(4) !== 0x0d0a1a0a ||
            header.getUint32(8) !== 13 || header.getUint32(12) !== 0x49484452) {
          throw new Error('The prepared image has an invalid PNG header.')
        }
        const width = header.getUint32(16), height = header.getUint32(20)
        if (!width || !height || width > rasterSideLimit || height > rasterSideLimit) {
          throw new Error('The prepared image exceeds the science grid dimensions.')
        }
        checkedHeader = true
      }
    }
  } finally {
    if (!complete) await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
  if (!checkedHeader) throw new Error('The prepared image is incomplete.')
  signal.throwIfAborted()
  const image = await createImageBitmap(new Blob([data.subarray(0, size)], {type: 'image/png'}))
  if (signal.aborted) {
    image.close()
    signal.throwIfAborted()
  }
  return image
}
function reserveVariant() {
  if (new Set([...raster.keys(), ...rasterLoads.keys()]).size < variantLimit) return
  for (const [key, image] of raster) {
    if (image === rendered || image === renderedPair || image === comparisonAsset || rasterLoads.has(key)) continue
    raster.delete(key)
    image.close()
    return
  }
  throw new Error('All image variants are still in use. Try the observation again.')
}
function clearRasters() {
  for (const load of rasterLoads.values()) load.controller.abort()
  for (const image of raster.values()) image.close()
  raster.clear()
}
async function readImage(url: string, signal: AbortSignal, priority: 'auto' | 'low' = 'auto') {
  signal.throwIfAborted()
  const asset = url.startsWith('/presets/') ? `${appBase}${url.slice(1)}` : url
  const checked = sameOrigin(asset, asset.startsWith(`${appBase}presets/`) ? `${appBase}presets/` : '/data/')
  const cached = raster.get(checked)
  if (cached) {
    raster.delete(checked)
    raster.set(checked, cached)
    return cached
  }
  let load = rasterLoads.get(checked)
  if (load?.controller.signal.aborted) {
    await waitFor(load.promise.catch(() => {}), signal)
    return readImage(url, signal, priority)
  }
  if (!load) {
    if (priority === 'low' && transfers.size >= transferLimit) throw new Error('Playback skipped prefetch while the browser was busy.')
    reserveVariant()
    const controller = new AbortController()
    const promise = transfer(() => fetchRaster(checked, controller.signal, priority), controller.signal, priority)
      .then(image => {
        if (controller.signal.aborted) {
          image.close()
          controller.signal.throwIfAborted()
        }
        raster.set(checked, image)
        return image
      }).finally(() => { rasterLoads.delete(checked) })
    load = {controller, promise, consumers: 0}
    rasterLoads.set(checked, load)
  }
  const active = load
  active.consumers++
  return waitFor(active.promise, signal).finally(() => {
    if (--active.consumers === 0) active.controller.abort()
  })
}
function transform(canvas: HTMLCanvasElement) {
  const { width, height } = canvas.getBoundingClientRect()
  const size = Math.min(width, height) * zoom
  return { width, height, size, left: (width - size) / 2 + pan[0], top: (height - size) / 2 + pan[1] }
}
function paint(canvas: HTMLCanvasElement, image?: ImageBitmap, adjustContrast = true) {
  const { width, height, size, left, top } = transform(canvas)
  const dpr = Math.min(2, window.devicePixelRatio)
  canvas.width = Math.round(width * dpr)
  canvas.height = Math.round(height * dpr)
  const context = canvas.getContext('2d')!
  context.scale(dpr, dpr)
  context.fillStyle = '#141c29'
  if (image && size > 0) {
    context.fillRect(left, top, size, size)
    context.save()
    context.beginPath(); context.rect(left, top, size, size); context.clip()
    context.strokeStyle = '#263244'
    context.lineWidth = 1
    for (let shift = -size; shift < size; shift += 12) {
      context.beginPath(); context.moveTo(left + shift, top); context.lineTo(left + shift + size, top + size); context.stroke()
    }
    context.restore()
    context.imageSmoothingEnabled = false
    if (adjustContrast) context.filter = `contrast(${input('contrast').value})`
    context.drawImage(image, left, top, size, size)
  }
}
function redraw() {
  el('contrast-control').hidden = !rendered || Boolean(comparisonAsset)
  paint(canvasA, comparisonAsset ?? (viewMode === 'blink' && blinkB ? renderedPair : rendered), !comparisonAsset)
  if (viewMode === 'side') paint(canvasB, renderedPair)
  el('layers-a').replaceChildren()
  el('layers-b').replaceChildren()
  document.dispatchEvent(new Event('spherex-redraw'))
}
function details(frame: Frame) {
  const item = el('metadata')
  item.replaceChildren()
  const list = document.createElement('dl')
  for (const [key, value] of Object.entries({ Start: formatTime(frame.startUtc), End: formatTime(frame.endUtc), Product: frame.productId,
    Release: frame.release, Detector: `D${frame.detector}`, Wavelength: frame.wavelengthUm != null ? `${frame.wavelengthUm.toFixed(4)} µm${frame.bandwidthUm != null ? ` · ${frame.bandwidthUm.toFixed(4)} µm bandwidth` : ''}` : 'Unavailable',
    Footprint: frame.coverageFraction == null ? 'Unavailable' : `${Math.round(frame.coverageFraction * 100)}%`, 'Valid pixels': frame.validFraction == null ? 'Unavailable' : `${Math.round(frame.validFraction * 100)}%`,
    'Survey pass': surveyPass(frame) ?? 'Unverified', Representation: frame.representation ?? 'Single exposure' })) {
    const dt = document.createElement('dt'), dd = document.createElement('dd')
    dt.textContent = key; dd.textContent = value; list.append(dt, dd)
  }
  item.append(list)
  if (frame.archiveUrl.startsWith('https://irsa.ipac.caltech.edu/')) {
    const source = document.createElement('a'); source.href = frame.archiveUrl; source.textContent = 'Original IRSA product ↗'; item.append(source)
  }
  if (frame.archiveDoi && /^10\.26131\/IRSA\d+$/.test(frame.archiveDoi)) {
    const citation = document.createElement('a'); citation.href = `https://doi.org/${frame.archiveDoi}`; citation.textContent = 'Release DOI ↗'; citation.className = 'doi'; item.append(citation)
  }
  for (const warning of frame.warnings ?? []) { const p = document.createElement('p'); p.textContent = warning; item.append(p) }
}
async function prepare(frame: Frame, signal: AbortSignal, representation = 'exposure') {
  const cached = prepared.get(frame.frameId)
  if (representation === 'exposure' && (cached?.imageUrl || frame.imageUrl)) return cached ?? frame
  const prefix = `/api/v1/series/${manifest!.seriesId}/frames/${frame.frameId}`
  const response = await data<Frame>(prefix, signal, { representation })
  return representation === 'coadd' ? {...response.data, coaddAnchor: frame.productId} : response.data
}

async function preparePinned(frame: Frame, signal: AbortSignal, coaddId?: string) {
  const result = await prepare(frame, signal, coaddId ? 'coadd' : 'exposure')
  if (coaddId && (result.frameId !== coaddId || result.representation !== 'coadd')) {
    throw new Error('The pinned coadd version is unavailable.')
  }
  return result
}

let pinnedA: string | null = null
let pinnedB: string | null = null
let pinnedCoaddA: string | undefined
let pinnedCoaddB: string | undefined
function hasMissingPins(frames: Frame[]) {
  return [pinnedA, pinnedB].some(pin => pin && !frames.some(frame => frame.productId === pin))
}
let shareMarkParameter: string | undefined
let manifestPages: AbortController | undefined
let retrySlot: number | undefined
const validModes = staticOnly ? ['single', 'blink', 'side'] : ['single', 'blink', 'side', 'difference', 'absolute_change', 'residual_score', 'sum']
const presetPath = (slug: string) => `${appBase}presets/${slug}/manifest.json`
const statusMessage = (error: unknown) => error instanceof Error ? error.message : 'The operation could not be completed.'

function updatePrepared(frame: Frame) {
  prepared.set(frame.frameId, frame)
  if (!manifest) return
  const previous = manifest.frames.findIndex(item => item.frameId === frame.frameId)
  if (previous >= 0) manifest.frames[previous] = frame
  else if (frame.coaddAnchor && surveyPass(frame)) {
    const anchor = manifest.frames.find(item => item.productId === frame.coaddAnchor)
    if (anchor && !surveyPass(anchor)) anchor.surveyPass = frame.surveyPass
  }
  rebuildTimeline()
}

async function showPrepared(frame: Frame, signal: AbortSignal = frameRequest.signal) {
  if (!frame.imageUrl) throw new Error('This observation has no prepared image.')
  const image = await readImage(frame.imageUrl, signal)
  if (signal.aborted) return
  shown = frame
  rendered = image
  updatePrepared(frame)
  el('image-empty').hidden = true
  el('image-tools').hidden = false
  const title = `${formatTime(frame.startUtc)} · D${frame.detector}`
  el('frame-a').setAttribute('aria-label', `SPHEREx observation ${title}`)
  el('caption-a').textContent = title
  const index = Math.max(0, slotIndex(frame))
  timeline(index, frame)
  details(frame)
  updatePairChoices()
  share()
  redraw()
  document.dispatchEvent(new Event('spherex-frame'))
}

async function choose(index: number, options: { specific?: Frame; nextUsable?: boolean; coaddId?: string } = {}): Promise<boolean> {
  if (!manifest || index < 0 || index >= slots.length) return false
  const generation = ++selectionId
  frameRequest.abort()
  pairController.value.abort()
  frameRequest = new AbortController()
  const signal = frameRequest.signal
  comparisonAsset = undefined
  el('heatmap-legend').hidden = true
  if (viewMode !== 'single' && viewMode !== 'side' && viewMode !== 'blink') setMode('single')
  const range = options.nextUsable ? slots.slice(index, index + 5) : [slots[index]]
  let lastError = ''
  let attempts = 0
  for (const group of range) {
    const alternatives = options.specific ? [options.specific] : group
    for (const frame of alternatives.slice(0, 6)) {
      if (failures.has(frame.frameId)) continue
      timeline(slots.indexOf(group), frame)
      note(`Loading ${formatTime(frame.startUtc)}…`)
      try {
        const preparedFrame = await preparePinned(frame, signal, options.coaddId)
        if (signal.aborted || generation !== selectionId) return false
        await showPrepared(preparedFrame, signal)
        if (signal.aborted || generation !== selectionId) return false
        const warning = [...(attempts ? ['Earlier candidate exposures were unavailable.'] : []), ...lastWarnings].join(' ')
        note(warning || 'Observation ready.')
        retrySlot = undefined
        const next = slots[slotIndex(preparedFrame) + 1]?.[0]
        const neighbor = next && (prepared.get(next.frameId) ?? next)
        if (neighbor?.imageUrl) void readImage(neighbor.imageUrl, signal, 'low').catch(() => {})
        return true
      } catch (error) {
        if (signal.aborted || generation !== selectionId) return false
        lastError = statusMessage(error)
        if (options.coaddId) {
          note(`The pinned coadd could not be restored. ${lastError}`, 'error')
          retrySlot = index
          return false
        }
        if (!(error instanceof ServiceError) || !['LOW_OVERLAP', 'BAD_FITS', 'INCOMPATIBLE_WAVELENGTH', 'PRODUCT_MISSING'].includes(error.code)) {
          note(lastError, 'error')
          retrySlot = index
          return false
        }
        failures.set(frame.frameId, lastError)
        if (++attempts >= 6) break
      }
    }
    if (attempts >= 6) break
  }
  timeline(index, slots[index][0])
  note(lastError || 'No suitable exposure for this interval. Choose another observation date.', 'error')
  retrySlot = index
  return false
}

function setPlaying(active: boolean) {
  window.clearTimeout(timekeeper)
  playing = active
  button('play').textContent = active ? 'Ⅱ Pause' : '▶ Play'
  button('play').setAttribute('aria-label', active ? 'Pause observations' : 'Play observations')
  if (active) timekeeper = window.setTimeout(advance, 1000 / Number(select('speed').value))
}
async function advance() {
  if (!playing || slots.length < 2) return setPlaying(false)
  const index = Number(slider.value)
  if (index >= slots.length - 1) return setPlaying(false)
  const displayed = await choose(index + 1)
  if (!displayed) return setPlaying(false)
  if (playing) setPlaying(true)
}

function createButton(text: string, onClick: () => void) {
  const item = document.createElement('button')
  item.type = 'button'; item.textContent = text
  item.addEventListener('click', onClick)
  return item
}
const pairPick = document.createElement('select')
const modePick = document.createElement('select')
const pairNote = document.createElement('p')
const pairController = { value: new AbortController() }
function updatePairChoices() {
  if (!shown || !manifest) return
  const candidates = manifest.frames.filter(item => item.frameId !== shown!.frameId).slice(0, 500)
  candidates.sort((a, b) => a.startUtc.localeCompare(b.startUtc))
  pairPick.replaceChildren(new Option('Choose a second observation', ''), ...candidates.map(
    frame => new Option(`${formatTime(frame.startUtc)} · D${frame.detector}`, frame.frameId)))
  if (paired && !candidates.some(item => item.frameId === paired!.frameId)) {
    const frame = paired
    if (frame.frameId !== shown.frameId) pairPick.add(new Option(formatTime(frame.startUtc), frame.frameId))
    else { paired = undefined; renderedPair = undefined; setMode('single') }
  }
  if (paired) pairPick.value = paired.frameId
  el('pair-panel').hidden = !candidates.length
}
function setMode(mode: string) {
  viewMode = validModes.includes(mode) ? mode : 'single'
  modePick.value = viewMode
  window.clearInterval(blinkTimer)
  blinkB = false
  comparisonAsset = undefined
  el('heatmap-legend').hidden = true
  el('frame-b').hidden = viewMode !== 'side'
  el('caption-a').hidden = !['blink', 'side'].includes(viewMode)
  el('caption-b').hidden = viewMode !== 'side'
  if (shown) el('caption-a').textContent = formatTime(shown.startUtc)
  if (viewMode === 'blink' && paired) {
    blinkTimer = window.setInterval(() => {
      blinkB = !blinkB
      const frame = blinkB ? paired : shown
      if (frame) el('caption-a').textContent = formatTime(frame.startUtc)
      redraw()
    }, 850)
  }
  redraw()
  share()
}
function compatible(a: Frame, b: Frame) {
  return a.detector === b.detector && a.visitId !== b.visitId && a.wavelengthUm != null && b.wavelengthUm != null
    && a.bandwidthUm != null && b.bandwidthUm != null && Math.abs(a.wavelengthUm - b.wavelengthUm) <= Math.min(a.bandwidthUm, b.bandwidthUm) / 2
}
function pairLegend(result: { limits: number[]; units: string; warnings?: string[]; mode: string }, a: Frame, b: Frame) {
  const legend = el('heatmap-legend')
  legend.replaceChildren()
  const name = document.createElement('p')
  const signed = result.mode === 'difference' || result.mode === 'residual_score'
  name.textContent = `${formatTime(a.startUtc)} and ${formatTime(b.startUtc)} · ${result.units}`
  const ramp = document.createElement('span'); ramp.className = 'legend-ramp'
  if (!signed) ramp.style.background = 'linear-gradient(90deg, #161d2a, #f6cd7e)'
  const labels = document.createElement('div'); labels.className = 'legend-labels'
  const low = document.createElement('span'), high = document.createElement('span')
  low.textContent = `${result.limits[0].toPrecision(3)}${signed ? ' · lower in B' : ''}`
  high.textContent = `${result.limits[1].toPrecision(3)}${signed ? ' · higher in B' : ''}`
  labels.append(low, high)
  legend.append(name, ramp, labels)
  legend.hidden = false
}
async function showPair(mode: string, other?: Frame, coaddId?: string) {
  pairController.value.abort()
  pairController.value = new AbortController()
  const signal = pairController.value.signal
  if (!shown || !manifest || !other) return setMode('single')
  const a = shown
  try {
    const second = await preparePinned(other, signal, coaddId)
    if (signal.aborted || shown !== a) return
    const image = await readImage(second.imageUrl!, signal)
    if (signal.aborted || shown !== a) return
    paired = second
    renderedPair = image
    updatePrepared(paired)
    timeline(Math.max(0, slotIndex(shown)), shown)
    updatePairChoices()
    el('caption-b').textContent = formatTime(paired.startUtc)
    pairNote.textContent = compatible(a, paired) ? 'Matched detector and central passbands. Pixel analysis checks common coverage and registration.'
      : 'The selected pair is unsuitable for pixel analysis. You can still inspect both observations.'
    setMode(mode)
    document.dispatchEvent(new Event('spherex-pair'))
    if (['single', 'blink', 'side'].includes(mode)) { note('Both observations are ready.'); return }
    const result = await data<{ assetUrl: string; limits: number[]; units: string; warnings?: string[]; mode: string }>(
      `/api/v1/series/${manifest.seriesId}/comparisons`, signal, { frameA: a.frameId, frameB: paired.frameId, mode })
    if (signal.aborted || shown !== a) return
    const asset = await readImage(result.data.assetUrl, signal)
    if (signal.aborted || shown !== a) return
    comparisonAsset = asset
    pairLegend(result.data, a, paired)
    redraw()
    note(result.warnings.join(' ') || 'Comparison ready.')
  } catch (error) {
    if (!signal.aborted) {
      pairNote.textContent = coaddId ? `The second pinned coadd could not be restored. ${statusMessage(error)}` : statusMessage(error)
      setMode('single')
      note(pairNote.textContent, 'error')
    }
  }
}

async function loadIndex(query: Query, example: string | undefined, fromLink = false) {
  const active = ++queryId
  request.abort(); frameRequest.abort(); pairController.value.abort(); manifestPages?.abort()
  request = new AbortController()
  const signal = request.signal
  setPlaying(false)
  manifest = undefined; slots = []; shown = undefined; paired = undefined
  rendered = undefined; renderedPair = undefined; retrySlot = undefined
  failures.clear(); prepared.clear(); clearRasters()
  if (!fromLink) {
    pinnedA = pinnedB = null
    pinnedCoaddA = pinnedCoaddB = shareMarkParameter = undefined
  }
  const restoredMode = fromLink ? viewMode : 'single'
  setMode('single')
  zoom = 1; pan = [0, 0]; redraw()
  preset = example
  for (const id of ['timeline-panel', 'pair-panel', 'image-tools', 'contrast-control', 'share']) el(id).hidden = true
  el('image-empty').hidden = false
  el('metadata').textContent = 'Select an observation to view its provenance.'
  el('query-error').hidden = true
  fill(query)
  el('field-title').textContent = example ? known.get(example)!.name : 'Custom sky field'
  el('field-position').textContent = `${query.raDeg.toFixed(5)}°, ${query.decDeg >= 0 ? '+' : ''}${query.decDeg.toFixed(5)}° · ${query.fovArcmin}′`
  if (!fromLink) history.pushState(null, '', urlFor(query, example))
  note(example ? 'Opening bundled example…' : 'Searching the NASA/IPAC archive…')
  for (const link of el('presets').querySelectorAll('a')) link.setAttribute('aria-current', String(link.dataset.slug === example))
  try {
    const response = await data<Manifest>(example ? presetPath(example) : '/api/v1/series', signal, example ? undefined : query)
    if (signal.aborted || active !== queryId) return
    manifest = response.data
    lastWarnings = response.warnings
    if (!manifest.frames.length) {
      const empty = manifest.searchStatus === 'NO_COVERAGE' ? 'No published observations cover this field and selection.'
        : manifest.searchStatus === 'NO_COMPARABLE_FRAMES' ? 'No exposures match the selected detector, wavelength and dates.'
        : 'The incomplete archive reply contains no candidate observations. Try again or open an example.'
      note(empty, 'error')
      return
    }
    if (hasMissingPins(manifest.frames)) await loadMore(true)
    if (signal.aborted || active !== queryId) return
    rebuildTimeline()
    const selected = pinnedA ? manifest.frames.find(frame => frame.productId === pinnedA) : undefined
    if (pinnedA && !selected) lastWarnings.push('The pinned first exposure is unavailable. Showing the earliest suitable observation.')
    const other = pinnedB ? manifest.frames.find(frame => frame.productId === pinnedB) : undefined
    if (pinnedB && !other) {
      pairNote.textContent = 'The pinned second exposure is unavailable. Choose another date.'
      lastWarnings.push(pairNote.textContent)
    }
    el('timeline-panel').hidden = false
    button('share').hidden = false
    const target = Math.max(0, slotIndex(selected))
    const restored = await choose(Math.max(0, target), selected ? {specific: selected, coaddId: pinnedCoaddA} : {nextUsable: true})
    if (signal.aborted || active !== queryId) return
    if (!restored && pinnedCoaddA && selected) {
      lastWarnings.push('The pinned coadd is unavailable. Showing its original exposure.')
      await choose(Math.max(0, target), {specific: selected})
    }
    if (signal.aborted || active !== queryId) return
    if (restoredMode !== 'single' && other && (!pinnedCoaddA || (selected && restored))) {
      await showPair(restoredMode, other, pinnedCoaddB)
    }
    moreButton.hidden = !manifest.nextCursor
    share()
  } catch (error) {
    if (!signal.aborted && active === queryId) note(statusMessage(error), 'error')
  }
}

async function loadMore(toFindPin = false) {
  if (!manifest?.nextCursor || preset) return
  const current = manifest
  manifestPages?.abort()
  manifestPages = new AbortController()
  const signal = manifestPages.signal
  try {
    do {
      const cursor = current.nextCursor
      if (!cursor) break
      const page = await data<Manifest>(`/api/v1/series/${current.seriesId}?${new URLSearchParams({ cursor })}`, signal, undefined, false)
      if (signal.aborted || current !== manifest) return
      current.frames.push(...page.data.frames)
      current.nextCursor = page.data.nextCursor
    } while (toFindPin && current.nextCursor && hasMissingPins(current.frames))
    rebuildTimeline()
    timeline(Math.max(0, slotIndex(shown)), shown)
    updatePairChoices()
    moreButton.hidden = !current.nextCursor
  } catch (error) { if (!signal.aborted) note(statusMessage(error), 'error') }
}

function readLocation() {
  if (![`${appBase}explore`, `${appBase}explore/`].includes(location.pathname)) return
  try {
    const params = new URLSearchParams(location.search)
    const example = params.get('preset') ?? undefined
    const coords = example ? known.get(example) : undefined
    if (example && !coords) throw new Error('This example field is unavailable.')
    if (staticOnly && !coords) throw new Error('Live lookup is unavailable in this static copy. Choose a bundled example.')
    const query = validate({ raDeg: coordinate(params.get('ra') ?? String(coords?.raDeg ?? ''), true),
      decDeg: coordinate(params.get('dec') ?? String(coords?.decDeg ?? ''), false), fovArcmin: Number(params.get('fov') ?? coords?.fovArcmin ?? 3),
      start: params.get('start') || undefined, end: params.get('end') || undefined,
      wavelengthUm: params.has('wave') ? Number(params.get('wave')) : undefined,
      detector: params.has('detector') ? Number(params.get('detector')) : undefined })
    if (coords && (Math.abs(coords.raDeg - query.raDeg) > 1e-6 || Math.abs(coords.decDeg - query.decDeg) > 1e-6 || coords.fovArcmin !== query.fovArcmin)) {
      throw new Error('This example link has different sky coordinates or field width. Choose an example or search these coordinates directly.')
    }
    select('interval').value = ['dates', 'week', 'month', 'passes'].includes(params.get('interval') ?? '') ? params.get('interval')! : 'dates'
    viewMode = validModes.includes(params.get('mode') ?? '') ? params.get('mode')! : 'single'
    pinnedA = params.get('a'); pinnedB = params.get('b')
    const coaddA = params.get('aCoadd'), coaddB = params.get('bCoadd')
    if ((coaddA && (!pinnedA || !/^[\w-]{1,80}$/.test(coaddA))) || (coaddB && (!pinnedB || !/^[\w-]{1,80}$/.test(coaddB)))) {
      throw new Error('The shared link contains an invalid coadd identifier.')
    }
    pinnedCoaddA = coaddA || undefined
    pinnedCoaddB = coaddB || undefined
    shareMarkParameter = (params.get('marks') || '').slice(0, 1000) || undefined
    void loadIndex(query, example, true)
  } catch (error) {
    el('query-error').textContent = statusMessage(error)
    el('query-error').hidden = false
  }
}

const moreButton = createButton('More indexed exposures', () => { void loadMore() })
moreButton.hidden = true
const retryButton = createButton('Retry selected observation', () => { if (retrySlot !== undefined) void choose(retrySlot) })
retryButton.id = 'retry-observation'
retryButton.hidden = true
el('timeline-panel').append(moreButton, retryButton)
modePick.setAttribute('aria-label', 'Comparison view')
pairPick.setAttribute('aria-label', 'Second observation date')
modePick.replaceChildren(...[
  ['single', 'Single frame'], ['blink', 'Blink'], ['side', 'Side by side'], ['difference', 'Signed difference (B − A)'],
  ['absolute_change', 'Absolute change'], ['sum', 'Sum (A + B)'], ['residual_score', 'Residual score'],
].filter(([value]) => validModes.includes(value)).map(([value, label]) => new Option(label, value)))
function onPairChange() {
  const candidate = manifest?.frames.find(frame => frame.frameId === pairPick.value) ?? prepared.get(pairPick.value)
  const mode = modePick.value === 'single' && candidate ? 'side' : modePick.value
  void showPair(mode, candidate)
}
pairPick.addEventListener('change', onPairChange)
modePick.addEventListener('change', () => { void showPair(modePick.value, manifest?.frames.find(frame => frame.frameId === pairPick.value) ?? prepared.get(pairPick.value)) })
el('pair-controls').append(pairPick, modePick, pairNote)

for (const [slug, field] of known) {
  const link = document.createElement('a')
  link.href = urlFor(field, slug); link.dataset.slug = slug; link.textContent = field.name
  link.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
    event.preventDefault(); void loadIndex(field, slug)
  })
  el('presets').append(link)
}
el('query-form').addEventListener('submit', event => {
  event.preventDefault()
  try {
    const query = validate({ raDeg: coordinate(input('ra').value, true), decDeg: coordinate(input('dec').value, false),
      fovArcmin: Number(select('fov').value), start: input('start').value || undefined, end: input('end').value || undefined,
      wavelengthUm: input('wavelength').value ? Number(input('wavelength').value) : undefined,
      detector: select('detector').value ? Number(select('detector').value) : undefined })
    void loadIndex(query, undefined)
  } catch (error) { el('query-error').textContent = statusMessage(error); el('query-error').hidden = false }
})
select('interval').addEventListener('change', () => {
  rebuildTimeline()
  const index = Math.max(0, slotIndex(shown))
  timeline(index, shown ?? slots[index]?.[0]); share()
})
select('speed').addEventListener('change', () => { if (playing) setPlaying(true) })
select('pointing').addEventListener('change', () => {
  const index = Number(slider.value)
  const frame = slots[index]?.find(item => item.frameId === select('pointing').value)
  if (frame) { setPlaying(false); void choose(index, { specific: frame }) }
})
button('play').addEventListener('click', () => { if (Number(slider.value) === slots.length - 1 && !playing) void choose(0); setPlaying(!playing) })
button('previous').addEventListener('click', () => { setPlaying(false); void choose(Number(slider.value) - 1) })
button('next').addEventListener('click', () => { setPlaying(false); void choose(Number(slider.value) + 1) })
let dragging = false
slider.addEventListener('pointerdown', () => { dragging = true; window.clearTimeout(debounce); setPlaying(false) })
slider.addEventListener('input', () => {
  const index = Number(slider.value)
  timeline(index, slots[index]?.[0])
  window.clearTimeout(debounce)
  if (!dragging) debounce = window.setTimeout(() => { setPlaying(false); void choose(index) }, 200)
})
slider.addEventListener('change', () => { if (dragging) { dragging = false; window.clearTimeout(debounce); void choose(Number(slider.value)) } })
slider.addEventListener('pointercancel', () => { dragging = false })
button('zoom-in').addEventListener('click', () => { zoom = Math.min(8, zoom * 1.5); redraw() })
button('zoom-out').addEventListener('click', () => { zoom = Math.max(1, zoom / 1.5); if (zoom === 1) pan = [0, 0]; redraw() })
button('reset-view').addEventListener('click', () => { zoom = 1; pan = [0, 0]; redraw() })
button('reset-contrast').addEventListener('click', () => { input('contrast').value = '1'; redraw() })
input('contrast').addEventListener('input', redraw)
button('share').addEventListener('click', async () => {
  share()
  try { await navigator.clipboard.writeText(location.href); note('Share link copied.') }
  catch { note('Copy the address from your browser to share this view.') }
})
for (const id of ['frame-a', 'frame-b']) {
  const pane = el(id)
  let start: [number, number] | undefined
  pane.addEventListener('pointerdown', event => {
    if (zoom === 1 || el('images').classList.contains('marking')) return
    start = [event.clientX - pan[0], event.clientY - pan[1]]; pane.setPointerCapture(event.pointerId)
  })
  pane.addEventListener('pointermove', event => {
    if (start) { pan = [event.clientX - start[0], event.clientY - start[1]]; redraw() }
  })
  pane.addEventListener('lostpointercapture', () => { start = undefined })
}
new ResizeObserver(redraw).observe(el('images'))
window.addEventListener('popstate', readLocation)
window.addEventListener('pagehide', () => { request.abort(); frameRequest.abort(); pairController.value.abort() })

function position(event: MouseEvent, canvas: HTMLCanvasElement) {
  if (!manifest) return
  const bounds = canvas.getBoundingClientRect(), basis = transform(canvas)
  const fx = (event.clientX - bounds.left - basis.left) / basis.size
  const fy = (event.clientY - bounds.top - basis.top) / basis.size
  if (!(fx >= 0 && fx < 1 && fy >= 0 && fy < 1)) return
  return { x: Math.max(0, Math.min(manifest.grid.width - 1, fx * manifest.grid.width - .5)),
    y: Math.max(0, Math.min(manifest.grid.height - 1, (1 - fy) * manifest.grid.height - .5)) }
}
function mark(target: 'a' | 'b', x: number, y: number, cssClass: string, title?: string) {
  if (!manifest) return
  const basis = transform(target === 'a' ? canvasA : canvasB)
  const node = document.createElement('span')
  node.className = `marker ${cssClass}`
  node.style.left = `${basis.left + (x + .5) / manifest.grid.width * basis.size}px`
  node.style.top = `${basis.top + (1 - (y + .5) / manifest.grid.height) * basis.size}px`
  if (title) node.title = title
  el(`layers-${target}`).append(node)
  return node
}
export const analysisApi = {
  manifest: () => manifest, shown: () => shown, paired: () => paired,
  displayed: (target: 'a' | 'b') => target === 'b' || (viewMode === 'blink' && blinkB) ? paired : shown,
  displayMode: () => viewMode,
  prepare, showPrepared, data, note, position, mark, redraw,
  shareMarks(value?: string) { shareMarkParameter = value?.slice(0, 1000); share() },
}
if (staticOnly) {
  el('query-form').hidden = true
  document.querySelector<HTMLAnchorElement>('.brand')!.href = appBase
  const explanation = el('title').nextElementSibling!
  explanation.textContent = 'Static copy · Play the bundled real examples and compare dates. Live lookup and scientific analysis require the server.'
} else installAnalysis(analysisApi)
readLocation()
