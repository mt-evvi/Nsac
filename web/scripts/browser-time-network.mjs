import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { chromium } from 'playwright'

const origin = process.env.SPHEREX_SMOKE_ORIGIN || 'http://127.0.0.1:4173'
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
const page = await browser.newPage()
await page.addInitScript(() => {
  const decode = window.createImageBitmap.bind(window)
  const close = ImageBitmap.prototype.close
  const bitmaps = new Set()
  window.rasterUse = {active: 0, peak: 0, decoded: 0}
  window.createImageBitmap = async (...arguments_) => {
    const image = await decode(...arguments_)
    bitmaps.add(image)
    window.rasterUse.active = bitmaps.size
    window.rasterUse.peak = Math.max(bitmaps.size, window.rasterUse.peak)
    window.rasterUse.decoded++
    return image
  }
  ImageBitmap.prototype.close = function () {
    bitmaps.delete(this)
    window.rasterUse.active = bitmaps.size
    return close.call(this)
  }
})
let olderRequest
const olderReceived = new Promise(resolve => { olderRequest = resolve })
const preparedCalls = []
const inputQueries = []
const scienceCalls = []
const build = (id, day, visit, detector = 6, hour = '12') => ({
  frameId: id, obsId: `fixture-${id}`, productId: `fixture-${id}`, slotKey: day,
  visitId: visit, startUtc: `${day}T${hour}:00:00Z`, endUtc: `${day}T${hour}:01:00Z`,
  release: 'SYNTHETIC TEST METADATA', detector, archiveUrl: 'https://example.invalid/fixture',
})
const frames = [build('A', '2025-01-01', 'first', 6, '23'), build('A2', '2025-01-01', 'first', 3, '23'),
  build('B', '2025-01-02', 'first', 6, '00'), build('C', '2025-01-15', 'second'),
  build('D', '2025-03-12', 'third'), build('E', '2025-03-16', 'fourth')]
const envelope = data => ({ status: 'succeeded', warnings: [], data })

try {
  const bundle = await (await page.request.get(`${origin}/presets/barnard/manifest.json`)).json()
  const imageUrl = bundle.data.frames[0].imageUrl
  const comparisonUrl = '/data/synthetic-comparison.png'
  const comparisonImage = await (await page.request.get(new URL(imageUrl, origin).href)).body()
  const indexedPages = []
  const preparedCoadds = []
  const requestedTracks = []
  const rasterRequests = new Map()
  const budgetFrames = Array.from({length:15}, (_, index) => ({
    ...build(`raster-${index}`, `2025-02-${String(index + 1).padStart(2, '0')}`, `visit-${index}`),
    imageUrl: `/data/raster-budget-${index}.png`,
  }))
  const invalidRaster = Buffer.from(comparisonImage)
  invalidRaster.writeUInt32BE(129, 16)
  const oversizedRaster = Buffer.alloc(256 * 1024 + 1)
  comparisonImage.copy(oversizedRaster)
  let releaseAdjacent, releaseBudget
  const adjacentHold = new Promise(resolve => {releaseAdjacent = resolve})
  const budgetHold = new Promise(resolve => {releaseBudget = resolve})
  await page.route('**/data/raster-budget-*.png', async route => {
    const url = new URL(route.request().url()).pathname
    rasterRequests.set(url, (rasterRequests.get(url) ?? 0) + 1)
    if (url.endsWith('-1.png')) await adjacentHold
    if (url.endsWith('-12.png')) await budgetHold
    const body = url.endsWith('-13.png') ? invalidRaster : url.endsWith('-14.png') ? oversizedRaster : comparisonImage
    await route.fulfill({body, contentType: 'image/png'})
  })
  const centroidPixel = {x: 12.25, y: 15.75}
  const covariance = [[0.11, 0.02], [0.02, 0.14]]
  const manifest = (query, frames, seriesId) => envelope({ seriesId, frames, query: {...query, start:'2025-01-01',end:'2025-03-31'},
    schemaVersion: 1, pipelineVersion: 'synthetic-test', grid: bundle.data.grid, searchStatus: frames.length ? 'OK' : 'NO_COVERAGE',
    counts: { products: frames.length, observationDates: new Set(frames.map(x => x.slotKey)).size, preparedFrames: 0 } })
  await page.route('**/api/v1/series', async route => {
    const query = route.request().postDataJSON()
    inputQueries.push(query)
    if (query.raDeg === 11) {
      olderRequest()
      await new Promise(resolve => setTimeout(resolve, 650))
      await route.fulfill({ json: manifest(query, [build('STALE', '2025-03-31', 'old')], 'stale') }).catch(() => {})
    } else if (query.raDeg === 45) {
      await route.fulfill({status:503,json:{code:'UPSTREAM_UNAVAILABLE',message:'The test archive is temporarily unavailable.'}})
    } else if (query.raDeg === 46) {
      const first = manifest(query, [frames[0], frames[3]], 'paginated')
      await route.fulfill({json: {...first, data: {...first.data, nextCursor: 'page-2'}}})
    } else if (query.raDeg === 47 || query.raDeg === 48) {
      const seriesId = query.raDeg === 47 ? 'pass-label' : 'late-pass'
      const first = manifest(query, [frames[0], frames[2], frames[3]], seriesId)
      await route.fulfill({json: {...first, data: {...first.data, nextCursor: 'pass-page'}}})
    } else if (query.raDeg === 49) {
      const result = manifest(query, budgetFrames, 'raster-budget')
      await route.fulfill({json: {...result, data: {...result.data, nextCursor: 'raster-page'}}})
    } else {
      const selected = query.raDeg === 43 ? [frames[0]] : query.raDeg === 44 ? [] : frames
      await route.fulfill({ json: manifest(query, selected, 'synthetic') })
    }
  })
  await page.route('**/api/v1/series/paginated?cursor=*', async route => {
    const cursor = new URL(route.request().url()).searchParams.get('cursor')
    indexedPages.push(cursor)
    const second = cursor === 'page-2'
    const result = manifest({raDeg: 46, decDeg: 0, fovArcmin: 3}, [second ? frames[4] : frames[5]], 'paginated')
    await route.fulfill({json: {...result, data: {...result.data, nextCursor: second ? 'page-3' : undefined}}})
  })
  await page.route(/\/api\/v1\/series\/raster-budget\?cursor=raster-page$/, async route => {
    await budgetHold
    await route.fulfill({json: manifest({raDeg: 49, decDeg: 0, fovArcmin: 3}, [], 'raster-budget')})
  })
  let budgetSpectrumRequests = 0
  await page.route('**/api/v1/series/raster-budget/spectra', route => {
    budgetSpectrumRequests++
    return route.fulfill({json: envelope({mode: 'quick', units: 'µJy', samples: [], warnings: [],
      referenceUrl: 'https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html'})})
  })
  await page.route(/\/api\/v1\/series\/(pass-label|late-pass)\?cursor=pass-page$/, async route => {
    const seriesId = new URL(route.request().url()).pathname.split('/').at(-1)
    const second = [{...frames[4], surveyPass: seriesId === 'pass-label' ? 'Survey 1' : 2}, frames[5]]
    await route.fulfill({json: manifest({raDeg: 47, decDeg: 0, fovArcmin: 3}, second, seriesId)})
  })
  await page.route(`**${comparisonUrl}`, route => route.fulfill({body: comparisonImage, contentType: 'image/png'}))
  await page.route('**/api/v1/series/paginated/comparisons', route => route.fulfill({json: envelope({
    assetUrl: comparisonUrl, limits: [-1, 1], units: 'MJy/sr', mode: 'difference',
  })}))
  await page.route('**/api/v1/series/paginated/detections', route => route.fulfill({json: envelope({
    candidates: [], sources: [{frameId: 'A', sources: [{frameId: 'A', pixel: centroidPixel, snr: 18}]}], warnings: [],
    residualGroups: [
      {frameA: 'A', frameB: 'D', timeA: frames[0].startUtc, timeB: frames[4].startUtc,
        sign: 'positive', pixel: {x: 8, y: 9}, raDeg: 46, decDeg: 0, snr: 12.5},
      {frameA: 'A', frameB: 'D', timeA: frames[0].startUtc, timeB: frames[4].startUtc,
        sign: 'negative', pixel: {x: 14, y: 11}, raDeg: 46.01, decDeg: 0.02, snr: 7.4},
    ],
  })}))
  await page.route('**/api/v1/series/paginated/spectra', route => route.fulfill({json: envelope({
    mode: 'coadded_cube', units: 'MJy/sr', samples: [], warnings: [], archiveDoi: '10.26131/IRSA679',
    referenceUrl: 'https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html',
  })}))
  await page.route('**/api/v1/series/paginated/tracks', route => {
    const {marks} = route.request().postDataJSON()
    requestedTracks.push(marks)
    const measurements = marks.map(mark => {
      const frame = frames.find(frame => frame.frameId === mark.frameId)
      const snapped = mark.centroidPixel && {originalPixel: mark.pixel, covariancePx2: covariance}
      return {frameId: mark.frameId, productId: frame.productId, timeUtc: frame.startUtc, pixel: mark.centroidPixel ?? mark.pixel,
        raDeg: 46, decDeg: 0, sigmaArcsec: 1.8, method: snapped ? 'snapped native centroid' : 'manual mark', ...snapped}
    })
    return route.fulfill({json: envelope({
      measurements, baselineDays: 70, separationArcsec: 2, uncertaintyArcsec: 1,
      positionAngleDeg: 43, rateArcsecPerDay: 0.04, forecastReason: 'Two measured visits.', forecast: null,
    })})
  })
  await page.route('**/api/v1/series/*/frames/*', async route => {
    const id = route.request().url().split('/').at(-1)
    const frame = frames.find(item => item.frameId === id)
    assert.ok(frame, 'Superseded request must not prepare its indexed frame')
    const coadd = route.request().postDataJSON().representation === 'coadd'
    if (coadd) preparedCoadds.push(id)
    else preparedCalls.push(id)
    const pass = route.request().url().includes('/pass-label/') && ['A', 'D'].includes(id)
      ? {surveyPass: 1} : {}
    const variant = coadd ? {frameId: `${id}-coadd`, representation: 'coadd'} : {}
    await route.fulfill({ json: envelope({...frame,...pass,...variant,imageUrl,coverageFraction:1,validFraction:1}) })
  })
  page.on('request', request => {
    if (/\/(comparisons|detections|tracks|overlays|spectra)$/.test(new URL(request.url()).pathname)) scienceCalls.push(request.url())
  })
  await page.goto(origin)
  const ra = page.locator('#ra'), dec = page.locator('#dec'), search = page.getByRole('button', {name:'Find observations'})
  await ra.fill('11'); await dec.fill('0'); await search.click(); await olderReceived
  await ra.fill('08h55m10.831s'); await dec.fill('−07d14m42.53s'); await search.click()
  await page.locator('#metadata').getByText('fixture-A',{exact:true}).waitFor()
  await page.waitForTimeout(700)
  assert.ok(Math.abs(inputQueries[1].raDeg - 133.79512917) < 1e-6)
  assert.ok(Math.abs(inputQueries[1].decDeg + 7.24514722) < 1e-6)
  assert.deepEqual(preparedCalls, ['A'])
  assert.ok(await page.locator('#pointing-label').isVisible())
  const scrub = page.locator('#scrubber')
  assert.equal(await scrub.getAttribute('max'), '4')
  await page.locator('#interval').selectOption('week')
  assert.equal(await scrub.getAttribute('max'), '2')
  await page.locator('#interval').selectOption('month')
  assert.equal(await scrub.getAttribute('max'), '1')
  await page.locator('#interval').selectOption('dates')
  await scrub.evaluate(node => {
    node.dispatchEvent(new PointerEvent('pointerdown'))
    for (const value of ['1','2','1','2','1','3']) {
      node.value = value
      node.dispatchEvent(new Event('input'))
    }
  })
  await page.waitForTimeout(450)
  assert.deepEqual(preparedCalls, ['A'])
  await scrub.dispatchEvent('change')
  await page.locator('#metadata').getByText('fixture-D',{exact:true}).waitFor()
  assert.deepEqual(preparedCalls, ['A', 'D'])
  assert.equal(scienceCalls.length, 0)
  await ra.fill('43'); await dec.fill('−00d30m'); await search.click()
  await page.getByText('Only one usable date is available', {exact:false}).waitFor()
  assert.equal(inputQueries.at(-1).decDeg, -0.5)
  assert.ok(await page.getByRole('button', {name:'Play observations'}).isDisabled())
  await ra.fill('44'); await search.click()
  await page.getByText('No published observations cover this field', {exact:false}).waitFor()
  await ra.fill('45'); await search.click()
  await page.getByText('The test archive is temporarily unavailable.', {exact:true}).waitFor()
  await page.goto(`${origin}/explore?ra=46&dec=0&fov=3&a=fixture-A&b=fixture-D&mode=side`)
  await page.locator('#caption-b').filter({hasText: '2025-03-12 12:00:00 UTC'}).waitFor()
  assert.deepEqual(indexedPages, ['page-2'])
  const shared = new URL(page.url())
  assert.equal(shared.searchParams.get('a'), 'fixture-A')
  assert.equal(shared.searchParams.get('b'), 'fixture-D')
  await page.locator('#pair-panel > summary').click()
  await page.getByRole('combobox', {name: 'Comparison view'}).selectOption('difference')
  await page.locator('#heatmap-legend').waitFor({state:'visible'})
  const contrast = page.locator('#contrast')
  assert.ok(await contrast.isHidden())
  const pixels = () => page.locator('#canvas-a').evaluate(canvas => canvas.toDataURL())
  const heatmap = await pixels()
  await contrast.evaluate(node => {
    node.value = '2.5'
    node.dispatchEvent(new Event('input'))
  })
  assert.equal(await pixels(), heatmap)
  await page.getByRole('combobox', {name: 'Comparison view'}).selectOption('side')
  await contrast.waitFor({state:'visible'})
  assert.equal(await contrast.inputValue(), '2.5')
  await page.getByText('Sources and motion', {exact:true}).click()
  for (const [pane, move] of [['A', 'ArrowLeft'], ['B', 'ArrowUp']]) {
    await page.getByRole('button', {name:`Place mark ${pane}`}).click()
    await page.keyboard.press(move)
    await page.keyboard.press('Enter')
  }
  await page.getByRole('checkbox', {name:'Include the two marks in the share link'}).check()
  const sharedMarks = () => JSON.parse(new URL(page.url()).searchParams.get('marks'))
  const original = sharedMarks().marks.find(mark => mark.frameId === 'A')
  await page.getByRole('button', {name:'Find sources'}).click()
  const residualTitle = 'Single-pair residuals · 2'
  await page.getByText(residualTitle, {exact:true}).click()
  const residuals = page.locator('#track-controls details', {hasText: residualTitle})
  await residuals.getByText('Brighter in B (+) · S/N 12.5', {exact:true}).waitFor()
  await residuals.getByText('Fainter in B (−) · S/N 7.4', {exact:true}).waitFor()
  assert.equal(await residuals.getByText(`A ${frames[0].startUtc} · B ${frames[4].startUtc}`, {exact:true}).count(), 2)
  await residuals.getByText('ICRS 46.010000°, 0.020000° · Pixel (14, 11)', {exact:true}).waitFor()
  await residuals.getByRole('button', {name:'Highlight residual'}).nth(1).click()
  await page.locator('#layers-a [title="Provisional residual · Fainter in B (−)"]').waitFor({state:'attached'})
  await page.locator('#layers-b [title="Provisional residual · Fainter in B (−)"]').waitFor({state:'attached'})
  assert.equal(await residuals.getByRole('button', {name:/Measure|Forecast/}).count(), 0)
  assert.equal(requestedTracks.length, 0)
  await page.getByText(/^Detected centroids · A /).click()
  await page.getByRole('button', {name:/^Use centroid 1 for A/}).click()
  const snapped = {...original, centroidPixel}
  assert.notDeepEqual(original.pixel, centroidPixel)
  assert.deepEqual(sharedMarks().marks.find(mark => mark.frameId === 'A'), snapped)
  assert.equal(sharedMarks().pipelineVersion, 'synthetic-test')
  await page.goto(page.url())
  await page.locator('#layers-a [title="Original mark A"]').waitFor({state:'attached'})
  await page.locator('#layers-a [title="Snapped centroid A"]').waitFor({state:'attached'})
  await page.getByText('Sources and motion', {exact:true}).click()
  await page.getByRole('button', {name:'Measure marks'}).click()
  await page.getByText('Measurement coordinates & provenance', {exact:true}).click()
  assert.deepEqual(requestedTracks[0].find(mark => mark.frameId === 'A'), {frameId: 'A', pixel: original.pixel, centroidPixel})
  await page.getByText('Centroid covariance [0.11, 0.02] [0.02, 0.14] px²', {exact:true}).waitFor()
  const downloadPending = page.waitForEvent('download')
  await page.getByRole('button', {name:'Download measurements'}).click()
  const download = await downloadPending
  assert.equal(download.suggestedFilename(), 'spherex-measurements.json')
  const exported = JSON.parse(await readFile(await download.path(), 'utf8'))
  assert.equal(exported.pipelineVersion, 'synthetic-test')
  assert.match(exported.dataCredit, /NASA\/IPAC Infrared Science Archive/)
  assert.equal(exported.sourceFrames.find(frame => frame.frameId === 'A').productId, 'fixture-A')
  assert.deepEqual(exported.marks.find(mark => mark.frameId === 'A'), snapped)
  const measurement = exported.measurements.find(mark => mark.frameId === 'A')
  assert.deepEqual(measurement.originalPixel, original.pixel)
  assert.deepEqual(measurement.pixel, centroidPixel)
  assert.deepEqual(measurement.covariancePx2, covariance)
  assert.equal(measurement.method, 'snapped native centroid')
  await page.getByText('Spectrum', {exact:true}).click()
  await page.getByLabel('Spectrum source').selectOption('coadded_cube')
  await page.getByRole('button', {name:'Extract spectrum'}).click()
  const citation = page.getByRole('link', {name:'Spectral product DOI ↗'})
  await citation.waitFor()
  assert.equal(await citation.getAttribute('href'), 'https://doi.org/10.26131/IRSA679')
  const selections = {pipelineVersion: 'synthetic-test', marks: [{
    frameId: 'A-coadd', productId: 'fixture-A', pixel: {x: 3, y: 3},
  }]}
  shared.searchParams.set('aCoadd', 'A-coadd')
  shared.searchParams.set('marks', JSON.stringify(selections))
  await page.goto(shared.href)
  await page.locator('#metadata').getByText('coadd', {exact: true}).waitFor()
  await page.locator('#layers-a .analysis-mark').waitFor({state:'attached'})
  await page.locator('#caption-b').filter({hasText: '2025-03-12 12:00:00 UTC'}).waitFor()
  assert.deepEqual(preparedCoadds, ['A'])
  assert.equal(new URL(page.url()).searchParams.get('aCoadd'), 'A-coadd')
  assert.equal(JSON.parse(new URL(page.url()).searchParams.get('marks')).marks[0].frameId, 'A-coadd')
  shared.searchParams.set('aCoadd', 'old-coadd-version')
  await page.goto(shared.href)
  await page.getByText('The pinned coadd is unavailable. Showing its original exposure.', {exact: true}).waitFor()
  assert.equal(await page.locator('#layers-a .analysis-mark').count(), 0)
  const beforePasses = preparedCalls.length
  await page.goto(`${origin}/explore?ra=47&dec=0&fov=3&interval=passes`)
  const dateLabel = page.locator('#date-label')
  await dateLabel.filter({hasText:'2025-01-01 23:00:00 UTC · Survey 1'}).waitFor()
  assert.equal(await page.locator('#interval').inputValue(), 'passes')
  assert.equal(new URL(page.url()).searchParams.get('interval'), 'passes')
  assert.equal(await scrub.getAttribute('max'), '2')
  await page.getByText(/Observations without a verified pass label are grouped by actual UTC date/).waitFor()
  await page.getByRole('button', {name:'More indexed exposures'}).click()
  const exposure = page.locator('#pointing')
  await exposure.locator('option[value="D"]').waitFor({state:'attached'})
  assert.equal(await scrub.getAttribute('max'), '3')
  assert.deepEqual(preparedCalls.slice(beforePasses), ['A'])
  await exposure.selectOption('D')
  await dateLabel.filter({hasText:'2025-03-12 12:00:00 UTC · Survey 1'}).waitFor()
  await page.locator('#metadata').getByText('fixture-D',{exact:true}).waitFor()
  assert.equal(await scrub.inputValue(), '0')
  await page.getByRole('button', {name:'Next observation'}).click()
  await page.locator('#metadata').getByText('fixture-B',{exact:true}).waitFor()
  assert.equal(await dateLabel.innerText(), '2025-01-02 00:00:00 UTC · Unverified survey pass')

  await page.goto(`${origin}/explore?ra=48&dec=0&fov=3`)
  await page.locator('#metadata').getByText('fixture-A',{exact:true}).waitFor()
  const passOption = page.locator('#interval option[value="passes"]')
  assert.ok(await passOption.isDisabled())
  const beforePage = preparedCalls.length
  await page.getByRole('button', {name:'More indexed exposures'}).click()
  await page.waitForFunction(() => !document.querySelector('#interval option[value="passes"]').disabled)
  await page.locator('#interval').selectOption('passes')
  assert.equal(await scrub.getAttribute('max'), '4')
  assert.deepEqual(preparedCalls.slice(beforePage), [])
  const real = await browser.newPage()
  await real.goto(`${origin}/explore?preset=barnard&interval=passes`)
  const barnardFrames = [...bundle.data.frames].sort((a, b) => a.startUtc.localeCompare(b.startUtc))
  const representatives = barnardFrames.filter((frame, index) => barnardFrames.findIndex(item => item.surveyPass === frame.surveyPass) === index)
  assert.deepEqual(representatives.map(frame => frame.surveyPass), ['Survey 2', 'Survey 1', 'Survey 4'])
  await real.locator('#metadata').getByText(representatives[0].productId, {exact:true}).waitFor()
  assert.equal(await real.locator('#interval').inputValue(), 'passes')
  assert.equal(await real.locator('#scrubber').getAttribute('max'), String(representatives.length - 1))
  for (const [index, frame] of representatives.entries()) {
    if (index > 0) await real.getByRole('button', {name:'Next observation'}).click()
    await real.locator('#metadata').getByText(frame.productId, {exact:true}).waitFor()
    assert.ok((await real.locator('#date-label').innerText()).endsWith(frame.surveyPass))
  }
  await real.close()
  const adjacentStarted = page.waitForRequest('**/data/raster-budget-1.png')
  await page.goto(`${origin}/explore?ra=49&dec=0&fov=3`)
  await page.locator('#metadata').getByText('fixture-raster-0', {exact:true}).waitFor()
  await adjacentStarted
  await page.locator('#pair-panel > summary').click()
  const secondImage = page.getByRole('combobox', {name: 'Second observation date'})
  await secondImage.selectOption('raster-1')
  await page.waitForTimeout(150)
  assert.equal(rasterRequests.get('/data/raster-budget-1.png'), 1)
  const metadataStarted = page.waitForRequest(request => request.url().includes('raster-budget?cursor=raster-page'))
  await page.getByRole('button', {name:'More indexed exposures'}).click()
  await metadataStarted
  const farStarted = page.waitForRequest('**/data/raster-budget-12.png')
  await secondImage.selectOption('raster-12')
  await farStarted
  await page.getByText('Spectrum', {exact:true}).click()
  await page.getByRole('button', {name:'Extract spectrum'}).click()
  await page.waitForTimeout(150)
  assert.equal(budgetSpectrumRequests, 0, 'A fourth concurrent transfer waits for capacity')
  releaseAdjacent()
  await page.getByText('Spectrum ready.', {exact:true}).waitFor()
  assert.equal(budgetSpectrumRequests, 1)
  releaseBudget()
  await page.locator('#caption-b').filter({hasText: '2025-02-13 12:00:00 UTC'}).waitFor()
  const pairCanvas = page.locator('#canvas-b')
  const pinnedPixels = await pairCanvas.evaluate(canvas => canvas.toDataURL())
  for (let index = 1; index <= 11; index++) {
    await page.getByRole('button', {name:'Next observation'}).click()
    await page.locator('#metadata').getByText(`fixture-raster-${index}`, {exact:true}).waitFor()
  }
  const rasters = await page.evaluate(() => window.rasterUse)
  assert.ok(rasters.decoded >= 13, 'Exercise eviction with more than eight decoded variants')
  assert.ok(rasters.peak <= 8, 'No more than eight decoded variants including the pinned comparison')
  assert.equal(await pairCanvas.evaluate(canvas => canvas.toDataURL()), pinnedPixels)
  for (const [index, error] of [
    ['13', 'The prepared image exceeds the science grid dimensions.'],
    ['14', 'The prepared image exceeds the transfer limit.'],
  ]) {
    await scrub.evaluate((node, index) => {
      node.dispatchEvent(new PointerEvent('pointerdown'))
      node.value = index
      node.dispatchEvent(new Event('change'))
    }, index)
    await page.getByText(error, {exact:true}).waitFor()
    assert.equal((await page.evaluate(() => window.rasterUse)).decoded, rasters.decoded)
  }
  await page.locator('#metadata').getByText('fixture-raster-11', {exact:true}).waitFor()
  console.log('Timeline, comparisons, survey passes, analysis provenance, bounded raster cache, transfer deduplication, and PNG limits passed.')
} finally {
  await browser.close()
}
