import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const origin = process.env.SPHEREX_SMOKE_ORIGIN || 'http://127.0.0.1:4173'
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
const envelope = data => ({status: 'succeeded', warnings: [], data})
const radians = Math.PI / 180
const side = 29
const pixelDegrees = 6.15 / 3600

// Independent inverse gnomonic calculation for the native north-up fixture grid.
function projectedCenter(ra, dec, dragX, dragY, pixels) {
  const east = dragX / pixels * side * pixelDegrees * radians
  const north = dragY / pixels * side * pixelDegrees * radians
  const distance = Math.hypot(east, north)
  const angle = Math.atan(distance)
  const latitude = dec * radians
  if (!distance) return {raDeg: ra, decDeg: dec}
  const declination = Math.asin(Math.cos(angle) * Math.sin(latitude) + north * Math.sin(angle) * Math.cos(latitude) / distance)
  const longitude = ra * radians + Math.atan2(east * Math.sin(angle), distance * Math.cos(latitude) * Math.cos(angle) - north * Math.sin(latitude) * Math.sin(angle))
  return {raDeg: (longitude / radians + 360) % 360, decDeg: declination / radians}
}

function separationArcsec(a, b) {
  const ra = (a.raDeg - b.raDeg) * radians
  const first = a.decDeg * radians, last = b.decDeg * radians
  const square = Math.sin((first - last) / 2) ** 2 + Math.cos(first) * Math.cos(last) * Math.sin(ra / 2) ** 2
  return 2 * Math.asin(Math.sqrt(Math.min(1, square))) / radians * 3600
}

try {
  const sample = await browser.newPage()
  const preset = await (await sample.request.get(`${origin}/presets/barnard/manifest.json`)).json()
  const png = await (await sample.request.get(new URL(preset.data.frames[0].imageUrl, origin).href)).body()
  await sample.close()

  async function field(raDeg, decDeg) {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}})
    page.setDefaultTimeout(15000)
    const queries = [], discoveries = [], recenters = [], preparations = [], assets = []
    const indexed = new Map()
    const unusable = new Set()
    let originalQuery
    let next = 'succeed'
    let pending
    let pendingQuery
    let announceHeld
    const held = new Promise(resolve => {announceHeld = resolve})
    await page.addInitScript(() => {
      const decode = window.createImageBitmap.bind(window)
      const close = ImageBitmap.prototype.close
      window.navigationRasters = {decoded: 0, closed: 0}
      window.createImageBitmap = async (...args) => {
        const image = await decode(...args)
        window.navigationRasters.decoded++
        return image
      }
      ImageBitmap.prototype.close = function () {
        window.navigationRasters.closed++
        return close.call(this)
      }
    })
    const manifest = (query, differentDates = false) => {
      const seriesId = `navigation-${queries.length}`
      const dates = differentDates ? ['2025-02-12', '2025-02-22'] : ['2025-01-01', '2025-02-01']
      const frames = dates.map((date, i) => ({
        frameId: `${seriesId}-${i}`, productId: differentDates ? `new-window-product-${i}` : `navigation-product-${i}`,
        obsId: `pointing-${date}`, slotKey: date, visitId: `visit-${date}`,
        startUtc: `${date}T00:00:00Z`, endUtc: `${date}T00:02:00Z`,
        release: 'SYNTHETIC NAVIGATION FIXTURE', detector: 6, archiveUrl: 'https://example.invalid/fixture',
      }))
      const result = {schemaVersion: 1, pipelineVersion: 'navigation-test', seriesId, frames,
        query: {...query, start: '2025-01-01', end: '2025-03-01'},
        grid: {width: side, height: side, crpix: [15, 15], crval: [query.raDeg, query.decDeg],
          cd: [[-pixelDegrees, 0], [0, pixelDegrees]]}, searchStatus: 'OK',
        counts: {products: 2, observationDates: 2, independentEpochs: 2, preparedFrames: 0}}
      indexed.set(seriesId, result)
      return envelope(result)
    }
    const respondToField = async route => {
      const coordinates = route.request().postDataJSON()
      const recenter = route.request().url().endsWith('/recenter')
      if (recenter) recenters.push(coordinates)
      else { discoveries.push(coordinates); originalQuery = coordinates }
      const query = {...originalQuery, ...coordinates}
      queries.push(query)
      const behavior = next
      next = 'succeed'
      const reply = manifest(query, behavior === 'different-dates')
      if (behavior === 'unpreparable') unusable.add(reply.data.seriesId)
      if (behavior === 'reject') {
        await route.fulfill({status: 503, json: {code: 'UPSTREAM_UNAVAILABLE', message: 'Navigation fixture archive unavailable.', retryable: true}})
      } else if (behavior === 'hold') {
        pendingQuery = reply.data.seriesId
        announceHeld()
        await new Promise(resolve => {pending = resolve})
        await route.fulfill({json: reply}).catch(() => {})
      } else await route.fulfill({json: reply})
    }
    await page.route('**/api/v1/series', respondToField)
    await page.route('**/api/v1/series/*/recenter', respondToField)
    await page.route(/\/api\/v1\/series\/navigation-\d+$/, route => {
      assert.equal(route.request().method(), 'GET')
      const cached = indexed.get(new URL(route.request().url()).pathname.split('/').at(-1))
      assert.ok(cached, 'A nearby share link restores only its previously indexed field')
      return route.fulfill({json: envelope(cached)})
    })
    await page.route('**/api/v1/series/*/frames/*', async route => {
      const components = new URL(route.request().url()).pathname.split('/')
      const seriesId = components[4], frameId = components[6]
      preparations.push({seriesId, frameId})
      const frame = indexed.get(seriesId)?.frames.find(frame => frame.frameId === frameId)
      assert.ok(frame, 'Only an indexed frame may be prepared')
      if (unusable.has(seriesId)) return route.fulfill({status: 422,
        json: {code: 'LOW_OVERLAP', message: 'Navigation fixture has masked exposures.'}})
      await route.fulfill({json: envelope({...frame, state: 'prepared', coverageFraction: 1, validFraction: 1,
        wavelengthUm: 4.5, bandwidthUm: .04, imageUrl: `/data/navigation-${seriesId}-${frameId}.png`})})
    })
    await page.route('**/data/navigation-*.png', async route => {
      assets.push(route.request().url())
      await route.fulfill({body: png, contentType: 'image/png'})
    })
    await page.goto(`${origin}/explore?ra=${raDeg}&dec=${decDeg}&fov=3&start=2025-01-01&end=2025-03-01&detector=6`)
    await page.locator('#metadata').getByText('navigation-product-0', {exact: true}).waitFor()
    const frame = page.locator('#frame-a')
    await frame.scrollIntoViewIfNeeded()
    const drag = async (dx, dy, beforeRelease) => {
      await frame.scrollIntoViewIfNeeded()
      const box = await frame.boundingBox()
      const center = {x: box.x + box.width / 2, y: box.y + box.height / 2}
      await page.mouse.move(center.x, center.y)
      await page.mouse.down()
      await page.mouse.move(center.x + dx, center.y + dy, {steps: 9})
      await beforeRelease?.()
      await page.mouse.up()
      return Math.min(box.width, box.height)
    }
    return {page, queries, discoveries, recenters, preparations, assets, frame, drag, held,
      setNext: value => {next = value}, releaseHeld: () => pending?.(), heldId: () => pendingQuery}
  }

  const regular = await field(42, 2)
  const {page, queries, discoveries, recenters, preparations, assets, drag} = regular
  const firstInput = {ra: await page.locator('#ra').inputValue(), dec: await page.locator('#dec').inputValue()}
  const initialBounds = await regular.frame.boundingBox()
  const width = Math.min(initialBounds.width, initialBounds.height)
  const shift = width * .32
  await drag(width * .08, 0)
  await page.waitForTimeout(850)
  assert.equal(queries.length, 1, 'Small adjustments do not repeatedly recenter the field')
  await page.locator('#reset-view').click()
  await drag(shift, 0, async () => {
    await page.waitForTimeout(800)
    assert.equal(queries.length, 1, 'Dragging causes no metadata lookup per pointer move')
    assert.equal(preparations.length, 1)
  })
  await page.waitForFunction(() => new URL(location.href).searchParams.has('viewRa'))
  await page.waitForFunction(() => document.querySelector('#view-center').textContent.length > 0)
  await page.waitForTimeout(850)
  assert.equal(queries.length, 2, 'One completed drag issues one new field query')
  assert.equal(discoveries.length, 1, 'Browsing never repeats archive discovery')
  assert.equal(recenters.length, 1, 'Browsing reuses one cached-metadata recenter request')
  assert.equal(preparations.length, 2, 'Only the selected frame is prepared in the new field')
  assert.equal(assets.length, 2, 'Browsing does not fetch offscreen tiles')
  const expected = projectedCenter(42, 2, shift, 0, width)
  assert.ok(separationArcsec(queries[1], expected) < .1, 'The requested center follows the TAN sky geometry')
  assert.equal(await page.locator('#ra').inputValue(), firstInput.ra)
  assert.equal(await page.locator('#dec').inputValue(), firstInput.dec)
  assert.equal(new URL(page.url()).searchParams.get('ra'), '42')
  assert.equal(new URL(page.url()).searchParams.get('dec'), '2')
  assert.ok(await page.locator('#return-target').isVisible())
  const bitmapUse = await page.evaluate(() => window.navigationRasters)
  assert.ok(bitmapUse.closed >= 1, 'A successful field replacement unloads the old decoded image')

  const savedView = new URL(page.url())
  assert.ok(savedView.searchParams.get('viewSeries'), 'The share URL identifies its cached nearby field')
  await page.reload()
  await page.locator('#metadata').getByText('navigation-product-0', {exact: true}).waitFor()
  assert.equal(discoveries.length, 1, 'A valid nearby share link needs no archive rediscovery')
  assert.equal(recenters.length, 1, 'A valid nearby share link restores the cached field directly')
  assert.equal(new URL(page.url()).searchParams.get('viewRa'), savedView.searchParams.get('viewRa'))
  assert.equal(await page.locator('#ra').inputValue(), firstInput.ra)
  assert.equal(await page.locator('#dec').inputValue(), firstInput.dec)

  const manualSeries = `navigation-${queries.length + 1}`
  await page.locator('#search-view').click()
  await page.waitForFunction(series => new URL(location.href).searchParams.get('viewSeries') === series, manualSeries)
  assert.equal(discoveries.length, 2, 'An explicit archive-search click issues exactly one new discovery')
  assert.equal(recenters.length, 1, 'Manual archive search does not also recenter cached metadata')
  assert.ok(separationArcsec(discoveries[1], expected) < .1, 'Manual archive search uses the visible sky center')
  assert.deepEqual(
    [discoveries[1].fovArcmin, discoveries[1].start, discoveries[1].end, discoveries[1].detector],
    [discoveries[0].fovArcmin, discoveries[0].start, discoveries[0].end, discoveries[0].detector],
    'Manual archive search preserves the active field, date and detector filters',
  )
  assert.equal(await page.locator('#ra').inputValue(), firstInput.ra)
  assert.equal(await page.locator('#dec').inputValue(), firstInput.dec)

  const beforeManualError = preparations.length
  const manualUrl = page.url()
  regular.setNext('reject')
  const manualFailure = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/series' && response.request().method() === 'POST')
  await page.locator('#search-view').click()
  assert.equal((await manualFailure).status(), 503)
  await page.getByText('Navigation fixture archive unavailable.', {exact: false}).waitFor()
  await page.waitForFunction(() => !document.querySelector('#search-view').disabled)
  assert.equal(discoveries.length, 3, 'A failed manual search is not automatically repeated')
  assert.equal(preparations.length, beforeManualError, 'Failed manual discovery cannot replace the loaded frame')
  assert.ok(await page.locator('#image-empty').isHidden(), 'Failed manual discovery retains the previous image')
  assert.equal(page.url(), manualUrl, 'Failed manual discovery preserves the loaded field share URL')
  assert.equal(await page.locator('#ra').inputValue(), firstInput.ra)
  assert.equal(await page.locator('#dec').inputValue(), firstInput.dec)

  const previousUrl = page.url()
  const beforeError = preparations.length
  regular.setNext('reject')
  await drag(shift, 0)
  await page.getByText('Navigation fixture archive unavailable.', {exact: false}).waitFor()
  assert.equal(preparations.length, beforeError)
  await page.locator('#metadata').getByText('navigation-product-0', {exact: true}).waitFor()
  assert.ok(await page.locator('#image-empty').isHidden(), 'Archive errors retain the previous field')
  assert.equal(new URL(page.url()).searchParams.get('viewRa'), new URL(previousUrl).searchParams.get('viewRa'))

  await page.locator('#reset-view').click()
  regular.setNext('hold')
  await drag(-shift, 0)
  await Promise.race([regular.held, page.waitForTimeout(12000).then(() => {throw new Error('The fixture recenter request did not arrive')})])
  const newestSeries = `navigation-${queries.length + 1}`
  const latestFrame = page.waitForResponse(response => response.url().includes(`/api/v1/series/${newestSeries}/frames/`))
  await drag(shift, width * .18)
  await latestFrame
  await page.waitForFunction(() => Number(new URL(location.href).searchParams.get('viewDec')) > 2.001)
  regular.releaseHeld()
  await page.waitForTimeout(850)
  assert.equal(preparations.filter(frame => frame.seriesId === regular.heldId()).length, 0,
    'A superseded field result must not prepare or display a frame')

  await page.getByText('Compare dates', {exact: true}).click()
  await page.getByRole('combobox', {name: 'Second observation date'}).selectOption({index: 1})
  await page.locator('#frame-b').waitFor({state: 'visible'})
  const beforeNewDates = {discoveries: discoveries.length, recenters: recenters.length, preparations: preparations.length}
  regular.setNext('different-dates')
  await page.locator('#search-view').click()
  await page.locator('#metadata').getByText('new-window-product-0', {exact: true}).waitFor()
  assert.ok(await page.locator('#frame-b').isHidden(), 'Explicit search clears a comparison whose dates are absent')
  assert.match(await page.locator('#date-label').innerText(), /2025-02-12/)
  assert.equal(discoveries.length, beforeNewDates.discoveries + 1)
  assert.equal(recenters.length, beforeNewDates.recenters, 'Explicit search does not run an additional recenter')
  assert.equal(preparations.length, beforeNewDates.preparations + 1, 'Explicit search loads only the first suitable observation')
  assert.equal(await page.locator('#ra').inputValue(), firstInput.ra)
  assert.equal(await page.locator('#dec').inputValue(), firstInput.dec)

  await page.getByRole('button', {name: /Return to/}).click()
  await page.waitForFunction(() => !new URL(location.href).searchParams.has('viewRa'))
  await page.locator('#metadata').getByText('navigation-product-0', {exact: true}).waitFor()
  assert.match(await page.locator('#date-label').innerText(), /2025-01-01/, 'Returning can use an original observation when the explored date differs')
  assert.equal(discoveries.length, beforeNewDates.discoveries + 1, 'Returning uses the known target index')
  assert.equal(await page.locator('#ra').inputValue(), firstInput.ra)
  assert.equal(await page.locator('#dec').inputValue(), firstInput.dec)

  const comparison = page.getByRole('combobox', {name: 'Second observation date'})
  if (!await comparison.isVisible()) await page.getByText('Compare dates', {exact: true}).click()
  await comparison.selectOption({index: 1})
  await page.locator('#frame-b').waitFor({state: 'visible'})
  const workingUrl = page.url()
  const workingDate = await page.locator('#date-label').innerText()
  for (const [behavior, newRa, reason] of [
    ['reject', '43.5', 'Navigation fixture archive unavailable.'],
    ['unpreparable', '44.5', 'Navigation fixture has masked exposures.'],
  ]) {
    regular.setNext(behavior)
    await page.locator('#ra').fill(newRa)
    await page.getByRole('button', {name: 'Find observations'}).click()
    await page.waitForFunction(message => document.querySelector('#status').textContent.includes(message), reason)
    assert.equal(await page.locator('#ra').inputValue(), newRa, 'Failed search keeps the typed coordinates available for retry')
    assert.equal(page.url(), workingUrl, 'Failed search keeps the share state for the visible comparison')
    assert.equal(await page.locator('#date-label').innerText(), workingDate)
    assert.ok(await page.locator('#image-empty').isHidden())
    assert.ok(await page.locator('#frame-b').isVisible(), 'Failed search keeps the last good comparison')
    await page.locator('#metadata').getByText('navigation-product-0', {exact: true}).waitFor()
  }
  await page.locator('#ra').fill('45.5')
  await page.getByRole('button', {name: 'Find observations'}).click()
  await page.waitForFunction(() => new URL(location.href).searchParams.get('ra') === '45.5')
  assert.ok(await page.locator('#frame-b').isHidden(), 'A successful replacement starts a new comparison selection')
  assert.match(await page.locator('#field-position').innerText(), /45\.50000°/)
  await page.close()

  const polar = await field(359.999, 89.92)
  const polarBox = await polar.frame.boundingBox()
  const polarWidth = Math.min(polarBox.width, polarBox.height)
  await polar.drag(polarWidth * .35, polarWidth * .2)
  await polar.page.waitForFunction(() => new URL(location.href).searchParams.has('viewRa'))
  const target = projectedCenter(359.999, 89.92, polarWidth * .35, polarWidth * .2, polarWidth)
  assert.ok(polar.queries[1].raDeg < 30 && polar.queries[1].raDeg >= 0, 'RA wraps through zero near the pole')
  assert.ok(separationArcsec(polar.queries[1], target) < .1, 'Polar navigation uses spherical coordinates')
  assert.equal(await polar.page.locator('#ra').inputValue(), '359.999')
  assert.equal(await polar.page.locator('#dec').inputValue(), '89.92')
  await polar.page.close()
  console.log('Demand sky browsing, preserved search coordinates, spherical centers, old-field eviction and retryable error retention passed.')
} finally {
  await browser.close()
}
