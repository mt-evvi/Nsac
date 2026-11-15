# Data and software provenance

The display images, masks and analysis arrays are generated from official SPHEREx archived exposures. Each example manifest stores the original product ID, UTC observation time, field, calibration release, DOI and direct provenance URL. The reduced wavelength index is derived from the public `cal-swcs-v5-2026-191` detector maps by `tools/build_passbands.py`. The coadded context API reads the official DR1 HiPS cube tile and reports its source URL and DOI. [Target matrix](TARGET_TEST_MATRIX.md) · [DR1 spectral images](https://doi.org/10.26131/IRSA678) · [DR1 all-sky cube](https://doi.org/10.26131/IRSA679) · [QR3 spectral images](https://doi.org/10.26131/IRSA662) · [IRSA cloud data](https://irsa.ipac.caltech.edu/cloud_access/)

Catalog overlays use Gaia DR3 positions from Heidelberg's Gaia DR3 Lite mirror or the ESA archive, and AllWISE positions from IRSA. Gaia positions use the catalog's reference epoch and proper motion, with parallax omitted from the displayed linear model. AllWISE positions retain their historical catalog coordinates. [Heidelberg Gaia DR3 Lite](https://dc.g-vo.org/tableinfo/gaia.dr3lite) · [Gaia data model](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html) · [AllWISE astrometry](https://irsa.ipac.caltech.edu/data/WISE/docs/release/AllWISE/expsup/sec5_3bii.html)

The browser and Python lockfiles enumerate the shipped source dependencies and versions. The release contains project code, built browser files and derived examples. The Python environment is installed from pinned upstream wheels. The wheels retain their bundled license notices, including those for compiled libraries.

| Packages | License from the installed distribution |
| --- | --- |
| FastAPI, Pydantic, pytest, Vite | MIT |
| Uvicorn, Starlette, Astropy, astropy-healpix, PyVO, astroquery, reproject | BSD family |
| SciPy | BSD-3-Clause project license with third-party notices in the wheel |
| NumPy | BSD-3-Clause and bundled 0BSD, MIT, Zlib and CC0-1.0 notices |
| Pillow | MIT-CMU |
| Requests, TypeScript, Playwright | Apache-2.0 |

The demo captures the app and its real archive images. It includes English subtitles and labels Codex assistance. The project README records the mission acknowledgement. [Verification record](VERIFICATION.md)
