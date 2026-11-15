"""Catalog tests use bounded local tables and never contact remote services."""

from io import BytesIO
import json
import time
from types import SimpleNamespace

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io.votable import from_table, writeto
from astropy.table import Table
import pytest

from server import analysis_api, catalogs
from server.app import Service
from server.catalogs import _parse, _query, nearby_matches, project_catalog
from server.config import Settings
from server.contracts import DetectionQuery, Problem
from server.imaging import grid_for, wcs_for


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


def test_candidate_matches_are_epoch_specific_and_report_competing_sources():
    grid = grid_for({"raDeg": 359.999, "decDeg": 60, "fovArcmin": 3})
    dates = {"first": {"startUtc": "2025-01-01T00:00:00Z"}, "next": {"startUtc": "2026-01-01T00:00:00Z"}}
    start = SkyCoord(359.9998, 60, unit="deg")
    tracked = [start.directional_offset_by(90 * u.deg, offset * u.arcsec) for offset in (10.8, 12)]
    x, y = wcs_for(grid).world_to_pixel(SkyCoord(tracked))
    marks = [{"frameId": frame, "pixel": {"x": float(px), "y": float(py)}} for frame, px, py in zip(dates, x, y)]
    gaia = _parse(_votable(Table({
        "source_id": [123, 456], "ra": [start.ra.deg, tracked[0].ra.deg], "dec": [start.dec.deg, tracked[0].dec.deg],
        "ref_epoch": [2016.0, 2016.0], "pmra": [1200.0, 0.0], "pmdec": [0.0, 0.0],
    })), "gaia_dr3", 0.07)
    wise = _parse(_votable(Table({
        "source_id": ["wise-old"], "ra": [start.ra.deg], "dec": [start.dec.deg],
    })), "allwise", 0.05)
    result = nearby_matches([{"candidateId": "candidate", "marks": marks}], [gaia, wise], dates, grid)["candidate"]
    assert result[0]["ambiguous"] and not result[0]["truncated"]
    assert {match["catalogId"] for match in result[0]["matches"]} == {"123", "456"}
    moving = next(match for match in result[0]["matches"] if match["catalogId"] == "123")
    assert moving["separationArcsec"] < 0.01 and moving["matchedVisits"] == 2
    assert moving["properMotionApplied"] and moving["referenceEpoch"] == 2016.0
    assert moving["comparisonEpoch"] == moving["observationUtc"]
    assert result[1]["matches"] == [] and not result[1]["ambiguous"]


def test_cached_detection_adds_catalog_after_explicit_overlay_load(tmp_path, monkeypatch):
    grid = grid_for({"raDeg": 0, "decDeg": 0, "fovArcmin": 3})
    dates = {"frame1": {"startUtc": "2025-01-01T00:00:00Z"}, "frame2": {"startUtc": "2026-01-01T00:00:00Z"}}
    middle = (grid["width"] - 1) / 2
    marks = [{"frameId": frame, "pixel": {"x": middle, "y": middle}} for frame in dates]
    detections = {"candidates": [{"candidateId": "candidate", "marks": marks}]}
    calls = []

    def detect(method, *_args, **_kwargs):
        calls.append(method)
        return detections

    def fetch(*_args, **_kwargs):
        pytest.fail("Detection issued a catalog request")

    service = Service(Settings(cache=tmp_path, disk_reserve=0))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(service=service)), client=None, cookies={},
                              url=SimpleNamespace(scheme="http"))
    monkeypatch.setattr(service, "manifest", lambda _: {"data": {"grid": grid}})
    monkeypatch.setattr(service, "frame", lambda _series, frame: (None, dates[frame]))
    monkeypatch.setattr(catalogs, "fetch", fetch)
    monkeypatch.setattr(analysis_api, "dataset", lambda *_: {})
    monkeypatch.setattr(analysis_api, "run_science", detect)
    query = DetectionQuery(frameIds=list(dates))
    try:
        job = analysis_api.detections("test-series", query, request)
        job_id = json.loads(job.body)["jobId"]
        deadline = time.monotonic() + 2
        while (initial := service.jobs.read(job_id))["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.01)
        assert initial["status"] == "succeeded" and "catalogMatches" not in initial["data"]["candidates"][0]

        wise = _parse(_votable(Table({"source_id": ["wise-centered"], "ra": [0.0], "dec": [0.0]})), "allwise", 0.05)
        service.store.put("catalog", analysis_api.catalog_cache_key(grid, "allwise"), wise)
        enriched = analysis_api.detections("test-series", query, request)
        match = enriched["data"]["candidates"][0]["catalogMatches"][0]["matches"][0]
        assert match["catalogId"] == "wise-centered" and match["matchedVisits"] == 2
        assert "2010–2011" in match["comparisonEpoch"]
        assert calls == ["detect"]
    finally:
        service.jobs.close()

