"""Adjacent-field browsing reuses identities without inventing prepared coverage."""

import copy
import json
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from server import archive, imaging, upstream
from server.app import Service, create_app
from server.config import ROOT, Settings
from server.contracts import Problem, RecenterQuery


@pytest.fixture
def browsing(tmp_path, monkeypatch):
    settings = Settings(cache=tmp_path, web=ROOT / "web" / "dist", disk_reserve=0,
                        client_burst=1, client_rate=1)
    app = create_app(settings)
    service = app.state.service = Service(settings)
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, "path", "") == "/api/v1/series/{series_id}/recenter")
    source = copy.deepcopy(service.store.preset("preset-barnard"))
    source["data"]["seriesId"] = "source"
    service.store.put("series", "source", source)
    request = Request({"type": "http", "app": app, "client": ("127.0.0.1", 1234),
                       "headers": [], "scheme": "http", "server": ("test", 80), "path": "/"})

    def forbidden(*_args, **_options):
        pytest.fail("Recentering made an upstream request")

    monkeypatch.setattr(archive, "discover", forbidden)
    monkeypatch.setattr(upstream.requests, "get", forbidden)
    # Cached metadata remains usable even while fresh transfers are refused.
    monkeypatch.setattr(upstream, "CIRCUITS", {"discovery": upstream.Circuit(until=time.monotonic() + 60),
                                             "images": upstream.Circuit(until=time.monotonic() + 60)})
    fixture = SimpleNamespace(service=service, endpoint=endpoint, source=source, request=request)
    try:
        yield fixture
    finally:
        service.jobs.close()


def recenter(fixture, position, source_id="source"):
    response = fixture.endpoint(source_id, RecenterQuery.model_validate(position), fixture.request)
    if isinstance(response, dict):
        return response, 200
    assert response.status_code == 202
    pending = json.loads(response.body)
    deadline = time.monotonic() + 2
    while True:
        result = fixture.service.jobs.read(pending["jobId"])
        if result["status"] not in {"queued", "running"}:
            assert result["status"] == "partial", result
            return result, 202
        assert time.monotonic() < deadline
        time.sleep(.005)


def test_recenter_reuses_identity_but_reprepares_pixels_and_bandpass(browsing):
    source = copy.deepcopy(browsing.source)
    center = {"raDeg": 269.47, "decDeg": 4.775}
    envelope, status = recenter(browsing, center)
    result = envelope["data"]
    assert status == 202 and envelope["status"] == "partial"
    assert result["query"] == {**source["data"]["query"], **center}
    assert result["grid"]["crval"] == [269.47, 4.775]
    assert result["searchStatus"] == "PARTIAL" and result["complete"] is False
    assert "Other exposures may exist" in envelope["warnings"][0]
    assert "archive search has not been repeated" in envelope["warnings"][0]
    before = {frame["productId"]: frame for frame in source["data"]["frames"]}
    assert len(result["frames"]) == len(before)
    for frame in result["frames"]:
        original = before[frame["productId"]]
        assert frame["frameId"] != original["frameId"]
        assert frame["archiveUrl"] == original["archiveUrl"]
        assert frame["startUtc"] == original["startUtc"]
        assert frame["detector"] == original["detector"]
        assert frame["state"] == "candidate"
        assert not ({"imageUrl", "maskUrl", "wavelengthUm", "bandwidthUm", "stretch", "coverageFraction",
                     "validFraction", "estimatedDetectorXY", "footprintMarginPx", "estimatedWavelengthUm",
                     "estimatedBandwidthUm", "wavelengthCalibrationId", "psfFwhmArcsec"} & frame.keys())
    assert browsing.service.store.get("series", "source")[0] == source
    assert not list(browsing.service.store.assets.iterdir())

    # Returning to an identical nearby field is immediate and consumes no new job allowance.
    cached, status = recenter(browsing, center)
    assert status == 200 and cached == envelope
    with pytest.raises(Problem) as rejected:
        recenter(browsing, {"raDeg": 269.48, "decDeg": 4.775})
    assert rejected.value.code == "RATE_LIMIT" and rejected.value.retry_after


@pytest.mark.parametrize(("before", "after"), [
    ({"raDeg": 359.99, "decDeg": 0.0}, {"raDeg": .01, "decDeg": 0.0}),
    ({"raDeg": 120.0, "decDeg": 89.99}, {"raDeg": 300.0, "decDeg": 89.99}),
    ({"raDeg": 120.0, "decDeg": -89.99}, {"raDeg": 300.0, "decDeg": -89.99}),
])
def test_recenter_distance_is_spherical_at_wrap_and_poles(browsing, before, after):
    source = copy.deepcopy(browsing.source)
    source["data"]["query"].update(before)
    source["data"]["grid"] = imaging.grid_for(source["data"]["query"])
    browsing.service.store.put("series", "source", source)
    envelope, _ = recenter(browsing, after)
    assert envelope["data"]["grid"]["crval"] == [after["raDeg"], after["decDeg"]]


def test_recenter_rejects_large_jumps_and_expired_sources(browsing):
    with pytest.raises(Problem) as rejected:
        recenter(browsing, {"raDeg": 280.0, "decDeg": 4.768})
    assert rejected.value.code == "RECENTER_LIMIT"
    with pytest.raises(Problem) as rejected:
        recenter(browsing, {"raDeg": 269.46, "decDeg": 4.768}, "not-indexed")
    assert rejected.value.code == "SERIES_EXPIRED"
    with browsing.service.store.connect() as conn:
        conn.execute("UPDATE records SET created = ? WHERE kind = 'series' AND key = 'source'",
                     (time.time() - 25 * 3600,))
    with pytest.raises(Problem) as rejected:
        recenter(browsing, {"raDeg": 269.46, "decDeg": 4.768})
    assert rejected.value.code == "SERIES_EXPIRED"


@pytest.mark.parametrize("position", [
    {"raDeg": 360, "decDeg": 0}, {"raDeg": 0, "decDeg": 91},
    {"raDeg": True, "decDeg": 0}, {"raDeg": "12", "decDeg": 0},
    {"raDeg": 12, "decDeg": 0, "archiveUrl": "https://example.org"},
    {"raDeg": 12, "decDeg": 0, "fovArcmin": 8},
])
def test_recenter_accepts_only_valid_position(position):
    with pytest.raises(ValidationError):
        RecenterQuery.model_validate(position)
