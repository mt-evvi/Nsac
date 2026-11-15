import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pixelToSky, skyToPixel, projectCatalog } from '../src/analysis.ts'

const grid = {
  width: 29, height: 29, crpix: [15, 15], crval: [269.45, 4.768],
  cd: [[-.0017241379310344827, 0], [0, .0017241379310344827]],
}
function close(actual: number, expected: number, tolerance = 1e-9) {
  assert.ok(Math.abs(actual - expected) < tolerance, `${actual} vs ${expected} at tolerance ${tolerance}`)
}

test('zero-based north-up TAN transform agrees with Astropy for Barnard and a rotated polar grid', () => {
  const polar = { ...grid, crval: [359.999, -89.93], cd: [[-.003, .0003], [.00015, .003]] }
  const cases = [
    {grid, x: 10, y: 17, ra: 269.4569205526202, dec: 4.773172379121177},
    {grid: polar, x: 7.25, y: 20.75, ra: 14.014473867750894, dec: -89.9080244250081},
  ]
  for (const datum of cases) {
    const sky = pixelToSky(datum.grid, {x: datum.x, y: datum.y})
    close(sky.raDeg, datum.ra)
    close(sky.decDeg, datum.dec)
    const position = skyToPixel(datum.grid, sky)!
    close(position.x, datum.x)
    close(position.y, datum.y)
  }
})

test('Gaia proper motion agrees with Astropy and AllWISE retains its reference place', () => {
  const row = {catalogId: 'synthetic', referenceEpoch: 2016, referenceRaDeg: 269.45,
    referenceDecDeg: 4.768, pmRaMasYr: -801, pmDecMasYr: 10362}
  const when = Date.parse('2026-03-22T08:51:43Z')
  const broad = {...grid, height: 64}
  const [gaia] = projectCatalog([row], 'gaia_dr3', broad, when)
  // Browser uses UTC Julian years, within 0.003 arcseconds of the Astropy TCB epoch.
  close(gaia.x, 15.318896531989711, .0005)
  close(gaia.y, 31.061680230110298, .0005)
  assert.equal(gaia.properMotionApplied, true)
  assert.equal(projectCatalog([row], 'gaia_dr3', grid, when).length, 0)
  const [allwise] = projectCatalog([row], 'allwise', broad, when)
  close(allwise.x, 14)
  close(allwise.y, 14)
  assert.equal(allwise.properMotionApplied, false)
})
