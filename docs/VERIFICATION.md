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

After the release switched to `a4d5cb6`, the same non-preset request recovered its 17 cached products in 0.055 s while IRSA was degraded. The response labeled the date of the previous compatible index. The exact prepared frame and its 1,441-byte PNG were served again in 0.054 s and remained available on repeat.

An isolated ten-visitor HTTP test submitted distinct fresh requests during a simulated archive outage. The two available workers started two jobs and the other eight queued. An eleventh fresh request returned `503 QUEUE_FULL`. All eleven visitors fetched every Barnard preset image during the overload. The requests completed in 0.231 s. The eight abandoned queued jobs reported `JOB_CANCELLED`, and both running jobs reported `UPSTREAM_UNAVAILABLE`.

The daily metadata inventory was verified against IRSA's anonymous S3 mirror. Three requests transferred 12,163 bytes. The DR1 listing contained 110 planning periods through `2026W20_1A`, and the QR3 listing contained 41 through `2026W40_2A`. The root also listed retired QR2 data. The collection allowlist remains DR1 and QR3. [IRSA cloud access](https://irsa.ipac.caltech.edu/cloud_access/#spherex)

All 16 bundled exposures have individual survey labels verified from their FITS IMAGE headers. `SPS_FLAGS=all_sky` and `NON_SURVEY=False` identify wide-survey observations. The planned ecliptic position angle `SPS_EPA` of 0° selects Survey 1 for DR1 or Survey 3 for QR3. An angle of 180° selects Survey 2 or 4, respectively. Four headers were recovered with 64 KiB range requests to the IRSA mirror. Their detectors and start and end timestamps matched the manifests. Barnard playback stepped through Surveys 2, 1 and 4 in observation order. Live indexing keeps an exposure in its UTC date slot until its pass is verified in the FITS header. [Explanatory Supplement, Section 2.4 and Table A.35](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf) · [IRSA release guide](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/)

The covered live index had 17 distinct D1 pairs within one hour, none within half the narrower estimated bandwidth. The nearest pair differed by 0.889 of that bandwidth. The deployed WISE preset coadd call reported `NO_COMPARABLE_FRAMES` for an anchor with no same-visit sibling and downloaded no FITS files. The inverse-variance calculation and versioned contributor identity passed controlled tests. A successful coadd of real near-simultaneous data is pending.

The Barnard AllWISE overlay returned 50 markers at the historical epoch over public HTTPS. The direct ESA Gaia TAP connection timed out from the deployment host. The Gaia adapter verified the same DR3 source positions through Heidelberg's documented mirror. The Barnard query took 0.752 s and returned 200 retained references (truncated) and 182 markers within the field, projected at the first exposure's epoch. The ESA endpoint remains the bounded fallback. [Heidelberg Gaia DR3 Lite](https://dc.g-vo.org/tableinfo/gaia.dr3lite)

## Follow-up release

The production release `local-9b700bdff4e671ec96c39b21` is identified by its deployment file checksums. Both Chromium suites passed in the inactive systemd slot. The public signed-out browser then repeated the preset playback, comparison, keyboard, direct-link and mobile checks. Public HTTPS returned the same 182 Gaia markers at the FITS exposure midpoint and 50 AllWISE markers at the historical epoch. The separate daily release inventory completed successfully. The known non-preset field again returned its 17 cached products with a stale-index warning while IRSA discovery was degraded. The previous application release remains available for rollback. Caddy's process stayed in place.

The same release passed the standalone `/Nsac/` static build check. Barnard's Survey 1 link restored after reload and the browser made zero API requests. The draft PR contains the previous release. The GitHub App installation available to this session lacked access to the private repository during this update, so the reviewed source and starting documents were archived locally.

## Readiness, monitoring and measurement provenance

The checksum-identified production release `local-dcf5acc1ef17a6ad2928f6c0` passed 62 Python tests, three frontend tests, both staged Chromium suites, and the public signed-out playback, comparison, link, keyboard and mobile smoke. The ready check confirmed the compiled shell, all six packaged example manifests and referenced files, and the cache schema. The service emitted structured metrics and job timing over the public run. Its first captured production sample counted 45 completed responses, 257,990 response body bytes, 365,573 bytes of packaged examples, and 0 HTTP 429s and 503s. Tests exercised both sustained warning conditions with three consecutive samples. The shared proxy PID remained unchanged, and the previous release remains available for rollback.

The public tracks endpoint preserved both rounded clicks at (53, 15) in the literal NASA WISE field. It verified centroids at (52.99090, 14.88441) and (53.04185, 14.95306) on the exact prepared exposures on 2025-11-10 and 2026-04-22. Both carried covariance and a 1.0373″ positional uncertainty. The job returned `TOO_FEW_EPOCHS` for a forecast. The centroids are field references, with no identification as WISE 0855. Chromium also verified both positions and frame provenance after a fresh share-link load and in the JSON download.

## Archive admission and outstanding coadd check

An isolated HTTP fixture returned `503 CIRCUIT_OPEN` for a fresh archive query and `429 DAILY_BUDGET` for a fresh catalog request in a combined 0.11 s. Both responses included `Retry-After`. Bundled playback assets and a comparison from local arrays succeeded in the same fixture. Deterministic tests verify that shared jobs can still accept another requester and that a locally refused half-open probe does not mark the archive reachable.

The DR1 cube citation was checked against IRSA's product documentation and an independent Barnard-center extract. The extract transferred 58,000 bytes and reported 68 measured values in 102 channels with DOI `10.26131/IRSA679`. [DR1 product guide](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html)

An additional coadd audit checked 896 distinct cached DR1 and QR3 pairs from the RW Aurigae control and the R Draconis field. Each pair used the same detector and exposures within an hour. The smallest estimated center gap was 0.884 of the narrower bandwidth, above the 0.5 limit. A 50″ North Ecliptic Pole check against the official deep collections returned HTTP 502 for QR3 and timed out for DR1. The bounded TAP fallback also timed out before any cutout could be requested. Real positive coadd acceptance remains unverified. [IRSA collection guide](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)

A coadd regression simulates a working anchor and an unavailable second exposure. The operation retains the retryable archive reason in that case. If all tested data are usable but exceed the match tolerance, the coadd still reports the wavelength or coverage result.

Production release `local-b019f3e893f1ae4c54dc3eaf` passed 67 Python tests, three frontend tests and both staged Chromium suites. The public signed-out viewer passed its playback, comparison, shared-link, keyboard and mobile checks after cutover. The real Barnard pair returned no signed residual groups and reported its unmet quantitative gate. A fresh public cube job returned DOI `10.26131/IRSA679`, 102 channels and 68 measured samples over 58,000 archive bytes. The previous release remains available for rollback, and the shared proxy process was preserved.

## Preset rebuild and playback limits

The batch rebuilt the two pinned Barnard exposures from archived SIA metadata and local calibrated FITS with zero downloaded bytes. Two separate runs produced the same content-addressed frame IDs and science manifest apart from generation time. In a two-target failover exercise, Barnard validated in temporary storage and Epsilon failed on a missing metadata file. The previous Barnard manifest matched its original bytes after the incomplete batch.

Chromium held three API and image transfers concurrently and verified that the fourth waited for a slot. A foreground selection joined one delayed adjacent request. The browser opened 13 different images with at most eight decoded rasters alive at once and preserved the visible comparison pane. Images with a 129-pixel side or a byte count above 256 KiB were rejected before decoding. The static `/Nsac/` build also played the real survey-pass sequence and restored a pinned share link without an API call.

The wider coadd search tested 1,744 cached same-detector pairs within one hour on a 65 × 65 grid across overlapping detector interiors. The smallest sampled wavelength separation was 0.841 times the narrower bandwidth. The compatibility gate allows at most 0.5. The isolated browser blocked the official Data Explorer before form submission, so no additional deep-field metadata or cutout was obtained through that route. [IRSA search guide](https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/searching.html)

Release `local-5c253c155ecb66ad38dcb1e6` passed 70 Python tests, three frontend tests, both Chromium suites on staging and the signed-out public browser smoke. A new one-day discovery request at the previously verified non-preset field returned retryable `UPSTREAM_UNAVAILABLE`. `/readyz` attributed the degraded sample to metadata discovery while the bundled examples and demo stayed available.

## Milestone acceptance status

| Build-plan milestone | Observed result and outstanding evidence |
| --- | --- |
| First real-data slice | Two calibrated, wavelength-compatible Barnard exposures on a shared WCS and a public HTTPS viewer. |
| Live viewer and core | A covered non-preset query previously succeeded cold over public HTTPS and reused cached products. Fresh discovery is now degraded. All five named fields and the separate historical WISE field play during a simulated outage. Share state and the time selectors passed browser checks. |
| Comparison and tracking | Tests verify the signed maps, calibrated residual grouping, exact mark provenance, candidate association and held-out synthetic forecasts. Two real quiet-field comparisons verified registration and residual noise. Both failed the effective-PSF support gate, leaving the real false-positive rate and real forecast unverified. |
| Spectra, overlays and coadd | Gaia and AllWISE passed public overlay checks. One measured spectrum agreed with the IRSA reference within the predeclared tolerance. The public cube transferred 58,000 bytes. Positive within-visit coadd passed controlled tests and remains unverified on real eligible exposures. |
| Release and submission | Public app, demo and static contingency verified. The first release was merged to `main` under MIT. Public source visibility and submission are still team actions. |

## Viewer usability follow-up

Release `local-1e29b8524e5b75d9f846258c` explains the image mask and adds pointer-centered wheel zoom, drag panning, touch pinch and keyboard navigation. Chromium verified synchronized movement across both comparison panes, exact mark and share coordinates, and mask and catalog explanations. The Epsilon Indi B exposure on 2026-04-20 has 91.4% usable pixels. Hatched pixels show data rejected by the mask or missing from the exposure.

The spectrum shows measured and unavailable channels, a brightness plot with uncertainty bars where available, and a readable sample list on mobile. The deterministic browser test verified that the extended retry preserves the selected position and photometry method. On the staged release the real Barnard DR1 cube plotted 68 measurements and marked the remaining 34 channels unavailable. Both desktop and phone-sized layouts passed.

## Bounded neighboring-sky navigation

Release `local-f392d03de36d194382d2387f` adds neighboring cutouts after a settled drag while retaining the entered target. Nearby movement reuses cached exposure identities and does not repeat metadata discovery. An explicit **Search archive here** control can discover other exposures at the visible center. Failed or superseded work retains the last loaded field. Both comparison images swap together, old decoded images are released, and restored shared views preserve the target and viewed center separately.

All 81 Python tests, three frontend tests, type checking, and all three Chromium suites passed. The final public HTTPS build passed the navigation fixture and signed-out playback, comparison, shared-link, keyboard and mobile checks. The regenerated static `/Nsac/` copy restored a shared observation on mobile with no API requests. The previous app release remains in the inactive slot, and the shared Caddy process retained PID 1817234.

A real neighboring Barnard cutout loaded in 9.106 seconds cold and 1.423 seconds warm. Three random 1′ metadata-only lookups revealed an IRSA metadata outage: one retryable upstream failure followed by two circuit rejections with no further archive work. Both official SIA collection probes returned HTTP 502. No frame or image download was requested by the random probes. These results do not establish absent coverage. [Navigation, resource limits and exact live test positions](SKY_NAVIGATION.md)

Original planning and specification checksums, including the original README snapshot, remain unchanged. The current source and fallback build were saved locally because the newly installed GitHub connector still returned an unavailable-tool error and the server CLI required renewed repository authorization. No GitHub CI result is claimed for this follow-up.

## Archive search outage and team footer

On November 15, official DR1 and QR3 SIA requests with `MAXREC=1` timed out even without date filters. The documented TAP query returned HTTP 502. A single-prefix AWS query returned HTTP 200 and listed a DR1 Level 2 planning period. These probes read 816 bytes in total and no images. The failure was observed in archive discovery, while the archived dataset remained accessible. [IRSA search and access documentation](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)

Release `local-6487093cf90f20e562b2b90c` isolates the discovery circuit from image data. Both still share the two-connection limit and daily transfer allowance. On staging, a fresh search returned `UPSTREAM_UNAVAILABLE` after 12.08 seconds. A new cutout of a known Barnard exposure then prepared in 4.05 seconds, with 100% geometric coverage and 91.7% usable pixels. Readiness reported discovery degraded and cutouts reachable.

All 87 Python tests, three frontend tests and three staged Chromium suites passed. The public signed-out browser verified the bundled examples, comparison, sharing, keyboard controls, phone layout, the Ze Deutsche footer link and demo delivery. Caddy remained on PID 1817234. Fresh searches remain dependent on IRSA. [Submission copy](SUBMISSION.md)

## Explicit search and archive recovery

Release `local-984379a643bea8651ef4a9ef` opens the earliest suitable indexed observation when an explicit archive search cannot restore the selected UTC date and detector. It explains when it can only open a single exposure. Return to target can select an available date from the saved target index. Automatic panning still preserves the selected observations. The Chromium fixture starts with a comparison, returns disjoint dates in an explicit search, checks the earliest new date and released comparison, and returns to the original image without a new search.

IRSA discovery validates the VOTable before recording a successful transfer. Tests cover malformed HTTP 200 responses, VOTable errors, a valid partial response with overflow, and independent cutout access during discovery cooldown. All 88 Python tests, three frontend tests and three staged Chromium suites passed. All six example bundles passed the provenance and image checks.

The public navigation regression and signed-out smoke checks passed after activation. Caddy retained PID 1817234. Both the GitHub CLI and connector returned 404 for the private project repository, and the connector was signed in under a different account from the CLI. The current release source was preserved locally.

## Failed coordinate searches and the shared row budget

Release `local-1148e474748d3ea904b5b755` keeps the last usable view when a new coordinate search fails, finds no observations, or cannot prepare a frame. The form keeps the attempted input and the share link continues to identify the visible comparison. The browser test also verifies that a successful replacement starts a new field and clears the old comparison.

Each discovery job now reserves a shared budget of 4,000 SIA rows across DR1 and QR3 before requesting pages. An oversized reply is sliced before indexing and the manifest is marked incomplete. The two-collection fixtures verified the 4,000-row limit, the per-response 500-row request limit, the 12-attempt ceiling and preservation of usable partial results. All 90 Python tests, three frontend tests and three staged Chromium suites passed.

A recovery probe for a previously covered non-preset position used one DR1 SIA request with `MAXREC=1` and timed out after 7.34 seconds. Both GitHub access paths still returned 404 for the project repository. Offline verification recovered one eligible centroid for Epsilon Indi B, while the available metadata yielded no compatible four-visit holdout sequence including it. [Science validation](SCIENCE_VALIDATION.md)

The signed-out production browser passed the navigation and example checks. The rebuilt static fallback played an observation and restored its shared link on a phone viewport with zero API requests. Caddy retained PID 1817234.

## Coadd provenance and source review

Release `local-099c89b286feb68410c99fef` lists each contributing exposure and its UTC range in Frame details. The Chromium fixture verified both contributors on a restored coadd link and checked that only IRSA product addresses become links. The comparison suite passed on staging and public HTTPS. The staged example and mobile smoke checks passed.

The archived metadata screen across the six example centers found 2,264 distinct same-series, same-visit, same-detector pairs within one hour. Of these, 2,248 had both passband estimates. The smallest estimated center gap was 0.861 times the narrower bandwidth, above the 0.5 limit. One bounded DR1 deep survey search at RA 276.26°, Dec +64.82° covering 2025-04-28 12:50–14:10 UTC timed out after 8.384 seconds. It made no cutout requests. The contributor UI and weighted-mean calculation passed controlled checks, while a real positive coadd remains unverified. [IRSA archive search reference](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)

Repository access recovered through the GitHub connector. Draft [PR #2](https://github.com/mt-evvi/Nsac/pull/2) contains the verified changes after the first release. Its initial head `190e37f3ac70df34687763925cff00954da39f10` passed [Verify SPHEREx](https://github.com/mt-evvi/Nsac/actions/runs/43760967005).

## Updated judging video

Release `local-5e29382ce7da0e763ba8038e` replaced the original demo and added an MP4 copy. The updated video introduces Ze Deutsche and the Planet X and SPHEREx challenge. It shows the August 15, 2025 and March 22, 2026 Barnard’s Star observations, their signed difference, and the catalog controls. The English captions credit NASA and ESA and explain the saturation limit. The last frame gives the public viewer address.

Chromium played both signed-out HTTPS links to the end at 1280 × 720. The measured durations were 28.3252 seconds for MP4 and 28.20 seconds for WebM. The MP4 returned HTTP 206 for a byte-range request. The [capture script](../web/scripts/record-pitch.mjs) uses the two bundled images and one locally computed comparison. [Submission MP4](https://spherex.144.91.89.214.sslip.io/assets/spherex-demo-2026.mp4) · [WebM copy](https://spherex.144.91.89.214.sslip.io/assets/spherex-demo.webm)

## Exact-field cache fallback

A direct DR1 SIA request at the known Barnard coordinates with `MAXREC=1` timed out after 7.33 seconds. Release `local-2e8d7589757ba7ae5f2dddc5` makes the distinction between unavailable archive discovery and unknown coverage explicit. During an archive failure, a typed search can use a bundled result only when the center and field width match and all bundled frames satisfy the requested filters. It displays the partial result with a cache notice. Unrelated searches and incompatible filters keep the prior image and report the failure.

The Reading the image guide distinguishes hatched pixels rejected from measurements, solid dark measured pixels, and sky beyond a loaded cutout. The 90 backend tests, three frontend tests, all three local Chromium suites and the staged smoke passed. The browser fixture checked one attempted archive request, real bundled playback, offline share reload and retention of the previous view with an incompatible detector filter.
