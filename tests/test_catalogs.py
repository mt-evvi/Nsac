"""Catalog tests use bounded local tables and never contact remote services."""

from io import BytesIO

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io.votable import from_table, writeto
from astropy.table import Table
import pytest

from server.catalogs import _parse, _query, project_catalog
from server.contracts import Problem
from server.imaging import grid_for


def _votable(table):
    output = BytesIO()
    writeto(from_table(table), output)
    return output.getvalue()


def test_gaia_tangent_motion_and_stable_id_across_ra_wrap():
    grid = grid_for({"raDeg": 359.999, "decDeg": 60, "fovArcmin": 3})
    identifier = 4472832130942575872
    payload = _votable(Table({
        "source_id": [identifier, 2], "ra": [359.9998, 0.5], "dec": [60.0, 60.0],
        "ref_epoch": [2016.0, 2016.0], "pmra": [1200.0, 0.0], "pmdec": [0.0, 0.0],
    }))
    rows = _parse(payload, "gaia_dr3", 0.07)
    original = project_catalog(rows, grid)
    later = project_catalog(rows, grid, {"startUtc": "2026-01-01T00:00:00Z"})
    assert len(later["referenceRows"]) == 2
    assert [m["catalogId"] for m in original["markers"]] == [str(identifier)]
    first, after = original["markers"][0], later["markers"][0]
    assert first["raDeg"] > 359.99 and after["raDeg"] < 0.01
    p0 = SkyCoord(first["raDeg"], first["decDeg"], unit=u.deg)
    p1 = SkyCoord(after["raDeg"], after["decDeg"], unit=u.deg)
    assert p0.separation(p1).arcsec == pytest.approx(12, abs=0.02)
    assert after["x"] < first["x"]
    assert after["properMotionApplied"]


def test_allwise_positions_remain_at_historical_observation_epochs():
    grid = grid_for({"raDeg": 269.45, "decDeg": 4.768, "fovArcmin": 3})
    payload = _votable(Table({
        "source_id": ["wise-unique"], "designation": ["J175748.00+044605.0"], "ra": [269.45], "dec": [4.768],
        "w1mjdmin": [55315.0], "w1mjdmean": [55355.0], "w1mjdmax": [55395.0],
        "w2mjdmin": [55316.0], "w2mjdmean": [55356.0], "w2mjdmax": [55415.0],
    }))
    rows = _parse(payload, "allwise", 0.04)
    a = project_catalog(rows, grid, {"startUtc": "2025-08-15T00:00:00Z"})
    b = project_catalog(rows, grid, {"startUtc": "2026-08-15T00:00:00Z"})
    assert a == b
    assert a["markers"][0]["observationRangeMjd"] == [55315.0, 55415.0]
    assert a["markers"][0]["meanObservationMjd"] == 55355.5
    assert "2010–2011" in a["displayEpoch"]


def test_catalog_overflow_empty_and_malformed_responses_are_distinct():
    grid = grid_for({"raDeg": 12.0, "decDeg": -30.0, "fovArcmin": 8})
    gaia_url, gaia_radius = _query("gaia_dr3", grid)
    wise_url, wise_radius = _query("allwise", grid)
    assert "TOP+201" in gaia_url and "outrows=201" in wise_url
    assert 0 < wise_radius < gaia_radius < 0.13
    dense = Table({"source_id": range(205), "ra": [12.0] * 205, "dec": [-30.0] * 205})
    rows = _parse(_votable(dense), "gaia_dr3", gaia_radius)
    assert rows["truncated"] and len(rows["rows"]) == 200
    empty = _parse(_votable(dense[:0]), "gaia_dr3", gaia_radius)
    assert not empty["truncated"] and project_catalog(empty, grid)["markers"] == []
    with pytest.raises(Problem) as bad:
        _parse(b"<VOTABLE broken", "allwise", wise_radius)
    assert bad.value.code == "CATALOG_UNAVAILABLE"

