# Exploring neighboring sky

The search form keeps the entered target. The viewer separately shows the current ICRS view center. Dragging moves both comparison panes together, and scrolling or pinching zooms around the pointer. **Return to entered position** restores the target. Mark placement takes priority over navigation.

After movement stops for 600 ms, the viewer requests a neighboring field only when the visible area extends past the loaded image and its center has moved at least 15% of a field width. It keeps the selected observation date and detector. It prepares the selected image, or the two selected comparison images, before replacing the old field. Superseded client requests are canceled. Old decoded images are closed after replacement. Blank space beyond the loaded image is unrequested sky, while hatching inside an image indicates missing or masked data.

## Controlling archive work

Automatic browsing uses `POST /api/v1/series/{seriesId}/recenter` with only `raDeg` and `decDeg`. The server inherits the source field width, dates and filters. It reuses known exposure identities and makes **no archive metadata request**. Each step is limited to two current field widths using spherical separation. Old pixels, coverage and position-dependent calibration are discarded; ordinary frame preparation checks the new cutout. The returned manifest is explicitly incomplete because other exposures may exist outside the cached selection.

**Search archive here** discovers other exposures at the view center on request. If the chosen observation is unavailable, the viewer tries the earliest suitable result within its preparation limit and explains the date change. It opens a single image if a previous comparison cannot be restored. Automatic panning keeps the selected dates and detector. A failed search or preparation leaves the previous view available. The viewer distinguishes an unavailable metadata service from a completed search with no coverage.

There is no dataset mirroring. Interactive requests use bounded cutouts at 1–8 arcminutes and at most 128 × 128 output pixels. The server's derived-product cache has a 4 GiB logical LRU limit and a 20 GiB disk reserve. A separate finite calibration cache is at most 684 MiB for the allowed releases and detectors. SQLite may retain freed pages. Jobs, transfer sizes and concurrency keep the limits in [PRODUCTION_AND_BUDGETS.md](PRODUCTION_AND_BUDGETS.md): six new jobs per minute per IP, two active jobs, two archive connections, and an 8 GiB rolling daily archive allowance. Browsing does not prefetch other fields or observations.

## November 15 live checks

A real Barnard move from RA 269.450000°, Dec +4.768000° to RA 269.462656°, Dec +4.768000° completed in 9.106 seconds on the staged release. The browser sent one recenter request and one selected-frame preparation request, with no archive discovery. Repeating the move on the final staged build completed in 1.423 seconds and required only the cached recenter response. The input coordinates stayed unchanged. The resulting cutout had 100% geometric coverage and 95% usable pixels.

Three seeded random positions were tested over public HTTPS, each with a 1′ field, detector 6, and May 18–24, 2026 dates. No frame preparation or image download was requested.

| RA / Dec in degrees | Result |
| --- | --- |
| 108.3014551 / −2.7862967 | Metadata job failed with retryable `UPSTREAM_UNAVAILABLE` after 2.023 s. |
| 275.8515064 / +18.7950398 | Protective `CIRCUIT_OPEN` response in 0.008 s; no new archive job. |
| 217.8036015 / −17.2633214 | Protective `CIRCUIT_OPEN` response in 0.024 s; no new archive job. |

Two independent direct checks of IRSA `/SIA`, one per DR1/QR3 collection with `MAXREC=1` and no retries, each returned HTTP 502 with a 341-byte proxy error page. These results leave coverage at the random coordinates unknown. The successful neighboring cutout demonstrates that image access can work while metadata discovery is degraded. The subsequent release split the circuit for archive search from the circuit for image data. Both circuits share the original connection and byte limits.

Deterministic verification includes 81 backend tests and Chromium checks for settled requests, preserved inputs, spherical wrap and poles, shared views, cancellation, old-image release, outage recovery, and explicit discovery. Starting plan and specification files retain their original checksums.
