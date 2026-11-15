"""Index bounded IRSA SIA2 metadata into deterministic timeline manifests."""

import io
import math
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io.votable import parse
from astropy.time import Time
from astropy.wcs import WCS
from scipy.ndimage import map_coordinates

from . import imaging
from .config import MIB
from .contracts import Problem, max_range_end
from .store import content_key
from .upstream import IRSA, TransferBudget, UpstreamError, check_url, fetch

PIPELINE_VERSION = "irsa-tan-v2"
COMPATIBLE_INDEX_VERSIONS = ("irsa-tan-v1",)
COLLECTIONS = (("spherex_dr1", "DR1", "10.26131/IRSA678"), ("spherex_qr3", "QR3", "10.26131/IRSA662"))
MISSION_START = date(2025, 4, 1)
ROW_LIMIT = 500
MAX_ROWS = 4000
DETECTOR_NAME = re.compile(r"SPHEREx-D([1-6])\Z", re.IGNORECASE)


class ArchiveError(Problem):
    pass


def query_dates(query):
    today = datetime.now(UTC).date()
    start, end = date.fromisoformat(query["start"]) if query.get("start") else None, date.fromisoformat(query["end"]) if query.get("end") else None
    if start is None:
        anchor = end or today
        try:
            start = anchor.replace(year=max(1, anchor.year - 2))
        except ValueError:
            start = anchor.replace(year=max(1, anchor.year - 2), day=28)
    if end is None:
        end = min(max_range_end(start), today)
    return max(start, MISSION_START), min(end, today)


def bounds(query):
    start, end = query_dates(query)
    return {**query, "start": start.isoformat(), "end": end.isoformat(), "frame": "ICRS"}, start, end


def region(query):
    radius = query["fovArcmin"] / 120 * math.sqrt(2) + imaging.PIXEL_ARCSEC / 3600
    return f'CIRCLE {query["raDeg"]:.7f} {query["decDeg"]:.7f} {radius:.8f}'


def time_mjd(day):
    return Time(datetime.combine(day, datetime.min.time(), UTC), scale="utc").mjd


def columns(table):
    return {name.lower(): name for name in table.colnames}


def parse_votable(payload):
    try:
        votable = parse(io.BytesIO(payload))
        statuses = [str(item.value).upper() for resource in votable.resources for item in resource.infos
                    if str(item.name).upper() == "QUERY_STATUS"]
        if "ERROR" in statuses:
            raise ValueError("VOTable QUERY_STATUS ERROR")
        table = votable.get_first_table().to_table(use_names_over_ids=True)
        if not {"access_url", "obs_id", "t_min"} <= set(columns(table)):
            raise ValueError("missing required SIA columns")
        return table, "OVERFLOW" in statuses or len(table) >= ROW_LIMIT
    except (ValueError, KeyError, OSError, TypeError, IndexError, StopIteration) as exc:
        raise ArchiveError("UPSTREAM_UNAVAILABLE", "IRSA returned an unreadable archive index.", 503, True) from exc


def read_table(collection, query, start, end, budget, deadline):
    parameters = {"COLLECTION": collection, "POS": region(query), "MAXREC": ROW_LIMIT,
                  "TIME": f"{time_mjd(start):.8f} {time_mjd(end):.8f}"}
    if query.get("wavelengthUm"):
        parameters["BAND"] = f'{query["wavelengthUm"] * 1e-6:.9g}'
    url = f"https://{IRSA}/SIA?{urlencode(parameters)}"
    for attempt in range(2):
        try:
            raw = fetch(url, limit=4 * MIB, deadline=deadline, purpose="metadata", budget=budget)
            return parse_votable(raw)
        except Problem as exc:
            wait = max(random.uniform(0.1, 0.3), exc.retry_after or 0)
            if attempt or exc.code not in {"UPSTREAM_UNAVAILABLE", "ARCHIVE_TIMEOUT"} or time.monotonic() + wait + 1 > deadline:
                raise
            time.sleep(wait)


def detector_xy(s_region, query):
    if not s_region or not s_region.upper().startswith("POLYGON ICRS "):
        return None
    try:
        coord = np.array(s_region.split()[2:], dtype=float).reshape(-1, 2)[:4]
        if coord.shape != (4, 2) or not np.isfinite(coord).all():
            return None
        wcs = WCS(naxis=2)
        wcs.wcs.crval = [query["raDeg"], query["decDeg"]]
        wcs.wcs.crpix = [1, 1]
        wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        corners = np.array(wcs.world_to_pixel(SkyCoord(coord[:, 0], coord[:, 1], unit="deg"))).T
        reverse = np.array([corners[1] - corners[0], corners[3] - corners[0]])
        xy = np.linalg.solve(reverse.T, -corners[0])
        if np.isfinite(xy).all() and all(-0.1 <= value <= 1.1 for value in xy):
            return (xy * 2040 - 0.5).tolist()
    except (ValueError, TypeError, np.linalg.LinAlgError):
        return None
    return None


@lru_cache(maxsize=1)
def band_index():
    path = Path(__file__).with_name("data") / "passbands.npz"
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as source:
        return source["wavelength"], source["bandwidth"], str(source["calibration"])


def estimate_passband(detector, position):
    index = band_index()
    if index is None or not all(0 <= value <= 2039 for value in position):
        return None
    wavelength, bandwidth, version = index
    size = wavelength.shape[1]
    ix, iy = (value * (size - 1) / 2039 for value in position)
    estimate = [float(map_coordinates(values[detector - 1], [[iy], [ix]], order=1)[0])
                for values in (wavelength, bandwidth)]
    if not all(np.isfinite(value) and value > 0 for value in estimate):
        return None
    return *estimate, version


def index_table(table, query, release, doi):
    col = columns(table)
    for row in table:
        def value(key, default=None):
            if key not in col or np.ma.is_masked(row[col[key]]):
                return default
            return row[col[key]]

        detector_field = DETECTOR_NAME.fullmatch(str(value("energy_bandpassname", "")))
        if not detector_field or not value("obs_id") or value("t_min") is None:
            continue
        detector = int(detector_field[1])
        obs = str(value("obs_id"))
        address = str(value("access_url", ""))
        start_mjd = float(value("t_min"))
        end_mjd = float(value("t_max", start_mjd))
        if not 60000 <= start_mjd <= end_mjd <= 75000:
            continue
        try:
            test = imaging.cutout_url(query, {"archiveUrl": address})
            check_url(test, "cutout")
        except Problem:
            continue
        start, end = (stamp + "Z" for stamp in Time([start_mjd, end_mjd], format="mjd", scale="utc").isot)
        product = urlsplit(address).path.rsplit("/", 1)[1].removesuffix(".fits")
        footprint = value("s_region")
        xy = detector_xy(footprint, query)
        lo, hi = value("em_min"), value("em_max")
        entry = {"frameId": content_key(PIPELINE_VERSION, product, release, query["raDeg"], query["decDeg"], query["fovArcmin"]),
                 "productId": product, "obsId": obs, "release": release, "detector": detector, "startUtc": start,
                 "endUtc": end, "slotKey": start[:10], "archiveUrl": address, "archiveDoi": doi, "state": "candidate"}
        if lo is not None and hi is not None:
            entry["detectorWavelengthRangeUm"] = [float(lo) * 1e6, float(hi) * 1e6]
        if xy is not None:
            entry["estimatedDetectorXY"] = xy
            distance = min(xy[0], xy[1], 2039 - xy[0], 2039 - xy[1])
            entry["footprintMarginPx"] = round(float(distance), 2)
            estimated = estimate_passband(detector, xy)
            if estimated:
                entry["estimatedWavelengthUm"], entry["estimatedBandwidthUm"], entry["estimatedBandCalibration"] = estimated
        survey_target = value("target_name")
        if survey_target:
            entry["surveyTarget"] = str(survey_target)
        yield entry


def collection_index(collection, release, doi, query, start, end, budget, deadline):
    windows = [(start, end + timedelta(days=1))]
    indexed = []
    warnings = []
    complete = True
    successful = False
    rows = 0
    while windows:
        first, last = windows.pop(0)
        try:
            table, overflows = read_table(collection, query, first, last, budget, deadline)
        except Problem as exc:
            warnings.append(f"{release}: {exc.message}")
            complete = False
            break
        successful = True
        rows += len(table)
        if rows > MAX_ROWS:
            complete = False
            warnings.append(f"{release}: reached the maximum number of archive index rows.")
            break
        if overflows:
            span = (last - first).days
            if span > 1 and budget.attempts < budget.max_attempts - 2 and rows < MAX_ROWS - 2 * ROW_LIMIT:
                mid = first + timedelta(days=span // 2)
                windows[:0] = [(first, mid), (mid, last)]
            else:
                complete = False
                warnings.append(f"{release}: archive index is truncated. Narrow the UTC dates for more complete coverage.")
        indexed.extend(index_table(table, query, release, doi))
    return {"collection": collection, "release": release, "doi": doi, "complete": complete, "successful": successful,
            "warnings": list(dict.fromkeys(warnings)), "entries": indexed, "rows": rows}


def visit_groups(frames):
    last = None
    visit = None
    for entry in frames:
        timestamp = datetime.fromisoformat(entry["startUtc"].replace("Z", "+00:00"))
        if last is None or (timestamp - last).total_seconds() >= 86400:
            visit = content_key("visit", entry["obsId"], entry["startUtc"])
        entry["visitId"] = visit
        last = timestamp


def rank(frame, query):
    # Favor likely footprint before the FITS checks. The precise wavelength is set only on preparation.
    wave = query.get("wavelengthUm")
    estimated = frame.get("estimatedWavelengthUm")
    gap = abs(wave - estimated) if wave is not None and estimated is not None else 0
    margin = frame.get("footprintMarginPx", -30)
    min_margin = query["fovArcmin"] * 60 / imaging.PIXEL_ARCSEC * 0.72
    # Footprint corner estimates may be off by a few native pixels. Preserve near misses for the FITS check.
    band = frame.get("estimatedBandwidthUm", 0)
    match = wave is None or estimated is None or gap <= band / 2 + 0.006
    return not match, margin < min_margin, gap, frame["startUtc"], frame["productId"]


def make_manifest(query, indexed, *, collections=None, complete=True, warnings=()):
    unique = {}
    for entry in sorted(indexed, key=lambda entry: (entry["release"] != "QR3", entry["startUtc"], entry["productId"])):
        unique.setdefault((entry["obsId"], entry["detector"]), entry.copy())
    frames = sorted(unique.values(), key=lambda entry: (entry["startUtc"], entry["productId"]))
    visit_groups(frames)
    if query.get("detector") is not None:
        frames = [frame for frame in frames if frame["detector"] == query["detector"]]
    if query.get("wavelengthUm") is not None:
        wave = query["wavelengthUm"]
        frames = [frame for frame in frames if "estimatedWavelengthUm" not in frame
                  or abs(frame["estimatedWavelengthUm"] - wave) <= frame["estimatedBandwidthUm"] / 2 + 0.012]
    # Index the best candidate on every real date first, followed by same-day repeats. This preserves calendar breadth on the first page.
    dates = {}
    for frame in frames:
        dates.setdefault(frame["slotKey"], []).append(frame)
    ordered = [sorted(same_day, key=lambda frame: rank(frame, query)) for same_day in dates.values()]
    first = [items[0] for items in ordered]
    rest = [frame for same_day in ordered for frame in same_day[1:]]
    empty_status = "NO_COMPARABLE_FRAMES" if any(k in query for k in ("detector", "wavelengthUm")) else "NO_COVERAGE"
    return {"schemaVersion": 1, "pipelineVersion": PIPELINE_VERSION, "query": query, "grid": imaging.grid_for(query),
            "counts": {"products": len(frames), "pointings": len({f["obsId"] for f in frames}), "observationDates": len(dates),
                       "independentEpochs": len({f["visitId"] for f in frames}), "preparedFrames": 0},
            "searchStatus": "PARTIAL" if not complete else ("OK" if frames else empty_status), "complete": complete,
            "warnings": list(warnings), "collections": collections or [], "visitGrouping": "Consecutive pointings less than 24 hours apart",
            "frames": first + rest}


def discover(query):
    query, start, end = bounds(query)
    if start > end:
        return make_manifest(query, [], warnings=["The date range does not overlap published mission dates."])
    budget = TransferBudget(4 * MIB, 12)
    deadline = time.monotonic() + 20
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(collection_index, *item, query, start, end, budget, deadline) for item in COLLECTIONS]
        results = [future.result() for future in futures]
    warnings = [warning for result in results for warning in result["warnings"]]
    if not any(result["successful"] for result in results):
        raise ArchiveError("UPSTREAM_UNAVAILABLE", "IRSA could not index this field. Try again or open a bundled example.", 503, True, 10)
    entries = [entry for result in results for entry in result.pop("entries")
               if start.isoformat() <= entry["slotKey"] <= end.isoformat()]
    complete = all(result["complete"] for result in results)
    if len(entries) > MAX_ROWS:
        entries = sorted(entries, key=lambda entry: (entry["startUtc"], entry["productId"]))[:MAX_ROWS]
        warnings.append("The combined archive index reached the row limit. Narrow the UTC date range.")
        complete = False
    return make_manifest(query, entries, collections=results, complete=complete, warnings=warnings)
