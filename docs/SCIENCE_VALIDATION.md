# Comparison and tracking validation

## Effective PSF matching

Calibrated comparisons use the locally sampled archived effective PSF from each exposure. A is convolved with B's kernel, and B with A's. Variance uses squared weights. Each analyzed pixel requires unmasked, wavelength-compatible input support across both kernels. The matcher requires at least three stable references, a median centroid residual under 0.30 native pixel before and after convolution, and agreement in relative flux scale, width, and normalized source profiles. A failed gate returns a visual comparison with its measured coverage and reason. Only vetted pixels feed the residual score and ranked brightness changes. [Comparison specification](COMPARISON_AND_TRACKING.md)

An injected static field with two different kernels, a 4% relative scale difference, and a 5 MJy/sr additive background offset recovered a ratio of 1.0400. The maximum absolute matched residual was 2.9 × 10⁻¹⁴ MJy/sr over 82.13% valid pixels. The propagated variance matched the expected squared-weight calculation. An asymmetric kernel test checked the reflected footprint and a wavelength-mismatched input pixel. Separate tests blocked quantitative output for insufficient convolved coverage, absent references, and an invalid kernel while retaining visual comparisons.

## Real archives

The extraction returned a 9 × 9 effective PSF for each of 12 reprocessed local FITS products from Barnard’s Star, both WISE 0855 fields, RW Aurigae, and R Draconis. The real pairs below were evaluated before convolution. Their currently bundled coverage or reference counts prevented a quantitative ePSF match.

| Pair or field | Common valid wavelength coverage | Accepted references | Result |
| --- | ---: | ---: | --- |
| Barnard’s Star, 2025-08-15 and 2026-03-22 | 79.67% | 0 | Visual comparison |
| WISE 0855, epoch-corrected | 76.01% | 0 | Visual comparison |
| WISE 0855, literal NASA field | 65.10% | 2 | Visual comparison |
| RW Aurigae, 3 tested pairs | 62.78–82.40% | 0–1 | Visual comparisons |
| R Draconis, 3 tested pairs | 73.13–79.31% | 0 | Visual comparisons |
| Epsilon Indi B, 3 bundled pairs | 36.3–57.6% | Coverage gate failed | Independent frames and visual playback |

A separate live check widened the literal NASA WISE pair to 8′. Each image was mostly usable in isolation (91.7% and 89.1%), but their common wavelength-matched area fell below the 60% comparison threshold.

The real comparisons verify archive handling and conservative rejection. Quantitative real-field astrometry, real-source classification, and a measured forecast remain unverified. The exact FITS observation identities and target limitations are recorded in the matrix. [Target verification matrix](TARGET_TEST_MATRIX.md)

## Non-preset quiet field

An 8′ query at RA 150.7817877°, Dec +3.3502204° used the public IRSA SPHEREx tutorial position near COSMOS. The April 2025–November 2026 DR1 and QR3 metadata queries returned `UPSTREAM_UNAVAILABLE`. A narrowed April–December 2025 DR1 retry made two bounded attempts and returned no response bytes and zero indexed rows. IRSA reported that the upstream service did not return the requested data. No FITS cutout request was issued. Registration, Gaia-stationary references, residual noise, and the false-positive rate remain unmeasured for this field. [IRSA tutorial position](https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo/)

## Injected source classification and independent holdout

Each reported run used three 64 × 64 simulated visits separated by 12 days, seeded Gaussian sky noise of 0.25 MJy/sr per pixel, five stable references, a moving source (1.15 pixels per visit), a fixed variable, and one single-pixel cosmic-ray injection per visit. The table scales the mover's amplitude and the variable's light curve together. Nominal peak S/N is the injected peak amplitude of the mover divided by the input pixel noise. A true positive requires the correct label and first-epoch position within 0.8 pixel. A wrong label counts as a false positive for this metric.

| Nominal peak S/N | True positives | False positives | Precision | Recall |
| ---: | ---: | ---: | ---: | ---: |
| 2.8 | 0 | 0 | Undefined | 0/2 |
| 8 | 0 | 1 | 0/1 | 0/2 |
| 32 | 1 | 0 | 1/1 | 1/2 |
| 220 | 2 | 0 | 2/2 | 2/2 |

The high-S/N track fit used the first three measurements. The next visit was held out and occurred at the 12-day forecast limit. The forecast was 0.204 arcseconds from the injected position, within its 4.404 arcsecond approximate 95% radius. Independent tests verify RA wrap, same-visit and masked-pixel rejection, and suppression of a forecast for stationary, ambiguous, or poorly fit associations. These fixtures test implementation behavior and do not estimate sky-wide detection performance.

Run `python -m pytest -q tests/test_analysis.py` for the deterministic comparison, ranking, motion, and path checks.
