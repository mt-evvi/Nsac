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
