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

Two further 50″ SIA searches at the tutorial position and at RA 150.11916°, Dec +2.2058333° both returned HTTP 502. A bounded TAP query using the documented `spherex.artifact` and `spherex.plane` join also returned HTTP 502. As a control on available data, 24 windows offset from the historical WISE center were reprojected from the cached D6 pair. The best trial had 79.05% matched coverage and a 0.117-native-pixel median offset from two references. The three-reference minimum still gated quantitative ranking. [IRSA TAP example](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/)

Two directly identified D1 cutouts also covered an independent 8′ control field 8.5′ north of RW Aurigae, centered at ICRS 76.95654167°, +30.54311111°. Each transferred 4,104,000 bytes. The DR1 exposure began 2025-09-03 at 23:53:31.971 UTC and the QR3 exposure began 2026-09-09 at 21:42:13.876 UTC. Both have a 78 × 78 aligned grid. Their calibrated center wavelengths are 0.955947 and 0.957899 µm, with 0.024722 and 0.024678 µm bandwidths. Common valid coverage was 82.86%. Five stable image references gave a median registration residual of 0.0667 native pixel (0.410″) and a centered median residual of 0.0240 pixel. One reference matched Gaia DR3 `156434910925142144` uniquely within 0.8 pixel in both exposures. Its proper motion components are +3.018 and −2.418 mas/yr. [DR1 cutout](https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W36_1A/l2b-v27-2026-232/1/level2_2025W36_1A_0663_1D1_spx_l2b-v27-2026-232.fits?center=76.95654167%2C30.54311111&size=0.16741667) · [QR3 cutout](https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2/2026W37_1A/l2b-v27-2026-255/1/level2_2026W37_1A_0524_1D1_spx_l2b-v27-2026-255.fits?center=76.95654167%2C30.54311111&size=0.16741667)

The visual comparison measured a robust sky residual of 0.02817 MJy/sr over 4,381 background pixels. Applying both effective-PSF masks left 5.64% valid support and returned `LOW_KERNEL_SUPPORT`. Quantitative rankings were suppressed, leaving the empirical false-positive rate unmeasured. Reproduce the cutouts, their hashes, and difference with `python -m tools.verify_real_slice --field rw-aurigae-control --output /tmp/spherex-rw-control`.

A second 8′ field at ICRS 77.12658214°, +31.06108277° used the same two D1 products. The two official cutouts transferred 8,196,480 bytes in total. All 85.62% of common usable pixels passed the local wavelength gate. Three stable references gave a 0.0915-pixel median registration residual. The visual sky residual was 0.02719 MJy/sr over 4,670 background pixels. After applying both ePSF masks, 10.91% retained full support and ranking was suppressed again. [DR1 cutout](https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W36_1A/l2b-v27-2026-232/1/level2_2025W36_1A_0663_1D1_spx_l2b-v27-2026-232.fits?center=77.12658214%2C31.06108277&size=0.16741667) · [QR3 cutout](https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2/2026W37_1A/l2b-v27-2026-255/1/level2_2026W37_1A_0524_1D1_spx_l2b-v27-2026-255.fits?center=77.12658214%2C31.06108277&size=0.16741667)

## Injected source classification and independent holdout

Each reported run used three 64 × 64 simulated visits separated by 12 days, seeded Gaussian sky noise of 0.25 MJy/sr per pixel, five stable references, a moving source (1.15 pixels per visit), a fixed variable, and one single-pixel cosmic-ray injection per visit. The table scales the mover's amplitude and the variable's light curve together. Nominal peak S/N is the injected peak amplitude of the mover divided by the input pixel noise. A true positive requires the correct label and first-epoch position within 0.8 pixel. A wrong label counts as a false positive for this metric.

| Nominal peak S/N | True positives | False positives | Precision | Recall |
| ---: | ---: | ---: | ---: | ---: |
| 2.8 | 0 | 0 | Undefined | 0/2 |
| 8 | 0 | 1 | 0/1 | 0/2 |
| 32 | 1 | 0 | 1/1 | 1/2 |
| 220 | 2 | 0 | 2/2 | 2/2 |

The high-S/N track fit used the first three measurements. The next visit was held out and occurred at the 12-day forecast limit. The forecast was 0.204 arcseconds from the injected position, within its 4.404 arcsecond approximate 95% radius. Independent tests verify RA wrap, same-visit and masked-pixel rejection, and suppression of a forecast for stationary, ambiguous, or poorly fit associations. These fixtures test implementation behavior and do not estimate sky-wide detection performance.

An independent calibrated two-epoch fixture recovered both a PSF-shaped appearance and disappearance within 0.01 pixel after matching the ePSFs. It excluded a third change centered on a masked pixel, and vetoed an isolated input spike that would have broadened during convolution. When the fixture used approximate wavelength calibration, signed detection returned no groups. The signed results carry the two frame times and their centroid covariance. Their significance propagates a conservative correlated-noise bound, and forecasting remains limited to associated sources across independent visits.

A separate four-epoch calibrated synthetic fixture checked a competing source close to the fixed search radius. The association now projects the two centroid covariances along the separation direction, with the existing registration floor, elapsed-time motion allowance and eight-pixel cap. The correct three-visit track survived a precise competing centroid outside its uncertainty envelope. A competitor with greater uncertainty in the separation direction was retained as ambiguous. The recovered forecast was 0.806″ from the held-out centroid, within the approximate 4.404″ radius.

Run `python -m pytest -q tests/test_analysis.py` for the deterministic comparison, ranking, motion, and path checks.
