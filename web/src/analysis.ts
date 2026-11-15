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
type PinnedMark = Mark & {productId: string; sky: Sky; centroidPixel?: Pixel}
type CatalogMatches = {
  catalog: Catalog; radiusArcsec: number; ambiguous: boolean; truncated: boolean
  matches: {
    catalogId: string; separationArcsec: number; observationUtc: string; referenceEpoch: number | string | null
    comparisonEpoch: string; properMotionApplied: boolean; matchedVisits: number
  }[]
}
type Candidate = {candidateId: string; label: string; reason: string; marks: Source[]; score: number; catalogMatches?: CatalogMatches[]}
type ResidualGroup = Sky & {
  frameA: string; frameB: string; timeA: string; timeB: string
  sign: 'positive' | 'negative'; pixel: Pixel; snr: number
}
type Detections = {
  candidates: Candidate[]; sources: {frameId: string; sources: Source[]}[]; residualGroups?: ResidualGroup[]; warnings: string[]
}
type Forecast = {
  horizonDays: number; model: string; uncertainty: string
  samples: (Pixel & {timeUtc: string; ellipse95Arcsec: number})[]
}
type Track = {
  measurements: (Mark & Sky & {
    timeUtc: string; productId?: string; sigmaArcsec: number; method: string
    originalPixel?: Pixel; covariancePx2?: number[][]
  })[]
  baselineDays: number; separationArcsec: number; uncertaintyArcsec: number; positionAngleDeg: number | null
  rateArcsecPerDay: number; forecastReason: string; forecast: Forecast | null
}
type SpectrumSample = {
  wavelengthUm: number | null; flux?: number | null; units?: string; error?: number | null; startUtc: string | null
  sampleStatus: 'measured' | 'missing'; reason?: string; channel?: number; productId?: string; bandwidthUm?: number
  detector?: number; visitId?: string
}
type Spectrum = {samples: SpectrumSample[]; mode: string; units: string; referenceUrl: string; archiveDoi?: string; warnings: string[]}

export type AnalysisApi = {
  manifest(): Manifest | undefined
  shown(): Frame | undefined
  paired(): Frame | undefined
  displayed?(target: Pane): Frame | undefined
  displayMode?(): string
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
const measuredSpectrumSample = (sample: SpectrumSample) => sample.sampleStatus === 'measured' && finite(sample.flux)
const cleanText = (problem: unknown) => problem instanceof Error ? problem.message : 'The operation did not complete.'
const distinctWarnings = (...warnings: string[][]) => [...new Set(warnings.flat())]
const isSciencePoint = (value: unknown): value is Pixel => {
  const point = value as Pixel | undefined
  return Boolean(point && finite(point.x) && finite(point.y))
}
const insideGrid = (point: unknown, grid: Manifest['grid']): point is Pixel =>
  isSciencePoint(point) && point.x >= 0 && point.x < grid.width && point.y >= 0 && point.y < grid.height
const residualSign = (group: ResidualGroup) => group.sign === 'positive' ? 'Brighter in B (+)' : 'Fainter in B (−)'

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
  const catalogHelp: Record<Catalog, string> = {
    gaia_dr3: 'The European Space Agency’s third Gaia data release maps stars. Green circles show their catalog positions, adjusted to the image date when motion is available.',
    allwise: 'NASA’s WISE infrared survey measured these sources in 2010–2011. Pink squares show their historical catalog positions.',
  }
  const selectedCatalogs = new Set<Catalog>()
  const catalogs = new Map<Catalog, Overlay>()
  const projections = new Map<string, Marker[]>()
  const attemptedCatalogs = new Set<Catalog>()
  const seenFrames = new Map<string, Frame>()
  const marks = new Map<Pane, PinnedMark>()
  let preview: Source[] = []
  let highlightedResidual: ResidualGroup | undefined
  let selectedCandidate: Candidate | undefined
  let tracked: Track | undefined
  let point: (Pixel & Sky) | undefined
  let series: string | undefined
  let spectrumFor: 'center' | 'point' | 'candidate' = 'center'
  let armed: Pane | 'spectrum' | undefined
  let cursor: Pixel | undefined
  let operation: AbortController | undefined
  let operationScope: 'pair' | 'series'
  let overlayJob: AbortController | undefined
  let overlayTimer = 0
  let activePair = ''
  let pendingShare = new URLSearchParams(location.search).get('marks')

  async function run(status: HTMLElement, stage: string, task: (signal: AbortSignal) => Promise<void>, scope: 'pair' | 'series' = 'pair') {
    operation?.abort()
    overlayJob?.abort()
    const controller = new AbortController()
    operation = controller
    operationScope = scope
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
    return api.manifest()?.pipelineVersion
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
    const row = node('div')
    row.className = 'catalog-toggle'
    const choice = label(catalogLabels[catalog], toggle)
    const marker = node('span')
    marker.className = `catalog-key ${catalog}`
    marker.setAttribute('aria-hidden', 'true')
    choice.prepend(marker, toggle)
    const help = node('div')
    help.className = 'context-help'
    const info = action('?')
    info.className = 'info-button'
    info.setAttribute('aria-label', `About ${catalogLabels[catalog]}`)
    info.setAttribute('aria-expanded', 'false')
    const description = node('p', catalogHelp[catalog])
    description.id = `catalog-help-${catalog}`
    description.className = 'help-bubble'
    description.setAttribute('role', 'tooltip')
    info.setAttribute('aria-describedby', description.id)
    info.onclick = () => {
      const pinned = info.getAttribute('aria-expanded') === 'true'
      info.setAttribute('aria-expanded', String(!pinned))
      help.dataset.dismissed = String(pinned)
    }
    info.onkeydown = event => {
      if (event.key !== 'Escape') return
      info.setAttribute('aria-expanded', 'false')
      help.dataset.dismissed = 'true'
    }
    help.onpointerleave = () => { delete help.dataset.dismissed }
    info.onblur = () => { delete help.dataset.dismissed }
    help.append(info, description)
    row.append(choice, help)
    catalogRegion.append(row)
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
    api.shareMarks(includeMarks.checked && marks.size && api.manifest() ? JSON.stringify({
      pipelineVersion: pipelineVersion(), marks: [...marks.values()],
    }) : undefined)
  }

  function restoreShare() {
    if (!pendingShare) return
    try {
      const pinned = JSON.parse(pendingShare) as {pipelineVersion: string; marks: (Omit<PinnedMark, 'frameId'> & {frameId?: string})[]}
      if ((pinned.pipelineVersion && pinned.pipelineVersion !== pipelineVersion()) || !Array.isArray(pinned.marks) || pinned.marks.length > 2) {
        throw new Error('Unsupported marker version')
      }
      const remaining = []
      const grid = api.manifest()!.grid
      for (const pin of pinned.marks) {
        const exactFrame = typeof pin?.frameId === 'string' && /^[\w-]{1,80}$/.test(pin.frameId)
        if (!pin || typeof pin.productId !== 'string' || (pin.frameId !== undefined && !exactFrame) || !insideGrid(pin.pixel, grid)
            || (pin.centroidPixel !== undefined && (!exactFrame || !pinned.pipelineVersion || !insideGrid(pin.centroidPixel, grid)))) {
          throw new Error('Invalid marker')
        }
        const match = panes().find(([, frame]) => frame && frame.productId === pin.productId && (!pin.frameId || frame.frameId === pin.frameId))
        if (match) {
          const [pane, frame] = match
          marks.set(pane, {frameId: frame!.frameId, productId: pin.productId, sky: pixelToSky(grid, pin.pixel),
            pixel: pin.pixel, centroidPixel: pin.centroidPixel})
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
    motionLabel.hidden = true
    showMotion.checked = false
    trackResults.replaceChildren()
  }

  function renderTrack(result: Track, selectedMarks: PinnedMark[] = []) {
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
      const entry = node('li', `${measure.timeUtc} · ${measure.raDeg.toFixed(6)}°, ${measure.decDeg.toFixed(6)}° · ${measure.method} · ${measure.productId ?? measure.frameId}`)
      entry.append(node('p', `Position uncertainty ${format(measure.sigmaArcsec)}″`))
      if (measure.originalPixel) {
        const coordinates = (pixel: Pixel) => `(${format(pixel.x, 6)}, ${format(pixel.y, 6)})`
        entry.append(node('p', `Original mark ${coordinates(measure.originalPixel)} · Measured centroid ${coordinates(measure.pixel)} · Image pixels`))
      }
      if (measure.covariancePx2) {
        const matrix = measure.covariancePx2.map(row => `[${row.map(value => format(value, 4)).join(', ')}]`).join(' ')
        entry.append(node('p', `Centroid covariance ${matrix} px²`))
      }
      measurementList.append(entry)
    }
    const download = action('Download measurements')
    download.onclick = () => {
      const manifest = api.manifest()
      if (!manifest) return
      const sourceFrames = result.measurements.map(measurement => {
        const frame = seenFrames.get(measurement.frameId) ?? manifest.frames.find(frame => frame.frameId === measurement.frameId)
        return {
          frameId: measurement.frameId, productId: measurement.productId ?? frame?.productId,
          archiveUrl: frame?.archiveUrl, archiveDoi: frame?.archiveDoi, release: frame?.release,
        }
      })
      const payload = {
        schemaVersion: 1, pipelineVersion: pipelineVersion(), seriesId: manifest.seriesId,
        dataCredit: 'NASA SPHEREx mission · NASA/IPAC Infrared Science Archive',
        query: manifest.query, grid: manifest.grid, sourceFrames, marks: selectedMarks, ...result,
      }
      const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'}))
      const file = node('a')
      file.href = url
      file.download = 'spherex-measurements.json'
      file.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
    const observations = node('details')
    observations.append(node('summary', 'Measurement coordinates & provenance'), measurementList, download)
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
    if (api.shown()?.visitId === api.paired()?.visitId) return
    const selected = [...marks.values()]
    if (selected.length !== 2) return
    void run(trackStatus, 'Measuring angular separation…', async signal => {
      const requestMarks = selected.map(({frameId, pixel, centroidPixel}) => ({frameId, pixel, centroidPixel}))
      const {data} = await api.data<Track>(path('tracks'), signal, {marks: requestMarks}, false)
      if (signal.aborted || selected.some(mark => ![...marks.values()].includes(mark))) return
      renderTrack(data, selected)
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
    if (!frame || source.frameId !== frame.frameId || !grid || !insideGrid(source.pixel, grid)) return
    const previous = marks.get(pane)
    const pixel = previous?.frameId === frame.frameId ? previous.pixel : source.pixel
    marks.set(pane, {
      frameId: frame.frameId, pixel, sky: pixelToSky(grid, pixel), productId: frame.productId, centroidPixel: source.pixel,
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
    highlightedResidual = undefined
    selectedCandidate = undefined
    clearTrack()
    const info = [...distinctWarnings(result.warnings ?? [], warnings)]
    if (!result.candidates.length) candidateList.append(node('p', 'No linked change candidate passed the quality gate.'))
    for (const warning of info) candidateList.append(node('p', warning))
    const groups = result.residualGroups ?? []
    if (groups.length) {
      const details = node('details')
      const list = node('ol')
      details.append(node('summary', `Single-pair residuals · ${groups.length}`),
        node('p', 'Provisional changes from one aligned pair. The signal-to-noise values are approximate.'), list)
      let pressed: HTMLButtonElement | undefined
      for (const group of groups.slice(0, 8)) {
        const item = node('li')
        const highlight = action('Highlight residual')
        highlight.setAttribute('aria-pressed', 'false')
        highlight.disabled = !panes().some(([, frame]) => frame && (frame.frameId === group.frameA || frame.frameId === group.frameB))
        highlight.onclick = () => {
          pressed?.setAttribute('aria-pressed', 'false')
          highlightedResidual = highlightedResidual === group ? undefined : group
          pressed = highlightedResidual ? highlight : undefined
          pressed?.setAttribute('aria-pressed', 'true')
          api.redraw()
        }
        item.append(
          node('p', `${residualSign(group)} · S/N ${format(Math.abs(group.snr))}`),
          node('p', `A ${group.timeA} · B ${group.timeB}`),
          node('p', `ICRS ${group.raDeg.toFixed(6)}°, ${group.decDeg.toFixed(6)}° · Pixel (${format(group.pixel.x, 5)}, ${format(group.pixel.y, 5)})`),
          highlight,
        )
        list.append(item)
      }
      if (groups.length > 8) details.append(node('p', `Showing the strongest 8 of ${groups.length} residuals.`))
      candidateList.append(details)
    }
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
      for (const nearby of candidate.catalogMatches ?? []) {
        const title = catalogLabels[nearby.catalog]
        if (!nearby.matches.length) {
          const coverage = nearby.truncated ? ' in the truncated catalog results' : ''
          item.append(node('p', `${title} · No position within ${format(nearby.radiusArcsec)}″${coverage}.`))
          continue
        }
        const qualifiers = [nearby.ambiguous && 'multiple possible matches', nearby.truncated && 'truncated results'].filter(Boolean)
        item.append(node('p', `${title} proximity only${qualifiers.length ? ` · ${qualifiers.join(' · ')}` : ''}`))
        const list = node('ul')
        for (const match of nearby.matches) {
          const reference = typeof match.referenceEpoch === 'number' ? `J${match.referenceEpoch.toFixed(1)}` : match.referenceEpoch ?? 'epoch unspecified'
          const epoch = nearby.catalog === 'allwise' ? match.comparisonEpoch
            : match.properMotionApplied ? `propagated from ${reference}` : reference
          const visits = match.matchedVisits === 1 ? '1 visit' : `${match.matchedVisits} visits`
          list.append(node('li', `${match.catalogId} · ${format(match.separationArcsec)}″ on ${match.observationUtc.slice(0, 10)} UTC · ${epoch} · ${visits}`))
        }
        item.append(list)
      }
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
      const residualCount = response.data.residualGroups?.length ?? 0
      trackStatus.textContent = `${response.data.candidates.length} linked candidates${residualCount ? ` · ${residualCount} signed residuals` : ''}`
    })
  }

  coadd.onclick = () => {
    const frame = api.shown()
    if (!frame) return
    void run(coaddCaption, 'Preparing wavelength-matched exposures from this visit…', async signal => {
      const merged = await api.prepare(frame, signal, 'coadd')
      if (signal.aborted) return
      await api.showPrepared(merged)
      coaddCaption.textContent = merged.warnings?.join(' ') || 'Within-visit coadd is displayed.'
    }, 'series')
  }

  const spectrumTarget = choose([['center', 'Field center'], ['point', 'Picked sky position'], ['candidate', 'Active detected candidate']])
  const spectrumMode = choose([['quick', 'Quick exposure spectrum'], ['extended', 'Extended exposure spectrum'], ['coadded_cube', 'DR1 coadded cube context']])
  const spectrumModeInfo = node('p')
  spectrumModeInfo.className = 'spectrum-mode-info'
  const spectrumMethod = choose([['aperture', 'Aperture photometry'], ['epsf', 'Effective PSF']])
  const spectrumMethodLabel = label('Photometry method', spectrumMethod)
  const pickSpectrum = action('Pick a sky position')
  const computeSpectrum = action('Extract spectrum')
  const spectrumStatus = statusLine()
  const spectrumOutput = node('div')
  spectrumOutput.className = 'spectrum-output'
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
    spectrumModeInfo, spectrumMethodLabel, range, computeSpectrum, spectrumStatus, spectrumOutput)

  function refreshSpectrumTarget() {
    const isCube = spectrumMode.value === 'coadded_cube'
    spectrumMethodLabel.hidden = dates.hidden = isCube
    spectrumModeInfo.textContent = isCube ? 'Show infrared brightness across 102 wavelength channels combined over multiple observations.' :
      spectrumMode.value === 'extended' ? 'Check more observations and load calibration if needed. This can take longer.' :
      'Check up to eight observations using calibration already available on the server.'
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
    extractSpectrum(body)
  }

  function extractSpectrum(body: Record<string, unknown>) {
    void run(spectrumStatus, 'Measuring infrared brightness…', async signal => {
      const response = await api.data<Spectrum>(path('spectra'), signal, body, false)
      if (signal.aborted) return
      spectrumStatus.textContent = response.status === 'partial' ? 'Extraction finished with gaps.' : 'Extraction complete.'
      displaySpectrum(response.data, response.warnings, body)
    }, 'series')
  }

  function displaySpectrum(spectrum: Spectrum, warnings: string[], body: Record<string, unknown>) {
    spectrumOutput.replaceChildren()
    const samples = spectrum.samples
    const usable = samples.filter(measuredSpectrumSample)
    const calibrationMissing = body.mode === 'quick' && samples.some(sample =>
      !measuredSpectrumSample(sample) && /extended spectrum|calibrat.*not cached/i.test(sample.reason ?? ''))
    if (samples.length) spectrumOutput.append(spectrumCoverage(samples))
    else spectrumOutput.append(node('p', 'No samples were available for this position and range.'))
    if (usable.some(sample => finite(sample.wavelengthUm))) {
      spectrumOutput.append(plotSpectrum(usable, spectrum.units))
    } else if (samples.length) {
      const empty = node('div')
      empty.className = 'spectrum-empty'
      empty.append(node('strong', 'No brightness measurements'), node('p', calibrationMissing ?
        'The quick check could not use the detector calibration for this selection.' :
        'The sample list shows where coverage or data quality prevented a measurement.'))
      if (spectrum.mode !== 'coadded_cube') empty.append(node('p',
        'For a wider range of wavelengths, choose the DR1 coadded cube. It combines multiple observations.'))
      spectrumOutput.append(empty)
    }
    if (calibrationMissing) {
      const retry = action('Retry with extended extraction')
      retry.className = 'spectrum-retry'
      retry.onclick = () => {
        spectrumMode.value = 'extended'
        refreshSpectrumTarget()
        extractSpectrum({...body, mode: 'extended'})
      }
      spectrumOutput.append(retry)
    }
    const lightCurve = matchedLightCurve(usable)
    if (lightCurve.length >= 2) {
      const panel = node('details')
      panel.append(node('summary', 'Matched-wavelength light curve'), node('p',
        `Detector ${lightCurve[0].detector} · one fitted flux per independent visit.`), plotSpectrum(lightCurve, spectrum.units, true))
      spectrumOutput.append(panel)
    }
    const table = node('table')
    table.className = 'sample-table'
    const headers = node('thead'), header = node('tr')
    const headings = ['Wavelength', `Brightness (${spectrum.units})`, 'Observation']
    for (const name of headings) {
      const th = node('th', name)
      th.scope = 'col'
      header.append(th)
    }
    headers.append(header)
    table.append(headers)
    const rows = node('tbody')
    for (const sample of samples) {
      const row = node('tr')
      const wave = node('td', finite(sample.wavelengthUm) ? `${format(sample.wavelengthUm, 4)} µm` : 'Unavailable')
      if (finite(sample.bandwidthUm)) wave.append(node('small', `${format(sample.bandwidthUm)} µm band`))
      const flux = node('td', measuredSpectrumSample(sample) ?
        `${format(sample.flux)}${finite(sample.error) ? ' ± ' + format(sample.error) : ''}` : 'Unavailable')
      const observation = node('td', sample.startUtc ? `${sample.startUtc.slice(0, 10)} UTC` :
        sample.channel != null ? `Channel ${sample.channel}` : '—')
      if (sample.startUtc) observation.append(node('small', sample.startUtc.split('T')[1]?.replace(/Z$/, ' UTC')))
      if (sample.reason) observation.append(node('small', sample.reason))
      if (sample.productId) observation.append(node('small', sample.productId))
      for (const [index, cell] of [wave, flux, observation].entries()) cell.dataset.label = headings[index]
      row.append(wave, flux, observation)
      rows.append(row)
    }
    table.append(rows)
    if (samples.length) {
      const details = node('details')
      details.append(node('summary', `Spectral samples (${samples.length})`), table)
      spectrumOutput.append(details)
    }
    const notes = node('details')
    notes.append(node('summary', 'Method and data notes'), node('p', spectrum.mode === 'coadded_cube' ?
      'The DR1 cube combines exposures, so individual channels have no observation date.' :
      'The measurement date can vary from one wavelength to the next.'))
    for (const warning of distinctWarnings(spectrum.warnings ?? [], warnings)) notes.append(node('p', warning))
    notes.append(link('IRSA spectrum reference ↗', spectrum.referenceUrl))
    spectrumOutput.append(notes)
    if (spectrum.archiveDoi && /^10\.26131\/IRSA\d+$/.test(spectrum.archiveDoi)) {
      spectrumOutput.append(link('Spectral product DOI ↗', `https://doi.org/${spectrum.archiveDoi}`))
    }
  }

  function updateControls() {
    const a = api.shown(), b = api.paired()
    for (const pane of ['track-panel', 'catalog-panel', 'spectrum-panel']) $(pane).hidden = !a
    coaddRegion.hidden = !a
    coadd.disabled = !a || a.representation === 'coadd'
    const showExposure = !api.displayMode || ['single', 'side'].includes(api.displayMode())
    markA.disabled = !a || !showExposure
    markB.disabled = !b || !showExposure || Boolean($('frame-b').hidden)
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
    for (const [pane, preferred] of panes()) {
      const frame = api.displayed ? api.displayed(pane) : preferred
      if (!frame || (pane === 'b' && $('frame-b').hidden)) continue
      for (const catalog of selectedCatalogs) {
        for (const marker of projectedCatalog(catalog, frame)) {
          api.mark(pane, marker.x, marker.y, catalog, `${catalogLabels[catalog]} ${marker.catalogId}`)
        }
      }
      const placed = marks.get(pane)
      if (placed?.frameId === frame.frameId) {
        const {pixel, centroidPixel} = placed
        if (centroidPixel && (centroidPixel.x !== pixel.x || centroidPixel.y !== pixel.y)) {
          api.mark(pane, pixel.x, pixel.y, 'analysis-cursor', `Original mark ${pane.toUpperCase()}`)
        }
        const position = centroidPixel ?? pixel
        const kind = centroidPixel ? 'Snapped centroid' : 'Mark'
        api.mark(pane, position.x, position.y, 'analysis-mark', `${kind} ${pane.toUpperCase()}`)
      }
      for (const source of preview) {
        if (source.frameId === frame.frameId) api.mark(pane, source.pixel.x, source.pixel.y, 'analysis-candidate', selectedCandidate?.label)
      }
      if (highlightedResidual && (frame.frameId === highlightedResidual.frameA || frame.frameId === highlightedResidual.frameB)) {
        const {x, y} = highlightedResidual.pixel
        api.mark(pane, x, y, 'analysis-candidate', `Provisional residual · ${residualSign(highlightedResidual)}`)
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
      const grid = api.manifest()!.grid
      const [[a, b], [c, d]] = grid.cd
      const arcsecPerPixel = Math.sqrt(Math.abs(a * d - b * c)) * 3600
      let previous: HTMLElement | void = undefined
      const samples = tracked.forecast.samples
      const bandSamples = new Set([0, Math.floor(samples.length / 2), samples.length - 1])
      for (const [index, sample] of samples.entries()) {
        const marker = api.mark('a', sample.x, sample.y, 'analysis-forecast', `${sample.timeUtc} · approximate 95% radius ${format(sample.ellipse95Arcsec)}″`)
        joinMarkers(previous, marker, 'analysis-prediction')
        previous = marker
        if (!marker || !bandSamples.has(index)) continue
        const probe = api.mark('a', sample.x + 1, sample.y, 'analysis-uncertainty')
        if (!probe) continue
        const displayPixelsPerPixel = Math.abs(parseFloat(probe.style.left) - parseFloat(marker.style.left))
        probe.remove()
        const band = api.mark('a', sample.x, sample.y, 'analysis-uncertainty')
        if (band) band.style.width = band.style.height = `${2 * sample.ellipse95Arcsec / arcsecPerPixel * displayPixelsPerPixel}px`
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
      highlightedResidual = undefined
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
      if (operationScope === 'pair' && activePair) operation?.abort()
      activePair = pair
      clearTrack()
      candidateList.replaceChildren()
      selectedCandidate = undefined
      preview = []
      highlightedResidual = undefined
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

export function matchedLightCurve(samples: SpectrumSample[]) {
  const valid = samples.filter(sample => sample.sampleStatus === 'measured' && finite(sample.flux)
    && finite(sample.wavelengthUm) && finite(sample.bandwidthUm) && sample.bandwidthUm > 0
    && sample.detector && sample.visitId && sample.startUtc && Number.isFinite(Date.parse(sample.startUtc)))
  let best: SpectrumSample[] = []
  for (const anchor of valid) {
    const visits = new Map<string, SpectrumSample>()
    const nearby = valid.filter(sample => sample.detector === anchor.detector
      && Math.abs(sample.wavelengthUm! - anchor.wavelengthUm!) <= Math.min(sample.bandwidthUm!, anchor.bandwidthUm!) / 2)
    nearby.sort((a, b) => Math.abs(a.wavelengthUm! - anchor.wavelengthUm!) - Math.abs(b.wavelengthUm! - anchor.wavelengthUm!))
    for (const sample of nearby) {
      if (visits.has(sample.visitId!)) continue
      const sharesBand = [...visits.values()].every(previous => Math.abs(sample.wavelengthUm! - previous.wavelengthUm!)
        <= Math.min(sample.bandwidthUm!, previous.bandwidthUm!) / 2)
      if (sharesBand) visits.set(sample.visitId!, sample)
    }
    if (visits.size > best.length) best = [...visits.values()]
  }
  return best.sort((a, b) => Date.parse(a.startUtc!) - Date.parse(b.startUtc!))
}

function spectrumCoverage(samples: SpectrumSample[]) {
  const coverage = node('section')
  coverage.className = 'spectrum-coverage'
  const measured = samples.filter(measuredSpectrumSample).length
  const available = node('div')
  available.className = 'spectrum-coverage-label'
  available.append(node('strong', `${measured} of ${samples.length} samples measured`))
  const strip = node('div')
  strip.className = 'spectrum-coverage-strip'
  strip.setAttribute('aria-hidden', 'true')
  const sorted = [...samples].sort((a, b) => (a.wavelengthUm ?? Infinity) - (b.wavelengthUm ?? Infinity))
  for (const [index, sample] of sorted.entries()) {
    const measured = measuredSpectrumSample(sample)
    const cell = node('span')
    cell.className = measured ? 'spectrum-measured' : 'spectrum-missing'
    const name = finite(sample.wavelengthUm) ? `${format(sample.wavelengthUm, 4)} µm` : `Sample ${index + 1}`
    cell.title = `${name} · ${measured ? 'Measured' : sample.reason || 'Unavailable'}`
    strip.append(cell)
  }
  const legend = node('div')
  legend.className = 'spectrum-legend'
  for (const [className, label] of [['spectrum-measured', 'Measured'], ['spectrum-missing', 'Unavailable']]) {
    const item = node('span', label)
    const swatch = node('i')
    swatch.className = className
    swatch.setAttribute('aria-hidden', 'true')
    item.prepend(swatch)
    legend.append(item)
  }
  coverage.append(available, strip, legend)
  return coverage
}

function plotSpectrum(samples: SpectrumSample[], units: string, byDate = false) {
  const chart = node('figure')
  chart.className = 'spectrum-chart'
  const position = (sample: SpectrumSample) => byDate ? Date.parse(sample.startUtc ?? '') : sample.wavelengthUm
  const data = samples.flatMap(sample => {
    const x = position(sample)
    if (!finite(x) || !finite(sample.flux)) return []
    return [{x, y: sample.flux, error: finite(sample.error) && sample.error >= 0 ? sample.error : 0}]
  })
  const hasErrors = data.some(sample => sample.error > 0)
  const bounds = (values: number[], minSpan: number) => {
    const lo = Math.min(...values), hi = Math.max(...values)
    const padding = Math.max((hi - lo) * .04, (minSpan - (hi - lo)) / 2)
    return [lo - padding, hi + padding]
  }
  const [firstX, lastX] = bounds(data.map(sample => sample.x), byDate ? 86400000 : .02)
  const [firstY, lastY] = bounds(data.flatMap(sample => [sample.y - sample.error, sample.y + sample.error]),
    Math.max(Math.abs(data[0].y) * .08, 1e-7))
  const xPercent = (value: number) => 100 * (value - firstX) / (lastX - firstX)
  const yPercent = (value: number) => 100 * (lastY - value) / (lastY - firstY)
  const showX = (value: number) => byDate ? new Date(value).toISOString().slice(0, 10) : format(value, 4)

  chart.append(node('figcaption', `Brightness (${units})`))
  const graphic = node('div')
  graphic.className = 'spectrum-chart-area'
  graphic.setAttribute('role', 'img')
  const axis = byDate ? 'UTC observation date' : 'Wavelength (µm)'
  graphic.setAttribute('aria-label', `${data.length} brightness measurements by ${axis.toLowerCase()}. See spectral samples for exact values.`)
  const yAxis = node('div')
  yAxis.className = 'spectrum-y-axis'
  for (const value of [lastY, (lastY + firstY) / 2, firstY]) yAxis.append(node('span', format(value, 4)))
  const points = node('div')
  points.className = 'spectrum-points'
  points.setAttribute('aria-hidden', 'true')
  for (const sample of data) {
    if (sample.error > 0) {
      const error = node('span')
      error.className = 'spectrum-error-bar'
      error.style.left = `${xPercent(sample.x)}%`
      error.style.top = `${yPercent(sample.y + sample.error)}%`
      error.style.height = `${yPercent(sample.y - sample.error) - yPercent(sample.y + sample.error)}%`
      points.append(error)
    }
    const point = node('span')
    point.className = 'spectrum-point'
    point.style.left = `${xPercent(sample.x)}%`
    point.style.top = `${yPercent(sample.y)}%`
    const uncertainty = sample.error > 0 ? ` ± ${format(sample.error, 4)}` : ''
    point.title = `${showX(sample.x)}${byDate ? ' UTC' : ' µm'} · ${format(sample.y, 4)}${uncertainty} ${units}`
    points.append(point)
  }
  const xAxis = node('div')
  xAxis.className = 'spectrum-x-axis'
  xAxis.append(node('span', showX(firstX)), node('span', showX(lastX)))
  const xLabel = node('p', axis)
  xLabel.className = 'spectrum-x-label'
  graphic.append(yAxis, points, xAxis, xLabel)
  chart.append(graphic)
  if (hasErrors) chart.append(node('small', 'Vertical bars show measurement uncertainty.'))
  return chart
}
