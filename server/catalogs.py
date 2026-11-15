"""Bounded field catalogs and epoch-specific ICRS marker projection."""

from io import BytesIO
from math import hypot, isfinite
from time import monotonic, sleep
from urllib.parse import urlencode
from xml.parsers.expat import ExpatError

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io.votable import parse
from astropy.time import Time
import numpy as np

from .analysis import frame_time
from .config import MIB
from .contracts import Problem
from .imaging import wcs_for
from .upstream import GAIA, IRSA, TransferBudget, UpstreamError, fetch

ROW_LIMIT = 200
GAIA_HALO_DEG = 2 / 60
GAIA_URL = "https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html"
WISE_URL = "https://irsa.ipac.caltech.edu/data/WISE/docs/release/AllWISE/expsup/sec2_1a.html"


def _query(catalog, grid):
    gaia = catalog == "gaia_dr3"
    fields = "source_id,ra,dec,ref_epoch,pmra,pmdec,parallax,ruwe,astrometric_params_solved" if gaia else (
        "source_id,designation,ra,dec,w1mjdmin,w1mjdmax,w1mjdmean,w2mjdmin,w2mjdmax,w2mjdmean"
    )
    ra, dec = grid["crval"]
    wcs = wcs_for(grid)
    edge = wcs.pixel_to_world([-0.5, grid["width"] - 0.5], [-0.5, grid["height"] - 0.5])
    center = SkyCoord(ra, dec, unit="deg", frame="icrs")
    radius = float(max(edge.separation(center).deg)) + (GAIA_HALO_DEG if gaia else 0)
    if not gaia:
        parameters = {
            "catalog": "allwise_p3as_psd", "spatial": "cone", "objstr": f"{ra:.8f} {dec:+.8f}",
            "radius": f"{radius * 3600:.6f}", "radunits": "arcsec", "outfmt": 3,
            "selcols": fields, "outrows": ROW_LIMIT + 1,
        }
        return f"https://{IRSA}/cgi-bin/Gator/nph-query?" + urlencode(parameters), radius
    point = f"POINT('ICRS',{ra:.8f},{dec:.8f})"
    adql = (
        f"SELECT TOP {ROW_LIMIT + 1} {fields},DISTANCE(POINT('ICRS',ra,dec),{point}) AS separation FROM gaiadr3.gaia_source "
        f"WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.8f},{dec:.8f},{radius:.8f})) "
        "ORDER BY separation,source_id"
    )
    path = f"https://{GAIA}/tap-server/tap/sync"
    return path + "?" + urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "QUERY": adql, "FORMAT": "votable"}), radius


def _number(value):
    if np.ma.is_masked(value):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if isfinite(number) else None


def _text(value):
    if np.ma.is_masked(value):
        return ""
    return (value.decode() if isinstance(value, bytes) else str(value)).strip()


def _parse(payload, catalog, radius):
    gaia = catalog == "gaia_dr3"
    try:
        votable = parse(BytesIO(payload), verify="ignore")
        infos = list(votable.infos)
        for resource in votable.resources:
            infos.extend(resource.infos)
        states = {str(info.value).upper() for info in infos if info.name == "QUERY_STATUS"}
        if "ERROR" in states:
            raise ValueError("TAP failure")
        first = votable.get_first_table()
        states.update(str(info.value).upper() for info in first.infos if info.name == "QUERY_STATUS")
        table = first.to_table(use_names_over_ids=True)
    except (ValueError, TypeError, AttributeError, IndexError, OSError, ExpatError) as exc:
        raise Problem("CATALOG_UNAVAILABLE", "The catalog returned an invalid response.", 503, True) from exc
    names = {name.lower(): name for name in table.colnames}
    if not {"source_id", "ra", "dec"} <= names.keys():
        raise Problem("CATALOG_UNAVAILABLE", "The catalog response omitted required coordinates.", 503, True)
    rows = []
    for row in table[:ROW_LIMIT]:
        def number(name):
            return _number(row[names[name]]) if name in names else None

        ra, dec = number("ra"), number("dec")
        identifier = _text(row[names["source_id"]])
        if not identifier or ra is None or dec is None or not 0 <= ra < 360 or not -90 <= dec <= 90:
            continue
        item = {"catalogId": identifier, "referenceRaDeg": ra, "referenceDecDeg": dec}
        if gaia:
            item.update({
                "referenceEpoch": number("ref_epoch"), "pmRaMasYr": number("pmra"),
                "pmDecMasYr": number("pmdec"), "parallaxMas": number("parallax"),
                "ruwe": number("ruwe"), "astrometricParametersSolved": number("astrometric_params_solved"),
            })
        else:
            means = [v for name in ("w1mjdmean", "w2mjdmean") if (v := number(name)) is not None and v > 0]
            minimum = [v for name in ("w1mjdmin", "w2mjdmin") if (v := number(name)) is not None and v > 0]
            maximum = [v for name in ("w1mjdmax", "w2mjdmax") if (v := number(name)) is not None and v > 0]
            designation = _text(row[names["designation"]]) if "designation" in names else identifier
            item.update({
                "designation": designation, "referenceEpoch": "Historical AllWISE coadd",
                "meanObservationMjd": sum(means) / len(means) if means else None,
                "observationRangeMjd": [min(minimum), max(maximum)] if minimum and maximum else None,
            })
        rows.append(item)
    return {
        "catalog": catalog, "rows": rows, "coneRadiusDeg": radius, "rowLimit": ROW_LIMIT,
        "truncated": len(table) > ROW_LIMIT or "OVERFLOW" in states,
        "sourceUrl": GAIA_URL if gaia else WISE_URL,
    }


def fetch_catalog(catalog, grid, deadline):
    if catalog not in {"gaia_dr3", "allwise"}:
        raise Problem("UNKNOWN_CATALOG", "Choose Gaia DR3 or AllWISE.")
    deadline = min(deadline, monotonic() + 10)
    url, radius = _query(catalog, grid)
    budget = TransferBudget(MIB, 2)
    for attempt in range(2):
        try:
            payload = fetch(url, limit=MIB, deadline=deadline, purpose="catalog", budget=budget)
            return _parse(payload, catalog, radius)
        except UpstreamError as exc:
            delay = max(0.2, exc.retry_after or 0)
            if attempt or not exc.retryable or exc.code not in {"ARCHIVE_TIMEOUT", "UPSTREAM_UNAVAILABLE"} or (
                monotonic() + delay + 1 > deadline
            ):
                raise
            sleep(delay)


def project_catalog(rows, grid, frame_metadata=None):
    gaia = rows["catalog"] == "gaia_dr3"
    when = frame_time(frame_metadata) if gaia and frame_metadata else None
    epoch = Time(when).tcb.jyear if when else None
    wcs = wcs_for(grid)
    markers = []
    for row in rows["rows"]:
        point = SkyCoord(row["referenceRaDeg"], row["referenceDecDeg"], unit="deg", frame="icrs")
        reference_epoch = row["referenceEpoch"]
        pm_ra, pm_dec = row.get("pmRaMasYr"), row.get("pmDecMasYr")
        propagated = False
        if epoch is not None and reference_epoch is not None and pm_ra is not None and pm_dec is not None:
            years = float(epoch - reference_epoch)
            offset = hypot(pm_ra, pm_dec) * years
            angle = np.arctan2(pm_ra, pm_dec)
            point = point.directional_offset_by(angle * u.rad, offset * u.mas)
            propagated = True
        x, y = wcs.world_to_pixel(point)
        if -0.5 <= x < grid["width"] - 0.5 and -0.5 <= y < grid["height"] - 0.5:
            markers.append({
                **row, "x": float(x), "y": float(y), "raDeg": float(point.ra.deg),
                "decDeg": float(point.dec.deg), "properMotionApplied": propagated,
            })
    return {
        "catalog": rows["catalog"], "markers": markers, "referenceRows": rows["rows"],
        "truncated": rows["truncated"],
        "rowLimit": rows["rowLimit"], "coneRadiusDeg": rows["coneRadiusDeg"], "sourceUrl": rows["sourceUrl"],
        "displayEpoch": when.isoformat().replace("+00:00", "Z") if when else (
            "Gaia reference epoch (J2016.0)" if gaia else "Historical AllWISE observations (2010–2011)"
        ),
        "positionMethod": (
            "Gaia ICRS positions with linear proper motion when available; annual parallax omitted."
            if when else "Catalog barycentric ICRS positions at reference epoch."
        ) if gaia else "Stationary AllWISE catalog solution at the historical coadd. Bright-source astrometric biases may apply.",
    }

