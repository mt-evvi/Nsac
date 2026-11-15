# Build and release verification

## First real-data slice

Field center ICRS RA 269.45°, Dec +4.768°, 3 arcminutes wide. Both files are DR1 Level 2 detector 6 products. The WCS places them on one 29 × 29 north-up TAN grid. The official CWAVE and CBAND map was `spectral_wcs_D6_spx_cal-swcs-v5-2026-191.fits`.

| Observation ID | FITS UTC start and end | Calibrated wavelength / bandwidth | Geometric coverage / valid pixels | Download |
| --- | --- | --- | --- | --- |
| `2025W33_2C_0321_1` | 2025-08-15 20:45:11.337–20:47:06.455 | 4.928207 / 0.036792 µm | 90.6% / 83.5% | 3,962,880 bytes |
| `2026W12_2A_0520_4` | 2026-03-22 08:50:47.183–08:52:42.300 | 4.929935 / 0.038216 µm | 100% / 94.8% | 3,974,400 bytes |

The baseline is 218.50 days. Common valid wavelength-matched coverage is 79.67%. The early 3′ archive download took 7.29 seconds in a cold transport probe. IRSA returned transient errors on some repeats. The pair supports visual comparison. Saturation-related flags and zero accepted reference centroids prevent a quantitative motion claim. The sky residual scale was 0.091 MJy/sr after shared sky matching. [First observation cutout](https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W33_2C/l2b-v27-2026-228/6/level2_2025W33_2C_0321_1D6_spx_l2b-v27-2026-228.fits?center=269.45,4.768&size=0.05) · [Second observation cutout](https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2026W12_2A/l2b-v27-2026-235/6/level2_2026W12_2A_0520_4D6_spx_l2b-v27-2026-235.fits?center=269.45,4.768&size=0.066) · [DR1 DOI](https://doi.org/10.26131/IRSA678)

## Hosting

The server owner approved the hostname and one controlled Caddy restart. The staged site uses `spherex.144.91.89.214.sslip.io`. On Caddy 2.10.2, the signal reload printed `not implemented`; after the approved restart, HTTP-01 validation produced a trusted certificate. The existing neighboring HTTPS route returned HTTP 200. The SPHEREx loopback service runs under a systemd dynamic user and responds publicly at `/healthz`. A full `/readyz` check belongs to each staged application build.

## Spectrum validation tolerance

Use the same DR1/QR3 release, individual image ID, detector, position, and observation time when matching a point-source ePSF sample to IRSA Data Explorer forced photometry. Restrict to isolated sources with healthy fits and match central wavelength within 0.005 µm. For retained rows, compare flux within 15% or combined 3σ uncertainty, whichever is larger. Record any systematic offset and leave the spectrum labeled as an independent extraction until a reference comparison passes. [IRSA spectrophotometry reference](https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html)

## Core milestone

All five named examples and the separate literal NASA WISE field pass bundle health and Chromium playback with live discovery forced to return 503. A fresh browser context restores the exact Barnard exposure and comparison link. Keyboard stepping, side-by-side, signed difference legend and 390-pixel mobile layout passed in signed-out Chromium. [Five-target verification matrix](TARGET_TEST_MATRIX.md)

The November 15 covered non-preset request used RA 337.8783221°, Dec −5.1891588°, D1, 3′, May 18–24, 2026. Discovery returned 17 products across three UTC dates, in one independent visit. The earliest prepared image was `level2_2026W21_1A_0442_1D1_spx_l2b-v27-2026-268`, UTC May 20, 2026 at 21:31:37.849, with 99.76% geometric coverage and 84.78% of pixels valid. Discovery took 3.759 s cold and 0.062 s warm. Frame preparation took 16.096 s cold, including 3,977,280 archive bytes, and 0.034 s warm. The image response was 1,441 bytes with an immutable cache policy. These timings were measured from the development host over the deployed HTTPS route.

The separate DR1 coadded spectrum made 104 bounded byte-range reads, transferring 58,000 bytes in 7.66 s. Barnard's center returned 68 finite channels, 32 no-data channels and two known blank dichroic channels. The cube has no observation date axis or channel variance. [IRSA HiPS cube reference](https://caltech-ipac.github.io/irsa-tutorials/spherex-hipscube/)

## External HTTPS

The owner enabled TCP 443 in the provider firewall after the initial external timeouts. Independent HTTP-over-TLS checks of the home page then returned HTTP 200 from Germany, France, Poland and the United States. Caddy continued serving the existing vhosts without a second restart. [External HTTPS home-page checks](https://check-host.net/check-report/57f815d8k2bd)

## Calibrated live spectrum

An extended spectrum at ICRS 133.72675693°, −7.22425717° selected an isolated source near the WISE field center. The deployed native ePSF path returned 4061.93 ± 177.97 µJy at 4.512709 µm in DR1 observation `2025W46_1A_0076_3`, detector 6, UTC 2025-11-10 07:14:12.445, with a 0.035756 µm bandwidth and fit metric 2.09. The public job took 14.27 seconds and downloaded a 3,962,880-byte cutout plus versioned calibration. R Draconis correctly refused flux extraction where its local sky pixels were flagged. The independently completed IRSA Data Explorer point-source job used the same position, detector 6 and a five-minute UTC window, 07:13:00–07:18:00. The matched DID was `ivo://irsa.ipac/spherex_dr1?2025W46_1A_0076_3/D6`, midpoint 2025-11-10T07:15:10.004Z. The reference reported 3943.352 ± 203.792 µJy at 4.512709 µm, width 0.03575636 µm, fit metric 2.84, and flag 2097152 (source). The absolute difference is 118.576 µJy, 3.01% or 0.44 combined standard deviations. This passes the predeclared threshold. The downloaded official VOTable's SHA-256 is `efd6d6108b640df4af4aaf276cfd1972d7b64a0fafdeda942b016e346d4dcf46`. [Reference method](https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html)

## Demo and contingency build

The English 23.16-second screen recording shows two real Barnard dates and their signed difference. It labels the saturation limit and NASA/IPAC IRSA provenance. The static fallback can be built at a standalone origin or under the `/Nsac/` project-site prefix with the same shared links, playback, blink and side-by-side selection. [Capture script](../web/scripts/record-demo.mjs) · [Static build instructions](../README.md#static-contingency)

The inactive systemd slot browser test caught an intermittent job identifier mismatch on the polling route. The fixed producer and backward-compatible route validator passed a regression that forces a punctuation-leading nonce. The staged full browser suite then passed.

The independent Chromium network fixture verifies NASA sexagesimal and Unicode minus input, negative-zero declination, 7-day and 30-day UTC boundaries, simultaneous detector choices, and one usable date. It forces an older request to finish after a replacement, checks that the old response prepares zero frames, and checks that a drag issues one frame request on release. Playback causes no unsolicited analysis API calls. The released site preserved all six bundled views during a later official IRSA HTTP 502, and custom lookup reported the upstream error without substituting a preset.
