import type { Envelope, Frame, Manifest } from './core.ts'

type Pixel = {x: number; y: number}
type Sky = {raDeg: number; decDeg: number}
type Pane = 'a' | 'b'
type CatalogReference = {
  catalogId: string; referenceEpoch: number | string | null
  referenceRaDeg: number; referenceDecDeg: number; pmRaMasYr?: number | null; pmDecMasYr?: number | null
}
type Marker = CatalogReference & Pixel & Sky & {properMotionApplied: boolean}
type Catalog = 'gaia_dr3' | 'allwise'
type Overlay = {
  markers: Marker[]; referenceRows?: CatalogReference[]; displayEpoch: string; positionMethod: string; truncated: boolean; sourceUrl: string
}
type Mark = {frameId: string; pixel: Pixel}
type Source = Mark & {snr?: number; method?: string}
type PinnedMark = Mark & {productId: string; sky: Sky}
type Candidate = {candidateId: string; label: string; reason: string; marks: Source[]; score: number}
type Detections = {candidates: Candidate[]; sources: {frameId: string; sources: Source[]}[]; warnings: string[]}
type Forecast = {
  horizonDays: number; model: string; uncertainty: string
  samples: (Pixel & {timeUtc: string; ellipse95Arcsec: number})[]
}
type Track = {
  measurements: (Mark & Sky & {timeUtc: string; productId?: string; sigmaArcsec: number; method: string})[]
  baselineDays: number; separationArcsec: number; uncertaintyArcsec: number; positionAngleDeg: number | null
  rateArcsecPerDay: number; forecastReason: string; forecast: Forecast | null
}
type SpectrumSample = {
  wavelengthUm: number | null; flux?: number | null; units?: string; error?: number | null; startUtc: string | null
  sampleStatus: 'measured' | 'missing'; reason?: string; channel?: number; productId?: string; bandwidthUm?: number
}
type Spectrum = {samples: SpectrumSample[]; mode: string; units: string; referenceUrl: string; warnings: string[]}

export type AnalysisApi = {
  manifest(): Manifest | undefined
  shown(): Frame | undefined
  paired(): Frame | undefined
  prepare(frame: Frame, signal: AbortSignal, representation?: string): Promise<Frame>
  showPrepared(frame: Frame): Promise<void>
  data<T>(url: string, signal: AbortSignal, body?: object, announce?: boolean): Promise<Envelope<T>>
  note(message: string, kind?: string): void
  position(event: PointerEvent | MouseEvent, canvas: HTMLCanvasElement): Pixel | undefined
  mark(target: Pane, x: number, y: number, cssClass: string, title?: string): HTMLElement | void
  redraw(): void
  shareMarks(value?: string): void
}

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T
const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text?: string) => {
  const element = document.createElement(tag)
  if (text !== undefined) element.textContent = text
  return element
}
const action = (text: string) => {
  const element = node('button', text)
  element.type = 'button'
  return element
}
const label = <T extends HTMLElement>(text: string, control: T) => {
  const wrapper = node('label', text)
  wrapper.append(control)
  return wrapper
}
const choose = (options: [string, string][]) => {
  const select = node('select')
  select.append(...options.map(([value, text]) => new Option(text, value)))
  return select
}
const statusLine = () => {
  const paragraph = node('p')
  paragraph.className = 'annotation'
  paragraph.setAttribute('role', 'status')
  return paragraph
}
const actions = (...buttons: HTMLButtonElement[]) => {
  const row = node('div')
  row.className = 'tool-actions'
  row.append(...buttons)
  return row
}
const link = (name: string, href: string) => {
  const element = node('a', name)
  try {
    const url = new URL(href)
    if (url.protocol === 'https:') element.href = url.href
  } catch { /* A malformed provenance URL stays inert. */ }
  return element
}
const finite = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isFinite(value)
const format = (value: number | null | undefined, digits = 3) => finite(value) ? Number(value.toPrecision(digits)).toString() : '—'
const cleanText = (problem: unknown) => problem instanceof Error ? problem.message : 'The operation did not complete.'
const distinctWarnings = (...warnings: string[][]) => [...new Set(warnings.flat())]
const isSciencePoint = (value: unknown): value is Pixel => {
  const point = value as Pixel | undefined
  return Boolean(point && finite(point.x) && finite(point.y))
}

const radians = Math.PI / 180

export function pixelToSky(grid: Manifest['grid'], pixel: Pixel): Sky {
  const dx = pixel.x + 1 - grid.crpix[0], dy = pixel.y + 1 - grid.crpix[1]
  const xi = (grid.cd[0][0] * dx + grid.cd[0][1] * dy) * radians
  const eta = (grid.cd[1][0] * dx + grid.cd[1][1] * dy) * radians
  const [ra, dec] = grid.crval.map(degrees => degrees * radians)
  const denominator = Math.cos(dec) - eta * Math.sin(dec)
  return {
    raDeg: (ra / radians + Math.atan2(xi, denominator) / radians + 360) % 360,
    decDeg: Math.atan2(Math.sin(dec) + eta * Math.cos(dec), Math.hypot(denominator, xi)) / radians,
  }
}

export function skyToPixel(grid: Manifest['grid'], point: Sky): Pixel | undefined {
  const [a, d, ra, dec] = [...grid.crval, point.raDeg, point.decDeg].map(value => value * radians)
  const east = Math.cos(dec) * Math.sin(ra - a)
  const north = Math.cos(d) * Math.sin(dec) - Math.sin(d) * Math.cos(dec) * Math.cos(ra - a)
  const center = Math.sin(d) * Math.sin(dec) + Math.cos(d) * Math.cos(dec) * Math.cos(ra - a)
  if (center <= 0) return
  const [xi, eta] = [east / center / radians, north / center / radians]
  const [[cd11, cd12], [cd21, cd22]] = grid.cd
  const det = cd11 * cd22 - cd12 * cd21
  return {x: grid.crpix[0] - 1 + (cd22 * xi - cd12 * eta) / det,
    y: grid.crpix[1] - 1 + (-cd21 * xi + cd11 * eta) / det}
}

export function projectCatalog(rows: CatalogReference[], catalog: Catalog, grid: Manifest['grid'], when: number) {
  // Julian year relative to J2000.0. The UTC–TCB clock difference is negligible on this display grid.
  const jyear = 2000 + (when - Date.UTC(2000, 0, 1, 12)) / (365.25 * 86400000)
  return rows.flatMap(source => {
    let ra = source.referenceRaDeg, dec = source.referenceDecDeg
    let properMotionApplied = false
    if (catalog === 'gaia_dr3' && finite(source.pmRaMasYr) && finite(source.pmDecMasYr) && typeof source.referenceEpoch === 'number') {
      const years = jyear - source.referenceEpoch
      const angle = Math.atan2(source.pmRaMasYr, source.pmDecMasYr)
      const arc = Math.hypot(source.pmRaMasYr, source.pmDecMasYr) * years * radians / 3600000
      const lat = dec * radians
      const next = Math.asin(Math.max(-1, Math.min(1, Math.sin(lat) * Math.cos(arc) + Math.cos(lat) * Math.sin(arc) * Math.cos(angle))))
      const longitude = Math.atan2(Math.sin(angle) * Math.sin(arc) * Math.cos(lat), Math.cos(arc) - Math.sin(lat) * Math.sin(next))
      ra = (ra + longitude / radians + 360) % 360
      dec = next / radians
      properMotionApplied = true
    }
    const pixel = skyToPixel(grid, {raDeg: ra, decDeg: dec})
    if (!pixel || !(pixel.x >= -.5 && pixel.x < grid.width - .5 && pixel.y >= -.5 && pixel.y < grid.height - .5)) return []
    return [{...source, ...pixel, raDeg: ra, decDeg: dec, properMotionApplied}]
  })
}

export function installAnalysis(api: AnalysisApi) {
  const trackRegion = $('track-controls')
  const catalogRegion = $('catalog-controls')
  const spectrumRegion = $('spectrum-controls')
  const coadd = action('Prepare within-visit coadd')
  const coaddCaption = statusLine()
  const coaddRegion = node('div')
  coaddRegion.className = 'detail-body'
  coaddRegion.append(coadd, coaddCaption)
  $('metadata').after(coaddRegion)
  const catalogLabels: Record<Catalog, string> = {gaia_dr3: 'Gaia DR3', allwise: 'AllWISE'}
  const selectedCatalogs = new Set<Catalog>()
  const catalogs = new Map<Catalog, Overlay>()
  const projections = new Map<string, Marker[]>()
  const attemptedCatalogs = new Set<Catalog>()
  const seenFrames = new Map<string, Frame>()
  const marks = new Map<Pane, PinnedMark>()
  let preview: Source[] = []
  let selectedCandidate: Candidate | undefined
  let tracked: Track | undefined
  let point: (Pixel & Sky) | undefined
  let series: string | undefined
  let spectrumFor: 'center' | 'point' | 'candidate' = 'center'
  let armed: Pane | 'spectrum' | undefined
  let cursor: Pixel | undefined
  let operation: AbortController | undefined
  let overlayJob: AbortController | undefined
  let overlayTimer = 0
  let activePair = ''
  let pendingShare = new URLSearchParams(location.search).get('marks')

  async function run(status: HTMLElement, stage: string, task: (signal: AbortSignal) => Promise<void>) {
    operation?.abort()
    overlayJob?.abort()
    const controller = new AbortController()
    operation = controller
    status.textContent = stage
    try { await task(controller.signal) }
    catch (error) {
      if (!controller.signal.aborted) status.textContent = cleanText(error)
    } finally {
      if (operation === controller) {
        operation = undefined
        scheduleCatalogs()
      }
    }
  }
  function pipelineVersion() {
    return (api.manifest() as (Manifest & {pipelineVersion?: string}) | undefined)?.pipelineVersion
  }
  function path(endpoint: string) {
    return '/api/v1/series/' + encodeURIComponent(api.manifest()!.seriesId) + '/' + endpoint
  }
  function panes(): [Pane, Frame | undefined][] { return [['a', api.shown()], ['b', api.paired()]] }
  function frameFor(pane: Pane) { return pane === 'a' ? api.shown() : api.paired() }

  const trackStatus = statusLine()
  const trackResults = node('div')
  const candidateList = node('div')
  const showForecast = node('input')
  showForecast.type = 'checkbox'
  const forecastLabel = label('Show forecast on sky image', showForecast)
  forecastLabel.hidden = true
  const markA = action('Place mark A')
  const markB = action('Place mark B')
  const clearMarks = action('Clear marks')
  const measure = action('Measure marks')
  const detect = action('Find sources')
  const detectSet = choose([['pair', 'Selected pair'], ['visits', 'Loaded visits (up to eight)']])
  const includeMarks = node('input')
  includeMarks.type = 'checkbox'
  trackRegion.append(actions(markA, markB, clearMarks, measure), label('Include the two marks in the share link', includeMarks),
    label('Source detection uses', detectSet), detect, trackStatus, candidateList, trackResults, forecastLabel)

  const catalogStatus = statusLine()
  const catalogRows = node('div')
  for (const catalog of Object.keys(catalogLabels) as Catalog[]) {
    const toggle = node('input')
    toggle.type = 'checkbox'
    toggle.addEventListener('change', () => {
      if (toggle.checked) { selectedCatalogs.add(catalog); attemptedCatalogs.delete(catalog) }
      else selectedCatalogs.delete(catalog)
      catalogStatus.textContent = ''
      api.redraw()
      showCatalogs()
      scheduleCatalogs()
    })
    catalogRegion.append(label(catalogLabels[catalog], toggle))
  }
  catalogRegion.append(catalogStatus, catalogRows)

  function projectedCatalog(catalog: Catalog, frame: Frame) {
    const current = catalogs.get(catalog)
    const grid = api.manifest()?.grid
    if (!current || !grid) return []
    const key = catalog === 'allwise' ? catalog : `${catalog}:${frame.frameId}`
    const existing = projections.get(key)
    if (existing) return existing
    const reference = current.referenceRows ?? current.markers
    const when = (Date.parse(frame.startUtc) + Date.parse(frame.endUtc)) / 2
    const markers = projectCatalog(reference, catalog, grid, when)
    if (projections.size >= 24) projections.delete(projections.keys().next().value!)
    projections.set(key, markers)
    return markers
  }

  function scheduleCatalogs() {
    window.clearTimeout(overlayTimer)
    if (operation || overlayJob || !series || ![...selectedCatalogs].some(catalog => !attemptedCatalogs.has(catalog))) return
    overlayTimer = window.setTimeout(() => void fetchCatalogs(), 350)
  }

  async function fetchCatalogs() {
    const frame = api.shown()
    if (!frame?.imageUrl || operation || overlayJob) return
    const controller = new AbortController()
    overlayJob = controller
    const errors: string[] = []
    try {
      for (const catalog of selectedCatalogs) {
        if (attemptedCatalogs.has(catalog) || controller.signal.aborted) continue
        attemptedCatalogs.add(catalog)
        catalogStatus.textContent = `Loading ${catalogLabels[catalog]}…`
        try {
          const {data} = await api.data<Overlay>(path('overlays'), controller.signal, {catalog, frameId: frame.frameId}, false)
          if (controller.signal.aborted) return
          catalogs.set(catalog, data)
          api.redraw()
          showCatalogs()
        } catch (error) {
          if (controller.signal.aborted) { attemptedCatalogs.delete(catalog); return }
          errors.push(`${catalogLabels[catalog]} · ${cleanText(error)}`)
        }
      }
      catalogStatus.textContent = errors.join(' ')
    } finally {
      if (overlayJob === controller) {
        overlayJob = undefined
        scheduleCatalogs()
      }
    }
  }

  function showCatalogs() {
    catalogRows.replaceChildren()
    const a = api.shown()
    if (!a) return
    for (const catalog of selectedCatalogs) {
      const layer = catalogs.get(catalog)
      if (!layer) continue
      const markers = projectedCatalog(catalog, a)
      const total = markers.length
      const details = node('details')
      const title = node('summary', `${catalogLabels[catalog]} · ${total} visible${layer.truncated ? ' · truncated query' : ''}`)
      const epoch = catalog === 'gaia_dr3' ? `Positions shown for observation on ${a.startUtc.slice(0, 10)} UTC` : layer.displayEpoch
      details.append(title, node('p', epoch), node('p', layer.positionMethod), link('Catalog documentation ↗', layer.sourceUrl))
      if (catalog === 'gaia_dr3' && markers.some(marker => !marker.properMotionApplied)) {
        details.append(node('p', 'Entries without a motion solution remain at the catalog position.'))
      }
      if (total) {
        const list = node('ul')
        for (const marker of markers) {
          list.append(node('li', `${marker.catalogId} · ${marker.raDeg.toFixed(6)}°, ${marker.decDeg.toFixed(6)}° · ${marker.referenceEpoch ?? 'epoch unspecified'}`))
        }
        details.append(list)
      }
      catalogRows.append(details)
    }
  }

  function titleFor(pane: Pane) {
    const frame = frameFor(pane)
    return frame ? `${pane.toUpperCase()} · ${frame.startUtc.slice(0,10)}` : pane.toUpperCase()
  }

  function toggleArm(target: typeof armed) {
    armed = armed === target ? undefined : target
    const grid = api.manifest()?.grid
    cursor = armed && grid ? {x: (grid.width - 1) / 2, y: (grid.height - 1) / 2} : undefined
    const frame = armed === 'b' ? 'frame-b' : 'frame-a'
    $('images').classList.toggle('marking', Boolean(armed))
    markA.setAttribute('aria-pressed', String(armed === 'a'))
    markB.setAttribute('aria-pressed', String(armed === 'b'))
    if (armed) $(frame).focus()
    api.redraw()
  }

  function saveMark(pixel: Pixel) {
    const grid = api.manifest()?.grid
    if (!grid || !armed) return
    const target = armed
    const bounded = {
      x: Math.min(grid.width - 1, Math.max(0, pixel.x)),
      y: Math.min(grid.height - 1, Math.max(0, pixel.y)),
    }
    if (target === 'spectrum') {
      point = {...bounded, ...pixelToSky(grid, bounded)}
      spectrumFor = 'point'
      spectrumTarget.value = 'point'
      refreshSpectrumTarget()
      spectrumStatus.textContent = `Selected ${point.raDeg.toFixed(6)}°, ${point.decDeg.toFixed(6)}° (ICRS).`
    } else {
      const frame = frameFor(target)
      if (frame) {
        marks.set(target, {frameId: frame.frameId, productId: frame.productId, sky: pixelToSky(grid, bounded), pixel: bounded})
        trackStatus.textContent = `Mark ${titleFor(target)} placed. Choose one mark on each view.`
      }
      clearTrack()
    }
    toggleArm(undefined)
    updateControls()
    updateShare()
  }

  for (const pane of ['a', 'b'] as const) {
    const frame = $(`frame-${pane}`)
    const canvas = $<HTMLCanvasElement>(`canvas-${pane}`)
    frame.addEventListener('click', event => {
      if (armed !== pane && !(pane === 'a' && armed === 'spectrum')) return
      const pixel = api.position(event, canvas)
      if (pixel) saveMark(pixel)
    })
    frame.addEventListener('keydown', event => {
      if (!cursor || (armed !== pane && !(pane === 'a' && armed === 'spectrum'))) return
      const grid = api.manifest()?.grid
      if (!grid) return
      const vectors: Record<string, [number, number]> = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowDown: [0, -1], ArrowUp: [0, 1]}
      if (vectors[event.key]) {
        event.preventDefault()
        event.stopImmediatePropagation()
        const [dx, dy] = vectors[event.key]
        cursor.x = Math.min(grid.width - 1, Math.max(0, cursor.x + dx))
        cursor.y = Math.min(grid.height - 1, Math.max(0, cursor.y + dy))
        api.redraw()
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        event.stopImmediatePropagation()
        saveMark(cursor)
      } else if (event.key === 'Escape') {
        event.stopImmediatePropagation()
        toggleArm(undefined)
      }
    }, {capture: true})
  }

  function updateShare() {
    const picked = [...marks.values()].map(mark => ({productId: mark.productId, sky: mark.sky, pixel: mark.pixel}))
    api.shareMarks(includeMarks.checked && picked.length && api.manifest() ? JSON.stringify({
      pipelineVersion: pipelineVersion(), marks: picked,
    }) : undefined)
  }

  function restoreShare() {
    if (!pendingShare) return
    try {
      const pinned = JSON.parse(pendingShare) as {pipelineVersion: string; marks: Omit<PinnedMark, 'frameId'>[]}
      if ((pinned.pipelineVersion && pinned.pipelineVersion !== pipelineVersion()) || !Array.isArray(pinned.marks) || pinned.marks.length > 2) {
        throw new Error('Unsupported marker version')
      }
      const remaining = []
      const grid = api.manifest()!.grid
      for (const pin of pinned.marks) {
        if (!pin || typeof pin.productId !== 'string' || !isSciencePoint(pin.pixel)
            || pin.pixel.x < 0 || pin.pixel.x >= grid.width || pin.pixel.y < 0 || pin.pixel.y >= grid.height) {
          throw new Error('Invalid marker')
        }
        const match = panes().find(([, frame]) => frame?.productId === pin.productId)
        if (match) {
          const [pane, frame] = match
          marks.set(pane, {frameId: frame!.frameId, productId: pin.productId, sky: pixelToSky(grid, pin.pixel), pixel: pin.pixel})
          includeMarks.checked = true
        } else remaining.push(pin)
      }
      if (remaining.length) trackStatus.textContent = 'A pinned mark is waiting for its matching exposure to be selected.'
      else {
        pendingShare = null
        updateShare()
      }
    } catch {
      trackStatus.textContent = 'The shared marks could not be restored to this field.'
      pendingShare = null
    }
  }

  function clearTrack() {
    tracked = undefined
    forecastLabel.hidden = true
    showForecast.checked = false
    trackResults.replaceChildren()
  }

  function renderTrack(result: Track) {
    tracked = result
    trackResults.replaceChildren()
    const summary = node('dl')
    for (const [term, value] of [
      ['Angular separation', `${format(result.separationArcsec)} ± ${format(result.uncertaintyArcsec)} arcsec`],
      ['Elapsed time', `${format(result.baselineDays, 5)} days`],
      ['Position angle', finite(result.positionAngleDeg) ? `${format(result.positionAngleDeg)}° east of north` : 'Undefined'],
      ['Average apparent rate', `${format(result.rateArcsecPerDay)} arcsec/day`],
    ]) summary.append(node('dt', term), node('dd', value))
    trackResults.append(summary)
    const measurementList = node('ul')
    for (const measure of result.measurements) {
      measurementList.append(node('li', `${measure.timeUtc} · ${measure.raDeg.toFixed(6)}°, ${measure.decDeg.toFixed(6)}° · ${measure.method} · ${measure.productId ?? ''}`))
    }
    const observations = node('details')
    observations.append(node('summary', 'Measurement coordinates & provenance'), measurementList)
    trackResults.append(observations)
    if (result.forecast) {
      forecastLabel.hidden = false
      trackResults.append(node('p', `${result.forecast.model} over ${format(result.forecast.horizonDays)} days. ${result.forecast.uncertainty}.`))
    } else {
      forecastLabel.hidden = true
      showForecast.checked = false
      trackResults.append(node('p', result.forecastReason))
    }
    api.redraw()
  }

  markA.onclick = () => {
    trackStatus.textContent = 'Choose a position on image A, or use the arrow keys and press Enter.'
    toggleArm('a')
  }
  markB.onclick = () => {
    trackStatus.textContent = 'Choose a position on image B, or use the arrow keys and press Enter.'
    toggleArm('b')
  }
  clearMarks.onclick = () => {
    marks.clear()
    clearTrack()
    trackStatus.textContent = ''
    toggleArm(undefined)
    updateShare()
    updateControls()
  }
  includeMarks.onchange = updateShare
  showForecast.onchange = api.redraw
  const showMotion = node('input')
  showMotion.type = 'checkbox'
  const motionLabel = label('Show measured motion arrow', showMotion)
  motionLabel.hidden = true
  trackRegion.append(motionLabel)
  showMotion.onchange = api.redraw

  measure.onclick = () => {
    const selected = [...marks.values()].map(({frameId, pixel}) => ({frameId, pixel}))
    if (selected.length !== 2) return
    void run(trackStatus, 'Measuring angular separation…', async signal => {
      const {data} = await api.data<Track>(path('tracks'), signal, {marks: selected}, false)
      if (signal.aborted) return
      renderTrack(data)
      motionLabel.hidden = false
      trackStatus.textContent = ''
    })
  }

  function loadedVisits() {
    const result: Frame[] = []
    const visits = new Set<string>()
    for (const frame of [api.shown(), api.paired(), ...seenFrames.values(), ...(api.manifest()?.frames ?? [])]) {
      if (!frame?.imageUrl || !frame.visitId || visits.has(frame.visitId)) continue
      if (api.shown() && frame.detector !== api.shown()!.detector) continue
      visits.add(frame.visitId)
      result.push(frame)
      if (result.length === 8) break
    }
    return result
  }

  function prepareTargets() {
    const manifest = api.manifest()
    const frame = api.shown()
    if (!manifest || !frame) return []
    const loaded = loadedVisits()
    const targets: Frame[] = []
    const pool = manifest.frames.filter(item => item.visitId && item.detector === frame.detector && !item.imageUrl)
    const chosen = new Set(loaded.map(item => item.visitId))
    const times = loaded.map(item => Date.parse(item.startUtc))
    const timeOf = (item: Frame) => Date.parse(item.startUtc)
    const distance = (item: Frame) => Math.min(...times.map(time => Math.abs(time - timeOf(item))))
    const ranked = pool.filter(item => !chosen.has(item.visitId))
    while (targets.length < 3 && targets.length + loaded.length < 8 && ranked.length) {
      ranked.sort((a, b) => distance(b) - distance(a) || a.startUtc.localeCompare(b.startUtc))
      const target = ranked.find(item => !chosen.has(item.visitId))
      if (!target) break
      targets.push(target)
      chosen.add(target.visitId)
      times.push(timeOf(target))
    }
    return targets
  }

  const prepareVisits = action('Prepare dates for tracking')
  const stopVisits = action('Stop preparing')
  const visitList = node('p')
  const visitStatus = statusLine()
  let stopPreparing = false
  stopVisits.hidden = true
  trackRegion.append(visitList, actions(prepareVisits, stopVisits), visitStatus)
  stopVisits.onclick = () => {
    stopPreparing = true
    stopVisits.disabled = true
  }
  prepareVisits.onclick = () => {
    const targets = prepareTargets()
    if (!targets.length) return
    stopPreparing = false
    stopVisits.hidden = false
    stopVisits.disabled = false
    prepareVisits.disabled = true
    void run(visitStatus, 'Preparing independent visits…', async signal => {
      const failed: string[] = []
      let count = 0
      try {
        for (const candidate of targets) {
          if (stopPreparing || signal.aborted) break
          visitStatus.textContent = `Preparing ${candidate.startUtc.slice(0, 10)} · ${count} of ${targets.length} ready…`
          try {
            const frame = await api.prepare(candidate, signal)
            if (signal.aborted) return
            if (frame.imageUrl) { seenFrames.set(frame.frameId, frame); count++ }
          } catch (error) {
            if (signal.aborted) return
            failed.push(`${candidate.startUtc.slice(0, 10)} · ${cleanText(error)}`)
          }
        }
        visitStatus.textContent = `${count} additional visits ready.${failed.length ? ' ' + failed.join(' · ') : ''}`
        detectSet.value = 'visits'
      } finally {
        stopVisits.hidden = true
        updateControls()
      }
    })
  }

  function applySource(source: Source, pane: Pane) {
    const frame = frameFor(pane)
    const grid = api.manifest()?.grid
    if (!frame || !grid) return
    marks.set(pane, {
      frameId: source.frameId, pixel: source.pixel, sky: pixelToSky(grid, source.pixel), productId: frame.productId,
    })
    clearTrack()
    trackStatus.textContent = `Mark ${pane.toUpperCase()} snapped to the detected centroid.`
    updateShare()
    updateControls()
    api.redraw()
  }

  function renderCandidates(result: Detections, warnings: string[]) {
    candidateList.replaceChildren()
    preview = []
    selectedCandidate = undefined
    clearTrack()
    const info = [...distinctWarnings(result.warnings ?? [], warnings)]
    if (!result.candidates.length) candidateList.append(node('p', 'No ranked change candidate passed the quality gate.'))
    for (const warning of info) candidateList.append(node('p', warning))
    for (const [index, candidate] of result.candidates.slice(0, 8).entries()) {
      const item = node('details')
      const focus = action('Highlight in the field')
      const model = action('Measure candidate')
      const dismiss = action('Dismiss candidate')
      focus.onclick = () => {
        selectedCandidate = candidate
        preview = candidate.marks
        refreshSpectrumTarget()
        api.redraw()
      }
      model.onclick = () => {
        focus.click()
        void run(trackStatus, 'Measuring linked observations…', async signal => {
          const {data} = await api.data<Track>(path('tracks'), signal, {candidateId: candidate.candidateId}, false)
          if (signal.aborted) return
          renderTrack(data)
          motionLabel.hidden = false
          trackStatus.textContent = ''
        })
      }
      dismiss.onclick = () => {
        item.remove()
        if (selectedCandidate === candidate) {
          selectedCandidate = undefined
          preview = []
          clearTrack()
          refreshSpectrumTarget()
          api.redraw()
        }
      }
      item.append(node('summary', `${index + 1}. ${candidate.label} · score ${format(candidate.score)}`), node('p', candidate.reason),
        actions(focus, model, dismiss))
      for (const [pane, frame] of panes()) {
        const match = candidate.marks.find(mark => mark.frameId === frame?.frameId)
        if (!match) continue
        const snap = action(`Use centroid for mark ${pane.toUpperCase()}`)
        snap.onclick = () => applySource(match, pane)
        item.append(snap)
      }
      candidateList.append(item)
    }
    for (const [pane, frame] of panes()) {
      const catalog = result.sources.find(item => item.frameId === frame?.frameId)
      if (!catalog?.sources.length) continue
      const details = node('details')
      details.append(node('summary', `Detected centroids · ${titleFor(pane)}`))
      for (const [index, source] of catalog.sources.slice(0, 10).entries()) {
        const chooseSource = action(`Use centroid ${index + 1} for ${pane.toUpperCase()} · S/N ${format(source.snr)}`)
        chooseSource.onclick = () => applySource(source, pane)
        details.append(chooseSource)
      }
      candidateList.append(details)
    }
    refreshSpectrumTarget()
    api.redraw()
  }

  detect.onclick = () => {
    const frames = detectSet.value === 'pair' ? [api.shown(), api.paired()] : loadedVisits()
    const ordered = frames.filter((frame): frame is Frame => Boolean(frame?.imageUrl))
    if (new Set(ordered.map(frame => frame.visitId)).size < 2) {
      trackStatus.textContent = 'Prepare at least two independent visits before detecting sources.'
      return
    }
    void run(trackStatus, 'Finding sources in prepared images…', async signal => {
      const response = await api.data<Detections>(path('detections'), signal, {frameIds: ordered.map(frame => frame.frameId)}, false)
      if (signal.aborted) return
      renderCandidates(response.data, response.warnings)
      trackStatus.textContent = `${response.data.candidates.length} ranked candidates`
    })
  }

  coadd.onclick = () => {
    const frame = api.shown()
    if (!frame) return
    void run(coaddCaption, 'Preparing wavelength-matched exposures from this visit…', async signal => {
      const merged = await api.prepare(frame, signal, 'coadd')
      if (signal.aborted) return
      await api.showPrepared(merged)
      coaddCaption.textContent = merged.warnings?.join(' ') ?? 'Within-visit coadd is displayed.'
    })
  }

  const spectrumTarget = choose([['center', 'Field center'], ['point', 'Picked sky position'], ['candidate', 'Active detected candidate']])
  const spectrumMode = choose([['quick', 'Quick exposure spectrum'], ['extended', 'Extended exposure spectrum'], ['coadded_cube', 'DR1 coadded cube context']])
  const spectrumMethod = choose([['aperture', 'Aperture photometry'], ['epsf', 'Effective PSF']])
  const spectrumMethodLabel = label('Photometry method', spectrumMethod)
  const pickSpectrum = action('Pick a sky position')
  const computeSpectrum = action('Extract spectrum')
  const spectrumStatus = statusLine()
  const spectrumOutput = node('div')
  const range = node('details')
  range.append(node('summary', 'Limit extraction'))
  const start = node('input'), end = node('input'), low = node('input'), high = node('input')
  start.type = end.type = 'date'
  low.type = high.type = 'number'
  for (const field of [low, high]) { field.min = '0.7'; field.max = '5.1'; field.step = 'any' }
  const dates = node('div')
  dates.append(label('From (UTC)', start), label('Through (UTC)', end))
  range.append(dates, label('Min wavelength (µm)', low), label('Max wavelength (µm)', high))
  spectrumRegion.append(label('Extract at', spectrumTarget), pickSpectrum, label('Spectrum source', spectrumMode),
    spectrumMethodLabel, range, computeSpectrum, spectrumStatus, spectrumOutput)

  function refreshSpectrumTarget() {
    const isCube = spectrumMode.value === 'coadded_cube'
    spectrumMethodLabel.hidden = dates.hidden = isCube
    spectrumTarget.options[1].disabled = !point
    spectrumTarget.options[2].disabled = !selectedCandidate || isCube
    if (spectrumTarget.selectedOptions[0]?.disabled) spectrumTarget.value = 'center'
    spectrumFor = spectrumTarget.value as typeof spectrumFor
  }
  spectrumTarget.onchange = refreshSpectrumTarget
  spectrumMode.onchange = refreshSpectrumTarget
  pickSpectrum.onclick = () => {
    spectrumStatus.textContent = 'Choose a position on image A, or use the arrow keys and press Enter.'
    toggleArm('spectrum')
  }
  computeSpectrum.onclick = () => {
    const result = api.manifest()
    if (!result) return
    const {raDeg, decDeg} = result.query
    const wave = low.value || high.value ? [Number(low.value || '0.7'), Number(high.value || '5.1')] : undefined
    if (wave && (!wave.every(value => Number.isFinite(value) && value >= .7 && value <= 5.1) || wave[0] > wave[1])) {
      spectrumStatus.textContent = 'Use an ordered wavelength range between 0.7 and 5.1 µm.'
      return
    }
    const body: Record<string, unknown> = {mode: spectrumMode.value, method: spectrumMethod.value}
    if (wave) body.wavelengthRange = wave
    if (spectrumMode.value !== 'coadded_cube' && (start.value || end.value)) {
      const first = start.value || result.query.start
      const last = end.value || result.query.end
      if (!first || !last || first > last) {
        spectrumStatus.textContent = 'Choose an ordered UTC date range.'
        return
      }
      body.timeRange = {start: first, end: last}
    }
    if (spectrumFor === 'candidate' && selectedCandidate) body.candidateId = selectedCandidate.candidateId
    else body.selectedSkyPosition = spectrumFor === 'point' && point ? {raDeg: point.raDeg, decDeg: point.decDeg} : {raDeg, decDeg}
    void run(spectrumStatus, 'Extracting spectra in the requested bounds…', async signal => {
      const response = await api.data<Spectrum>(path('spectra'), signal, body, false)
      if (signal.aborted) return
      spectrumStatus.textContent = response.status === 'partial' ? 'Partial spectrum. Unavailable bins are listed below.' : 'Spectrum ready.'
      displaySpectrum(response.data, response.warnings)
    })
  }

  function displaySpectrum(spectrum: Spectrum, warnings: string[]) {
    spectrumOutput.replaceChildren()
    const samples = spectrum.samples
    const usable = samples.filter(sample => sample.sampleStatus === 'measured' && finite(sample.wavelengthUm) && finite(sample.flux))
    spectrumOutput.append(node('p', spectrum.mode === 'coadded_cube' ?
      'DR1 coadded spectral context. Channels have no individual observation date.' :
      'Exposure spectrum. Each sample has its own observation date.'))
    if (usable.length) spectrumOutput.append(plotSpectrum(samples, spectrum.units))
    else spectrumOutput.append(node('p', 'No measured spectral samples are available in these bounds.'))
    for (const warning of distinctWarnings(spectrum.warnings ?? [], warnings)) spectrumOutput.append(node('p', warning))
    const table = node('table')
    table.className = 'sample-table'
    const headers = node('thead'), header = node('tr')
    for (const name of ['Wavelength', `Flux (${spectrum.units})`, 'Observation / quality']) {
      const th = node('th', name)
      th.scope = 'col'
      header.append(th)
    }
    headers.append(header)
    table.append(headers)
    const rows = node('tbody')
    for (const sample of samples) {
      const row = node('tr')
      const wave = sample.wavelengthUm == null ? '—' :
        `${format(sample.wavelengthUm, 4)} µm${finite(sample.bandwidthUm) ? ' · Δ' + format(sample.bandwidthUm) : ''}`
      const flux = finite(sample.flux) ?
        `${format(sample.flux)}${finite(sample.error) ? ' ± ' + format(sample.error) : ''}` : '—'
      const quality = [sample.startUtc ?? (sample.channel != null ? `Channel ${sample.channel}` : ''), sample.reason, sample.productId]
        .filter(Boolean).join(' · ')
      row.append(node('td', wave), node('td', flux), node('td', quality))
      rows.append(row)
    }
    table.append(rows)
    const details = node('details')
    details.append(node('summary', `Spectral samples (${samples.length})`), table)
    spectrumOutput.append(details, link('IRSA spectrum reference ↗', spectrum.referenceUrl))
  }

  function updateControls() {
    const a = api.shown(), b = api.paired()
    for (const pane of ['track-panel', 'catalog-panel', 'spectrum-panel']) $(pane).hidden = !a
    coaddRegion.hidden = !a
    coadd.disabled = !a || a.representation === 'coadd'
    markA.disabled = !a
    markB.disabled = !b || Boolean($('frame-b').hidden)
    markA.title = `Place a mark on ${titleFor('a')}`
    markB.title = markB.disabled ? 'Open Side by side to place a mark on image B.' : `Place a mark on ${titleFor('b')}`
    measure.disabled = marks.size !== 2 || !a || !b || a.visitId === b.visitId
    clearMarks.disabled = marks.size === 0
    const targets = prepareTargets()
    prepareVisits.disabled = !targets.length || !stopVisits.hidden
    visitList.textContent = targets.length ? `Up to ${targets.length} more visits · ${targets.map(frame => frame.startUtc.slice(0, 10)).join(', ')}` : ''
    computeSpectrum.disabled = !a
    pickSpectrum.disabled = !a
  }

  function joinMarkers(first: HTMLElement | void, last: HTMLElement | void, css: string) {
    if (!first || !last || first.parentElement !== last.parentElement) return
    const from = first.getBoundingClientRect(), to = last.getBoundingClientRect()
    const area = first.parentElement!.getBoundingClientRect()
    const deltaX = to.left + to.width / 2 - from.left - from.width / 2
    const deltaY = to.top + to.height / 2 - from.top - from.height / 2
    const line = node('span')
    line.className = 'analysis-line ' + css
    line.style.left = `${from.left + from.width / 2 - area.left}px`
    line.style.top = `${from.top + from.height / 2 - area.top}px`
    line.style.width = `${Math.hypot(deltaX, deltaY)}px`
    line.style.transform = `rotate(${Math.atan2(deltaY, deltaX)}rad)`
    first.parentElement!.append(line)
  }

  function redraw() {
    for (const [pane, frame] of panes()) {
      if (!frame || (pane === 'b' && $('frame-b').hidden)) continue
      for (const catalog of selectedCatalogs) {
        for (const marker of projectedCatalog(catalog, frame)) {
          api.mark(pane, marker.x, marker.y, catalog, `${catalogLabels[catalog]} ${marker.catalogId}`)
        }
      }
      const placed = marks.get(pane)
      if (placed?.frameId === frame.frameId) api.mark(pane, placed.pixel.x, placed.pixel.y, 'analysis-mark', `Marker ${pane.toUpperCase()}`)
      for (const source of preview) {
        if (source.frameId === frame.frameId) api.mark(pane, source.pixel.x, source.pixel.y, 'analysis-candidate', selectedCandidate?.label)
      }
      const keyboardCursor = armed === pane || (armed === 'spectrum' && pane === 'a')
      if (cursor && keyboardCursor) api.mark(pane, cursor.x, cursor.y, 'analysis-cursor', 'Mark cursor')
    }
    if (point) api.mark('a', point.x, point.y, 'analysis-spectrum', 'Spectrum extraction position')
    if (showMotion.checked && tracked && tracked.measurements.length >= 2) {
      const first = tracked.measurements[0], last = tracked.measurements.at(-1)!
      joinMarkers(api.mark('a', first.pixel.x, first.pixel.y, 'analysis-motion-point', 'Measured start'),
        api.mark('a', last.pixel.x, last.pixel.y, 'analysis-motion-point', 'Measured end'), 'analysis-motion')
    }
    if (showForecast.checked && tracked?.forecast) {
      let previous: HTMLElement | void = undefined
      for (const sample of tracked.forecast.samples) {
        const marker = api.mark('a', sample.x, sample.y, 'analysis-forecast', `${sample.timeUtc} · approximate 95% radius ${format(sample.ellipse95Arcsec)}″`)
        joinMarkers(previous, marker, 'analysis-prediction')
        previous = marker
      }
    }
  }

  function changed() {
    const next = api.manifest()?.seriesId
    if (next !== series) {
      series = next
      operation?.abort()
      overlayJob?.abort()
      marks.clear()
      catalogs.clear()
      projections.clear()
      attemptedCatalogs.clear()
      seenFrames.clear()
      candidateList.replaceChildren()
      spectrumOutput.replaceChildren()
      trackStatus.textContent = coaddCaption.textContent = catalogStatus.textContent = spectrumStatus.textContent = visitStatus.textContent = ''
      preview = []
      selectedCandidate = undefined
      point = undefined
      clearTrack()
      toggleArm(undefined)
      refreshSpectrumTarget()
    }
    const a = api.shown(), b = api.paired()
    for (const frame of [a, b]) if (frame?.imageUrl) seenFrames.set(frame.frameId, frame)
    const pair = `${a?.frameId}:${b?.frameId}`
    if (pair !== activePair) {
      activePair = pair
      clearTrack()
      motionLabel.hidden = true
      showMotion.checked = false
      candidateList.replaceChildren()
      selectedCandidate = undefined
      preview = []
      refreshSpectrumTarget()
    }
    for (const [pane, frame] of panes()) {
      if (marks.get(pane) && marks.get(pane)?.frameId !== frame?.frameId) marks.delete(pane)
    }
    if (a && pendingShare) restoreShare()
    else if (a) updateShare()
    showCatalogs()
    updateControls()
    api.redraw()
    scheduleCatalogs()
  }

  document.addEventListener('spherex-redraw', () => {
    markB.disabled = !api.paired() || Boolean($('frame-b').hidden)
    redraw()
  })
  document.addEventListener('spherex-frame', changed)
  document.addEventListener('spherex-pair', changed)
  refreshSpectrumTarget()
  changed()
}

function plotSpectrum(samples: SpectrumSample[], units: string) {
  const plot = node('canvas')
  plot.className = 'spectrum-plot'
  plot.width = 600
  plot.height = 340
  plot.setAttribute('role', 'img')
  plot.setAttribute('aria-label', `Spectral flux in ${units} by wavelength. See the sample table for precise values and missing channels.`)
  const context = plot.getContext('2d')!
  const measured = samples.filter(sample => finite(sample.wavelengthUm) && finite(sample.flux))
  const wavelengths = samples.map(sample => sample.wavelengthUm).filter(finite)
  const left = 80, right = 576, top = 26, bottom = 272
  const minWave = Math.min(...wavelengths)
  const waveSpan = Math.max(.02, Math.max(...wavelengths) - minWave)
  const fluxes = measured.flatMap(sample => [sample.flux! - (sample.error ?? 0), sample.flux! + (sample.error ?? 0)])
  const minFlux = Math.min(...fluxes)
  const fluxSpan = Math.max(1e-7, Math.max(...fluxes) - minFlux)
  const x = (value: number) => left + 12 + (right - left - 24) * (value - minWave) / waveSpan
  const y = (value: number) => bottom - 12 - (bottom - top - 24) * (value - minFlux) / fluxSpan
  context.font = '20px system-ui'
  context.fillStyle = '#b9c7d9'
  context.fillText(units, left, top)
  context.fillText('Wavelength (µm)', 230, 324)
  context.strokeStyle = '#50617a'
  context.beginPath()
  context.moveTo(left, top + 8)
  context.lineTo(left, bottom)
  context.lineTo(right, bottom)
  context.stroke()
  for (const value of [minWave, minWave + waveSpan]) context.fillText(format(value), x(value) - 14, bottom + 26)
  for (const value of [minFlux, minFlux + fluxSpan]) context.fillText(format(value), 3, y(value) + 7)
  for (const sample of samples) {
    if (!finite(sample.wavelengthUm)) continue
    const column = x(sample.wavelengthUm)
    if (!finite(sample.flux)) {
      context.fillStyle = '#ebad86'
      context.fillRect(column - 1, bottom - 7, 3, 7)
      continue
    }
    const row = y(sample.flux)
    context.fillStyle = '#87e3e8'
    context.strokeStyle = '#87e3e8'
    if (finite(sample.error)) {
      context.beginPath()
      context.moveTo(column, y(sample.flux - sample.error))
      context.lineTo(column, y(sample.flux + sample.error))
      context.stroke()
    }
    context.beginPath()
    context.arc(column, row, 3.5, 0, 2 * Math.PI)
    context.fill()
  }
  return plot
}
