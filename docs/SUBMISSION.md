# NASA Space Apps Challenge submission

**Project Name**

SPHEREx Sky Viewer — Explore the Infrared Sky Through Time

**Summary**

Ze Deutsche built a free web tool that lets anyone explore real NASA SPHEREx infrared observations. Enter right ascension and declination or open one of six examples covering the five challenge targets. Play the sky through time, pan to nearby fields, compare dates, and inspect spectra with uncertainties and missing samples. Catalog overlays and position measurements help users distinguish known sources from changes worth investigating. Every image keeps its observation time and archive provenance. The viewer requests small cutouts as needed and keeps the examples playable during archive search outages. It gives students, educators and citizen scientists a way to investigate how the sky changes and evaluate potential moving sources in the spirit of the Planet X challenge.

**Project Details**

SPHEREx Sky Viewer turns a sky coordinate into a sequence of real infrared observations in a browser. Start with Barnard’s Star, Epsilon Indi B, WISE 0855, RW Aurigae or R Draconis. A sixth example preserves the separate WISE 0855 field specified by NASA’s coordinate seed. Filter by date, detector or wavelength, then play, pause, step or scrub. The timeline groups observations by UTC date, week, month or published survey pass and preserves actual observation dates and gaps.

The viewer behaves like a sky map. Drag to explore nearby cutouts, scroll or pinch to zoom, or use the keyboard. The current view center appears separately from the entered target, which is one click away. Automatic panning reuses known exposures and requests selected images after movement stops. “Search archive here” looks for other exposures on request. Shared links preserve the field and selected observations. The layout works on phones, and a pixel key distinguishes faint measured sky from masked or missing pixels.

Put two dates side by side, blink between them, or display a sum or a signed difference heatmap. Mark the same feature in both images to measure its angular shift. Candidate detection and association can highlight changes, suggest catalog matches, rank eligible candidates and estimate a short future path with uncertainty when the data support it. Gaia DR3 and AllWISE overlays add context, with explanations available by hover, focus or touch. Gaia positions account for catalog proper motion, while AllWISE retains its historical coordinates. Downloadable results retain the measurements and their provenance.

Pick a point, source candidate or field center to plot infrared brightness against wavelength. The spectrum shows error bars, dates, measured samples and gaps. An extended extraction can retrieve additional calibration, and the DR1 all-sky cube gives spectral context across 102 nominal channels. The app also supports a matched-wavelength light curve and attempts within-visit coadds when the exposures are compatible.

We built the browser interface with TypeScript, Vite and Canvas, and the API with Python and FastAPI. Astropy handles FITS files and sky coordinates. NumPy, SciPy and Pillow support alignment, photometry and rendering. Our Linux server serves the app over HTTPS through Uvicorn and Caddy. We use small, on-demand cutouts, request limits and a cache that evicts older derived products to keep the service practical on one server. Bundled examples and a static fallback support exploration when archive discovery is unavailable. The original project software is MIT licensed.

The goal is to make the Planet X challenge approachable through repeatable observation and comparison. We show wavelength, masks, coverage, registration quality and original product IDs so users can judge whether an apparent change merits follow-up. One measured spectrum agreed with IRSA’s reference within our stated tolerance. Controlled tests verified candidate recognition and a held-out motion forecast. Real-field candidate ranking and forecasting, and a successful real within-visit coadd, still need validation.

**NASA Data**

| Link Text | Link URL |
| --- | --- |
| NASA SPHEREx mission | https://science.nasa.gov/mission/spherex/ |
| NASA/IPAC IRSA SPHEREx archive | https://irsa.ipac.caltech.edu/Missions/spherex.html |
| SPHEREx DR1 Level 2 spectral images | https://doi.org/10.26131/IRSA678 |
| SPHEREx QR3 Level 2 spectral images | https://doi.org/10.26131/IRSA662 |
| SPHEREx DR1 all-sky spectral cube | https://doi.org/10.26131/IRSA679 |
| NASA/IPAC IRSA SPHEREx data access and calibration products | https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/ |
| NASA/IPAC IRSA SPHEREx cutout tutorial | https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/ |
| NASA/IPAC IRSA SPHEREx spectrophotometry reference | https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html |
| NASA/IPAC IRSA AllWISE Source Catalog | https://doi.org/10.26131/IRSA1 |
| NASA Space Apps Planet X and SPHEREx challenge and target coordinates | https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/ |

SPHEREx is a joint project of the Jet Propulsion Laboratory and Caltech, funded by NASA. We used calibrated DR1 and QR3 spectral images and detector calibration products for the time viewer and analysis, the DR1 cube for spectral context, and AllWISE for catalog markers. Each displayed observation retains its product ID, release, UTC timestamp and source link.

**Space Agency Partner & Other Data**

| Link Text | Link URL |
| --- | --- |
| ESA Gaia Data Release 3 | https://www.cosmos.esa.int/web/gaia/dr3 |
| German Astrophysical Virtual Observatory Gaia DR3 Lite | https://dc.g-vo.org/tableinfo/gaia.dr3lite |
| IVOA Simple Image Access 2.0 standard | https://www.ivoa.net/documents/SIA/20151223/ |
| Python | https://www.python.org/ |
| Astropy | https://www.astropy.org/ |
| NumPy | https://numpy.org/ |
| SciPy | https://scipy.org/ |
| Pillow | https://python-pillow.org/ |
| Astropy HEALPix | https://astropy-healpix.readthedocs.io/ |
| Requests | https://requests.readthedocs.io/ |
| FastAPI | https://fastapi.tiangolo.com/ |
| Pydantic | https://docs.pydantic.dev/ |
| Uvicorn | https://www.uvicorn.org/ |
| Node.js | https://nodejs.org/ |
| TypeScript | https://www.typescriptlang.org/ |
| Vite | https://vite.dev/ |
| HTML Canvas API | https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API |
| Playwright and Chromium browser testing | https://playwright.dev/ |
| pytest | https://docs.pytest.org/ |
| GitHub Actions | https://docs.github.com/en/actions |
| Caddy | https://caddyserver.com/ |
| systemd | https://systemd.io/ |
| Inter typeface via Google Fonts | https://fonts.google.com/specimen/Inter |
| IBM Plex Mono typeface via Google Fonts | https://fonts.google.com/specimen/IBM+Plex+Mono |
| OpenAI Codex | https://openai.com/codex/ |

**Additional form fields**

| Field | Value |
| --- | --- |
| Link to Final Project | https://spherex.144.91.89.214.sslip.io/ |
| Link to Project Demo | https://spherex.144.91.89.214.sslip.io/assets/spherex-demo-2026.mp4 |
| Team | https://www.spaceappschallenge.org/2026/find-a-team/ze-deutsche/?tab=members |

The 28.33-second demo opens with Ze Deutsche, presents the Planet X and SPHEREx challenge, and shows real Barnard’s Star observations in the current viewer. It has English captions and plays without an account. [WebM copy](https://spherex.144.91.89.214.sslip.io/assets/spherex-demo.webm)

**Use of Super Intelligence**

Codex assisted with planning, coding, debugging, verification, interface design, documentation and demo preparation. The viewer and demo use real NASA/IPAC IRSA observations. The aligned images, masks and comparisons are derived from those observations. We label synthetic test fixtures separately from archive data.

**Team handoff**

The source repository is [mt-evvi/Nsac](https://github.com/mt-evvi/Nsac). Check that it opens while signed out before listing it as a public source link. Review the [target test matrix](TARGET_TEST_MATRIX.md), [science and release verification](VERIFICATION.md), [data and license notes](DEPENDENCIES.md), and [official submission guide](https://www.spaceappschallenge.org/resources/project-submission-guide/).
