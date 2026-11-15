import { mkdir, rename } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

const root = process.env.SPHEREX_DEMO_ORIGIN || 'http://127.0.0.1:4173'
const output = resolve(process.argv[2] || 'spherex-demo.webm')
const scratch = resolve(process.env.SPHEREX_DEMO_TEMP || '/tmp/spherex-demo-recording')
await mkdir(scratch, {recursive: true})
const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE})
const size = {width: 1280, height: 720}
const context = await browser.newContext({viewport: size, recordVideo: {dir: scratch, size}, reducedMotion: 'reduce'})
const page = await context.newPage()
page.setDefaultTimeout(6000)
const capture = page.video()

async function caption(copy) {
  await page.evaluate(text => {
    let overlay = document.querySelector('#demo-caption')
    if (!overlay) {
      overlay = document.createElement('div')
      overlay.id = 'demo-caption'
      Object.assign(overlay.style, {
        position: 'fixed', zIndex: '999', left: '26px', right: '26px', bottom: '22px',
        color: '#eef7fa', background: '#121c28', border: '1px solid #79a2af',
        borderRadius: '8px', padding: '13px 18px', boxShadow: '0 6px 24px #071019aa',
        font: '600 21px system-ui', textAlign: 'center', pointerEvents: 'none',
      })
      document.body.append(overlay)
    }
    overlay.textContent = text
  }, copy)
}

try {
  await page.goto(root, {waitUntil: 'domcontentloaded'})
  await caption('Planet X and SPHEREx · Explore real infrared observations of the same sky field')
  await page.waitForTimeout(2450)
  await page.getByRole('link', {name: 'Barnard’s Star'}).click()
  await page.locator('#metadata').getByText(/2025-08-15/).first().waitFor()
  await page.locator('#field-title').evaluate(node => node.scrollIntoView({block: 'start'}))
  await caption('Open Barnard’s Star · The viewer starts at the earliest bundled observation')
  await page.waitForTimeout(3100)
  await page.getByRole('button', {name: 'Play observations'}).click()
  await page.locator('#metadata').getByText(/2026-03-22/).first().waitFor()
  await page.getByRole('button', {name: 'Pause observations'}).click()
  await caption('Play or step between the actual UTC observation dates')
  await page.waitForTimeout(2600)
  await page.getByRole('button', {name: 'Previous observation'}).click()
  await page.locator('#metadata').getByText(/2025-08-15/).first().waitFor()
  await page.getByText('Compare dates', {exact: true}).click()
  await page.getByRole('combobox', {name: 'Second observation date'}).selectOption({index: 1})
  await page.locator('#frame-b').waitFor({state: 'visible'})
  await page.locator('#frame-a').evaluate(node => node.scrollIntoView({block: 'center'}))
  await caption('2025-08-15 and 2026-03-22 UTC · Matched detector 6 exposures near 4.93 μm')
  await page.waitForTimeout(3200)
  await page.getByRole('combobox', {name: 'Comparison view'}).selectOption('difference')
  await page.locator('#heatmap-legend').waitFor({state: 'visible'})
  await page.locator('#frame-a').evaluate(node => node.scrollIntoView({block: 'center'}))
  await caption('Signed difference · Blue is fainter, orange is brighter · Saturation limits the motion measurement')
  await page.waitForTimeout(3900)
  await caption('spherex.144.91.89.214.sslip.io · Real NASA/IPAC IRSA data · Viewer and demo assembled with Codex')
  await page.waitForTimeout(2700)
  await context.close()
  await rename(await capture.path(), output)
  console.log(output)
} finally {
  await browser.close()
}
