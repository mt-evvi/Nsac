import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

const origin = process.env.SPHEREX_DEMO_ORIGIN || 'http://127.0.0.1:4173'
const viewerAddress = process.env.SPHEREX_DEMO_PUBLIC_HOST || 'spherex.144.91.89.214.sslip.io'
const output = resolve(process.argv[2] || 'spherex-pitch.webm')
const ffmpeg = process.env.SPHEREX_DEMO_FFMPEG || 'ffmpeg'
const fps = 25
const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE})
const asImage = bytes => `data:image/jpeg;base64,${bytes.toString('base64')}`

async function captureViewer() {
  const page = await browser.newPage({viewport:{width:1280,height:1000}, reducedMotion:'reduce'})
  page.setDefaultTimeout(10000)
  // The pitch uses the packaged observations and a single comparison of their local arrays.
  await page.route('**/api/v1/series**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/series/preset-barnard/comparisons') return route.continue()
    return route.abort()
  })
  await page.goto(origin, {waitUntil:'domcontentloaded'})
  await page.addStyleTag({content:`
    .images {height: 370px; min-height: 370px}
    .browse-note {display: none}
    .viewer-guide {padding-block: 6px}
    .timeline {padding: 8px 10px}
    .playback {margin-top: 6px}
    #catalog-panel[open] .detail-body {padding-bottom: 82px}
  `})
  const record = locator => locator.screenshot({type:'jpeg',quality:95,animations:'disabled'})
  await page.getByRole('link',{name:'Barnard’s Star'}).click()
  await page.locator('#metadata').getByText(/2025-08-15/).first().waitFor()
  const picks = await record(page.locator('.query'))
  const first = await record(page.locator('.viewer'))
  const sky = await record(page.locator('#canvas-a'))

  await page.getByRole('button',{name:'Play observations'}).click()
  await page.locator('#metadata').getByText(/2026-03-22/).first().waitFor()
  await page.getByRole('button',{name:'Pause observations'}).click()
  const second = await record(page.locator('.viewer'))

  await page.getByRole('button',{name:'Previous observation'}).click()
  await page.locator('#metadata').getByText(/2025-08-15/).first().waitFor()
  await page.getByText('Compare dates',{exact:true}).click()
  await page.getByRole('combobox',{name:'Second observation date'}).selectOption({index:1})
  await page.locator('#frame-b').waitFor({state:'visible'})
  await page.locator('#caption-b').getByText(/2026-03-22/).waitFor()
  const pair = await record(page.locator('#images'))

  await page.getByRole('combobox',{name:'Comparison view'}).selectOption('difference')
  const legend = page.locator('#heatmap-legend')
  await legend.waitFor({state:'visible'})
  assert.match(await legend.innerText(), /lower in B/)
  assert.match(await legend.innerText(), /higher in B/)
  const difference = await record(page.locator('.viewer'))
  await page.getByText('Catalog overlays',{exact:true}).click()
  await page.getByRole('button',{name:'About Gaia DR3'}).hover()
  await page.locator('#catalog-help-gaia_dr3').waitFor({state:'visible'})
  const catalog = await record(page.locator('#catalog-panel'))
  await page.close()
  return {picks,first,second,sky,pair,difference,catalog}
}

const style = `
  * {box-sizing:border-box} html,body {margin:0;width:1280px;height:720px;overflow:hidden}
  body {color:#edf5fc;background:radial-gradient(ellipse at 75% 35%,#173548,#0a121e 64%);font-family:system-ui,sans-serif}
  header,footer {position:absolute;left:48px;right:48px;display:flex;justify-content:space-between;align-items:center}
  header {top:29px;height:44px;border-bottom:1px solid #365264;padding-bottom:14px}
  footer {bottom:22px;color:#aebfd1;font-size:17px;letter-spacing:.02em}
  .brand {font-size:22px;font-weight:720} .accent,.eyebrow {color:#8ae1e5}
  .tag,.eyebrow {font:700 17px/1.25 ui-monospace,monospace;letter-spacing:.085em;text-transform:uppercase}
  .tag {color:#bdcdd9}
  main {position:absolute;inset:105px 48px 68px;display:grid;grid-template-columns:385px 1fr;align-items:center;gap:36px}
  h1,h2,p {margin:0} h1 {font-size:62px;line-height:1.02;letter-spacing:-.045em}
  h1.team {font-size:51px;white-space:nowrap}
  .eyebrow {margin:0 0 16px} .caption {max-width:370px;margin-top:19px;font-size:25px;line-height:1.3;color:#d8e8f5}
  .note {margin-top:19px;color:#a6bed1;font-size:18px;line-height:1.3}
  .screen {min-height:375px;max-width:100%;margin:0;display:grid;align-content:center;gap:12px;padding:15px;background:#0f1d2a;border:1px solid #3b586e;border-radius:19px;box-shadow:0 22px 50px #0007}
  .screen img {display:block;width:100%;max-height:490px;object-fit:contain;border-radius:9px}
  .screen img.query {max-height:150px} .screen img.query + img {max-height:342px}
  .captioned {display:flex;justify-content:space-between;gap:12px;padding:0 5px;font:600 16px/1.4 ui-monospace,monospace;color:#d4e9fa}
  .catalog {display:grid;grid-template-columns:1fr 295px;align-items:center;gap:13px}
  .catalog img {max-height:445px} .catalog img.key {border:1px solid #3b586e}
  .url {display:inline-block;margin-top:24px;padding:12px 14px;border:1px solid #548a96;border-radius:7px;color:#b2f4f4;font-size:21px;white-space:nowrap}
  .progress {position:absolute;bottom:0;left:0;height:4px;background:#86e0e4}
`

function pitchShots(captures) {
  return [
    {seconds:2.25,tag:'Our team',title:'Ze Deutsche',caption:'NASA Space Apps Challenge 2026',image:captures.sky,team:true},
    {seconds:2.80,tag:'The challenge',title:'Planet X and SPHEREx',caption:'How can anyone spot changes in infrared observations?',image:captures.pair},
    {seconds:4.95,tag:'Our project',title:'SPHEREx Sky Viewer',caption:'Explore the infrared sky through time.',image:captures.sky},
    {seconds:2.65,tag:'Sky coordinates',title:'Choose a field',caption:'Enter sky coordinates or choose a verified example.',image:captures.first,inset:captures.picks,label:'Barnard’s Star · 2025-08-15 UTC'},
    {seconds:2.85,tag:'The timeline',title:'Watch it change',caption:'Step between actual dates in NASA’s open SPHEREx archive.',image:captures.second,label:'Barnard’s Star · 2026-03-22 UTC'},
    {seconds:3.25,tag:'Compare dates',title:'See what changed',caption:'Blue is fainter and orange is brighter in the later image.',note:'Saturation limits motion measurements.',image:captures.difference,label:'2025-08-15 → 2026-03-22 UTC'},
    {seconds:3.10,tag:'Add context',title:'Check known sources',caption:'ESA Gaia DR3 and NASA AllWISE give each field catalog context.',image:captures.pair,catalog:captures.catalog},
    {seconds:6.35,tag:'What comes next',title:'Share what you find',caption:'Students and citizen scientists can flag changes and check them as more observations arrive.',url:true,image:captures.pair},
  ]
}

function shotHtml(shot, width) {
  const picture = (image, className = '') => `<img class="${className}" src="${asImage(image)}" alt="">`
  return `<meta charset="utf-8"><style>${style}</style>
    <header><span class="brand"><span class="accent">✧</span> SPHEREx Sky Viewer</span><span class="tag">Team Ze Deutsche</span></header>
    <main><article><p class="eyebrow">${shot.tag}</p><h1${shot.team ? ' class="team"' : ''}>${shot.title}</h1><p class="caption">${shot.caption}</p>
    ${shot.note ? `<p class="note">${shot.note}</p>` : ''}
    ${shot.url ? `<p class="url">${viewerAddress}</p>` : ''}</article>
    <figure class="screen">${shot.inset ? picture(shot.inset,'query') : ''}
    ${shot.catalog ? `<div class="catalog">${picture(shot.image)}${picture(shot.catalog,'key')}</div>` : picture(shot.image)}
    ${shot.label ? `<figcaption class="captioned">${shot.label}</figcaption>` : ''}</figure></main>
    <footer><span>Real observations · NASA SPHEREx / NASA-IPAC IRSA</span><span>${shot.url ? 'Video and viewer made with Codex assistance' : 'NASA Space Apps Challenge 2026'}</span></footer>
    <div class="progress" style="width:${width}%"></div>`
}

try {
  assert.match(viewerAddress,/^[a-zA-Z0-9.-]+$/)
  const captures = await captureViewer()
  const shots = pitchShots(captures)
  const frameCounts = shots.map(shot=>Math.round(shot.seconds*fps))
  const total = frameCounts.reduce((sum,count)=>sum+count,0)
  assert.ok(total/fps < 30, 'Pitch must be shorter than 30 seconds')
  const editor = await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1})
  const encoder = spawn(ffmpeg,['-hide_banner','-loglevel','error','-y','-f','image2pipe','-framerate',String(fps),
    '-c:v','mjpeg','-i','pipe:0','-an','-c:v','libvpx-vp9','-pix_fmt','yuv420p','-deadline','good','-cpu-used','5',
    '-crf','25','-b:v','0','-threads','4','-f','webm',output],{stdio:['pipe','ignore','inherit']})
  const exited = once(encoder,'exit')
  try {
    let elapsed = 0
    for (const [index,shot] of shots.entries()) {
      const count = frameCounts[index]
      await editor.setContent(shotHtml(shot,100*(elapsed+count)/total),{waitUntil:'load'})
      const rendered = await editor.screenshot({type:'jpeg',quality:96})
      for (let frame=0;frame<count;frame++) {
        if (!encoder.stdin.write(rendered)) await once(encoder.stdin,'drain')
      }
      elapsed += count
    }
    encoder.stdin.end()
    const [code] = await exited
    assert.equal(code,0,'VP9 encoding failed')
    console.log(`${output} · ${total/fps} seconds · 1280×720 · ${fps} fps`)
  } finally {
    if (encoder.exitCode === null) encoder.kill()
    await editor.close()
  }
} finally {
  await browser.close()
}
