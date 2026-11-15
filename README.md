# Planet X and SPHEREx

Enter an ICRS sky position or choose an example to explore time-ordered infrared images from NASA's SPHEREx mission. The viewer aligns observations on a fixed north-up grid and preserves the UTC timestamps, detector, wavelength, mask and archive provenance of each frame.

[Open the SPHEREx viewer](https://spherex.144.91.89.214.sslip.io/) · [NASA Space Apps challenge](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/)

## Run locally

With Python 3.12 and Node 24, install the locked dependencies and build the frontend from the repository root.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm --prefix web ci
npm --prefix web run build
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 4173
```

Open `http://127.0.0.1:4173/`. Use `SPHEREX_CACHE` to select a writable cache directory. The public deployment uses one Uvicorn process under systemd behind Caddy.

## Verify

```sh
.venv/bin/python -m pytest -q
npm --prefix web run check
npm --prefix web run build
.venv/bin/python -m tools.verify_real_slice --output /tmp/spherex-real-slice
```

The real-data verification command requires IRSA access and records both source observation IDs, times, calibrated wavelengths, masks and comparison-quality measurements. [Verification evidence](docs/VERIFICATION.md) · [Build and release gates](BUILD_PLAN.md) · [Server rollout](deploy/README.md)

## Static contingency

```sh
SPHEREX_STATIC_BASE=/Nsac/ npm --prefix web run build:static
```

Publish the generated `web/dist-static` directory at `/Nsac/` for project-root hosting such as GitHub Pages. Omit the environment variable for a standalone hostname. The static copy supports bundled playback, share links, blink and side-by-side. Live discovery and analyses use the FastAPI deployment. [Original starting README](docs/STARTING_README.md)

## Data acknowledgement

This project makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration. [IRSA mission archive](https://irsa.ipac.caltech.edu/Missions/spherex.html) · [DR1 DOI](https://doi.org/10.26131/IRSA678) · [QR3 DOI](https://doi.org/10.26131/IRSA662)

Codex assisted with planning, implementation, testing and documentation. Observation images come from the archive. Derived masks, aligned rasters and comparison products are reproducible from the source identifiers recorded in the viewer and example manifests.
