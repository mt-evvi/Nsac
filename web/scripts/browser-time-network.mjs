import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const origin = process.env.SPHEREX_SMOKE_ORIGIN || 'http://127.0.0.1:4173'
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
const page = await browser.newPage()
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
    } else {
      const selected = query.raDeg === 43 ? [frames[0]] : query.raDeg === 44 ? [] : frames
      await route.fulfill({ json: manifest(query, selected, 'synthetic') })
    }
  })
  await page.route('**/api/v1/series/*/frames/*', async route => {
    const id = route.request().url().split('/').at(-1)
    preparedCalls.push(id)
    const frame = frames.find(item => item.frameId === id)
    assert.ok(frame, 'Superseded request must not prepare its indexed frame')
    await route.fulfill({ json: envelope({...frame,imageUrl,coverageFraction:1,validFraction:1}) })
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
  console.log('Synthetic timeline, width-independent bins, same-day exposures, superseded responses, lazy scrubbing, and empty/error states passed.')
} finally {
  await browser.close()
}
