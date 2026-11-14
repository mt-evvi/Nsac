# How many dates are there?

There is no fixed number of dates per sky position. In a live IRSA check on November 14, 2026, the five official challenge fields had **27 to 78 distinct UTC observation dates** in the currently published wide survey collections. Each date can contain several pointings, and each pointing can have products from multiple detectors. These are archive coverage counts before wavelength, common footprint, and quality filtering. The number of frames that warrant comparison is smaller and must be measured in the processing pipeline.

SPHEREx scans the sky repeatedly. DR1 contains the first two surveys. QR3 provides published observations from surveys 3 and 4 to date. The broad survey cadence is not the interval between every observation. A field can have several measurements in a short span and then a gap of months. The coadded DR1 all-sky cube provides spectral context and has no observation time axis for playback. [IRSA releases](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/) · [IRSA access and collections](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/) · [DR1 products](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html)

## Live metadata snapshot

Each IRSA SIA2 search used a 0.005° radius (18″) around the center. This is a footprint intersection search and is independent of the viewer’s requested cutout width. D6 dates show how much a restriction to one detector can reduce the list. A shared detector still does not imply that two exposures used the same wavelength at the target.

| Field | Search center, ICRS RA/Dec (°) | DR1 + QR3 dates | Distinct pointings | Detector products | Date range, UTC | Longest gap | D6 dates |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| Barnard’s Star, approximate modern field | 269.45, +4.768 | 26 + 13 = **39** | 184 | 362 | 2025-08-15 to 2026-09-22 | 161 days | 20 |
| Epsilon Indi B, approximate modern field | 331.09656943, −56.80083957 | 50 + 10 = **60** | 241 | 463 | 2025-04-24 to 2026-10-02 | 157 days | 24 |
| WISE 0855, approximate modern field | 133.75977, −7.24218 | 27 + 0 = **27** | 129 | 258 | 2025-05-05 to 2026-05-14 | 178 days | 13 |
| WISE 0855, literal NASA input | 133.79512917, −7.24514722 | 27 + 0 = **27** | 129 | 258 | 2025-05-05 to 2026-05-14 | 178 days | 13 |
| RW Aurigae | 76.95654167, +30.40144444 | 25 + 10 = **35** | 168 | 336 | 2025-09-01 to 2026-09-16 | 174 days | 14 |
| R Draconis | 248.16761, +66.75498 | 60 + 18 = **78** | 278 | 545 | 2025-05-16 to 2026-07-16 | 99 days | 27 |

Both WISE 0855 searches returned the same counts. The literal NASA position and modern field center are about 2 arcminutes apart because of the object’s large proper motion. Matching archive counts give no assurance that a small cutout centered on the literal input includes the target. Check the expected position at the imaging epoch when selecting a preset center. The centers above are for reproducing a metadata probe. They are not fitted source positions. [NASA challenge coordinates](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/?tab=details) · [WISE 0855 catalog astrometry](https://simbad.harvard.edu/simbad/sim-id?Ident=WISE+J085510.83-071442.5+) · [Epsilon Indi B astrometry](https://www.aanda.org/articles/aa/pdf/2004/03/aa0292.pdf)

## Reproduce the count

1. Query each center against `spherex_dr1` and `spherex_qr3` separately. For example, run the request below for the DR1 part of the Barnard field. Use the VOTable metadata response. No FITS downloads are needed.

   ```bash
   curl --fail --silent --show-error --max-time 30 --max-filesize 8388608 \
     --get 'https://irsa.ipac.caltech.edu/SIA' \
     --data-urlencode 'COLLECTION=spherex_dr1' \
     --data-urlencode 'POS=CIRCLE 269.45 4.768 0.005' \
     --data-urlencode 'MAXREC=2000' \
     -o /tmp/spherex-barnard-dr1.xml
   ```

2. Check that the response is a successful VOTable and that no `QUERY_STATUS=OVERFLOW` is present. With Astropy use `parse(...).get_first_table().to_table(use_names_over_ids=True)`. Count rows as detector products, deduplicate `obs_id` for pointings, and convert the `t_min` Modified Julian Date from UTC before counting distinct `YYYY-MM-DD` values. Union the dates and pointing IDs across the two collections before counting them. The longest gap is the largest difference between consecutive UTC dates in the union.
3. This snapshot used row caps of 900–2,000 per response and an 8 MiB metadata cap. All counted replies reported `QUERY_STATUS=OK` and did not reach their row cap. Zero QR3 rows for the two WISE positions were successful empty results. Some initial requests returned HTTP 502 and succeeded on a bounded retry. If a release still fails, keep the other release’s findings with an explicit incomplete index status. An overflow count is a lower bound and should trigger a narrower time window or follow-up search. Deep survey collections were excluded from this snapshot.

## Timeline implications

- Build the timeline from the lightweight index of observed dates. Show the actual selected UTC timestamp, the active wavelength, and separate totals for indexed archive dates and usable or prepared frames. Load the earliest eligible frame first. Offer a distinct empty state if the chosen filters remove every eligible observation.
- Use actual elapsed time for the calendar scale and mark dates that have candidate observations. Support previous and next observed date as the default. Day, week, and month can control timeline grouping or jump size. Where a calendar step lands in a gap, show the gap and let the visitor choose an available observation instead of implying a new image was recorded.
- Fetch only the selected image on slider release or after a short debounce. Viewer requests for stale slider positions must not win over the current selection. Prefetch at most neighboring eligible dates within the same wavelength group. Per date, show one chosen frame by default with an explicit way to browse same-day exposures. Any coadd must use compatible wavelengths and label the time range and contributing observations.
- A raw date can become ineligible after checking the wavelength WCS at the target, masked pixels, overlap, or alignment. Show those reasons in the index. Directory listing dates and release dates do not belong on the observation slider. [IRSA spectral image products](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-products/)
