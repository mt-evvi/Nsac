import assert from 'node:assert/strict'
import { test } from 'node:test'
import { matchedLightCurve } from '../src/analysis.ts'

test('the light curve keeps one wavelength-matched sample per visit and sorts actual dates', () => {
  const sample = {sampleStatus:'measured' as const, flux:43, wavelengthUm:4.52, bandwidthUm:.04, detector:6}
  const samples = [
    {...sample, visitId:'C', startUtc:'2025-05-01T01:00:00Z'},
    {...sample, visitId:'A', startUtc:'2025-01-01T01:00:00Z'},
    {...sample, visitId:'A', startUtc:'2025-01-01T01:15:00Z', wavelengthUm:4.53},
    {...sample, visitId:'B', startUtc:'2025-02-01T01:00:00Z', wavelengthUm:4.51},
    {...sample, visitId:'D', startUtc:'2025-06-01T01:00:00Z', wavelengthUm:4.59},
    {...sample, visitId:'E', startUtc:'2025-06-01T02:00:00Z', detector:5},
    {...sample, visitId:'F', startUtc:'2025-06-01T03:00:00Z', sampleStatus:'missing' as const},
  ]
  assert.deepEqual(matchedLightCurve(samples).map(row => row.visitId), ['A','B','C'])
})
