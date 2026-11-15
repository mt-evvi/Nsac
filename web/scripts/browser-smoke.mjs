import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const origin = process.env.SPHEREX_SMOKE_ORIGIN || 'http://127.0.0.1:4173'
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
const errors = []
const allowed = ['barnard', 'epsilon-indi-b', 'wise-0855', 'wise-0855-nasa', 'rw-aurigae', 'r-draconis']
try {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(origin)
  assert.equal(await page.title(), 'SPHEREx Sky Viewer')
  const presetLinks = page.locator('#presets a')
  assert.equal(await presetLinks.count(), allowed.length)

  // Playback uses bundled images even when live discovery fails.
  await page.route('**/api/v1/series', route => route.fulfill({
    status: 503, json: {code: 'UPSTREAM_UNAVAILABLE', message: 'Simulated archive outage.'},
  }))
  for (const slug of allowed) {
    await page.locator(`#presets a[data-slug="${slug}"]`).click()
    await page.getByText('Original IRSA product', {exact: false}).waitFor()
    const firstDate = await page.locator('#date-label').innerText()
    await page.getByRole('button', { name: 'Next observation' }).click()
    await page.waitForFunction(first => document.querySelector('#date-label').textContent !== first, firstDate)
    await page.waitForFunction(first => !document.querySelector('#frame-a').getAttribute('aria-label').includes(first), firstDate)
    assert.ok(await page.locator('#image-empty').isHidden(), `${slug} did not retain a playable image`)
  }
  await page.unroute('**/api/v1/series')

  await page.getByRole('link', { name: 'Barnard’s Star' }).click()
  await page.locator('#metadata').getByText(/2025-08-15/).first().waitFor()
  await page.getByText('Masked or missing pixels', {exact: true}).click()
  await page.getByText(/Dark solid pixels show measured low brightness/).waitFor({state: 'visible'})
  await page.getByText('Catalog overlays', {exact: true}).click()
  const gaiaHelp = page.getByRole('button', {name: 'About Gaia DR3'})
  const gaiaTooltip = page.locator('#catalog-help-gaia_dr3')
  await gaiaHelp.hover()
  await gaiaTooltip.waitFor({state: 'visible'})
  assert.match(await gaiaTooltip.innerText(), /adjusted to the image date/)
  await gaiaHelp.focus()
  await gaiaHelp.press('Escape')
  await gaiaTooltip.waitFor({state: 'hidden'})
  await page.getByRole('button', { name: 'Next observation' }).click()
  await page.locator('#metadata').getByText(/2026-03-22/).first().waitFor()
  const fresh = await browser.newContext()
  const shared = await fresh.newPage()
  await shared.goto(page.url())
  await shared.locator('#metadata').getByText(/2026-03-22/).first().waitFor()
  await fresh.close()
  await page.locator('#scrubber').focus()
  await page.keyboard.press('ArrowLeft')
  await page.locator('#metadata').getByText(/2025-08-15/).first().waitFor()
  await page.getByText('Compare dates', {exact: true}).click()
  await page.getByRole('combobox', {name: 'Second observation date'}).selectOption({index: 1})
  await page.locator('#frame-b').waitFor({state: 'visible'})
  await page.getByRole('combobox', {name: 'Comparison view'}).selectOption('difference')
  await page.locator('#heatmap-legend').waitFor({state: 'visible'}).catch(async error => {
    const label = await page.locator('#status').innerText()
    throw new Error(`Comparison never rendered. Viewer status: ${label}`, {cause: error})
  })
  const legend = await page.locator('#heatmap-legend').innerText()
  assert.match(legend, /lower in B/)
  assert.match(legend, /higher in B/)
  await page.setViewportSize({width: 390, height: 844})
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  const wiseHelp = page.getByRole('button', {name: 'About AllWISE'})
  await wiseHelp.click()
  await page.locator('#catalog-help-allwise').waitFor({state: 'visible'})
  assert.equal(await wiseHelp.getAttribute('aria-expanded'), 'true')
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  assert.deepEqual(errors, [])
  console.log('Six cached examples, outage playback, keyboard, shared links, signed comparison, pixel legend, catalog help and mobile layout passed.')
} finally {
  await browser.close()
}
