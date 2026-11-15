import asyncio
import json
import logging
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from server.app import RequestBounds, Service, create_app
from server.config import MIB, ROOT, Settings
from server.contracts import Problem, SeriesQuery, ready
from server.jobs import Jobs
from server import release_index
from server.store import Store
from server.telemetry import ALERT_PERIODS, INTERVAL, RequestTraffic, Telemetry
from server import upstream
from server.upstream import TransferBudget, UpstreamError, check_url


@pytest.mark.parametrize("query", [
    {"raDeg": 360, "decDeg": 0}, {"raDeg": 0, "decDeg": -90.1},
    {"raDeg": 1, "decDeg": 0, "fovArcmin": 9}, {"raDeg": True, "decDeg": 0},
    {"raDeg": "11", "decDeg": 0}, {"raDeg": 1, "decDeg": 0, "detector": 1.0},
    {"raDeg": 5, "decDeg": 0, "start": "2023-01-01", "end": "2025-01-02"},
    {"raDeg": 7, "decDeg": 0, "upstreamUrl": "https://example.org"},
])
def test_validation(query):
    with pytest.raises(ValidationError):
        SeriesQuery.model_validate(query)


def test_normalization():
    assert SeriesQuery(raDeg=359.99999999, decDeg=1).normalized()["raDeg"] == 0
    assert SeriesQuery(raDeg=100, decDeg=-90).normalized()["raDeg"] == 0


def test_stream_body_limit():
    async def run():
        messages = iter([{"type": "http.request", "body": b"12345", "more_body": True},
                         {"type": "http.request", "body": b"67890", "more_body": False}])
        output = []

        async def receive():
            return next(messages)

        async def send(message):
            output.append(message)

        async def downstream(*_):
            pytest.fail("Oversized API body was accepted")

        app = RequestBounds(downstream, 9)
        await app({"type": "http", "method": "POST", "path": "/api/v1/series"}, receive, send)
        assert output[0]["status"] == 413
        assert json.loads(output[1]["body"])["code"] == "REQUEST_TOO_LARGE"

    asyncio.run(run())


def test_job_coalescing_queue_and_cancellation(tmp_path):
    jobs = Jobs(Settings(cache=tmp_path, job_workers=1, queue_limit=1))
    release = threading.Event()
    calls = []

    def delayed():
        calls.append("work")
        assert release.wait(4)
        return ready({"done": True})

    try:
        first = jobs.submit("first", "ip1", "session1", "discovery", delayed)
        assert jobs.submit("first", "ip2", "session2", "discovery", delayed)["jobId"] == first["jobId"]
        with pytest.raises(Problem, match="current request"):
            jobs.submit("other", "ip1", "session1", "discovery", delayed)
        queued = jobs.submit("queued", "ip3", "session3", "image", delayed)
        assert queued["status"] == "queued"
        with pytest.raises(Problem, match="queue is full"):
            jobs.submit("excess", "ip4", "session4", "image", delayed)
        jobs.abandon(queued["jobId"], "session3")
        assert jobs.read(queued["jobId"])["error"]["code"] == "JOB_CANCELLED"
        release.set()
        deadline = time.monotonic() + 1
        while jobs.read(first["jobId"])["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.005)
        assert jobs.read(first["jobId"])["data"]["done"]
        assert calls == ["work"]
    finally:
        release.set()
        jobs.close()


def test_failed_job_preserves_archive_reason(tmp_path):
    jobs = Jobs(Settings(cache=tmp_path))
    try:
        def unavailable():
            raise UpstreamError("UPSTREAM_UNAVAILABLE", "IRSA is unavailable.", 503, True)

        job = jobs.submit("unique", "ip", "session", "discovery", unavailable)
        deadline = time.monotonic() + 1
        while jobs.read(job["jobId"])["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.005)
        assert jobs.read(job["jobId"])["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    finally:
        jobs.close()


def test_upstream_admission_preserves_coalesced_and_local_work(tmp_path, monkeypatch):
    settings = Settings(cache=tmp_path, job_workers=1, irsa_daily_bytes=10, catalog_daily_bytes=2)
    transfers = upstream.RollingTransfers(settings)
    monkeypatch.setattr(upstream, "TRANSFERS", transfers)
    monkeypatch.setattr(upstream, "CIRCUITS", {"discovery": upstream.Circuit(), "images": upstream.Circuit()})
    transfers.charge("catalog", 2)
    with pytest.raises(Problem) as rejected:
        upstream.check_admission("catalog")
    assert rejected.value.code == "DAILY_BUDGET" and rejected.value.status == 429 and rejected.value.retry_after == 60

    jobs = Jobs(settings)
    finish = threading.Event()

    def work():
        assert finish.wait(2)
        return ready({})

    def admit():
        upstream.check_admission("metadata")

    try:
        original = jobs.submit("shared", "ip1", "session1", "archive", work, admit=admit)
        upstream.CIRCUITS["discovery"].until = time.monotonic() + 30
        same = jobs.submit("shared", "ip2", "session2", "archive", work, admit=admit)
        assert same["jobId"] == original["jobId"]
        with pytest.raises(Problem) as blocked:
            jobs.submit("different", "ip3", "session3", "archive", work, admit=admit)
        assert blocked.value.code == "CIRCUIT_OPEN" and blocked.value.status == 503 and blocked.value.retry_after > 0
        assert jobs.submit("local", "ip3", "session3", "comparing cached frames", work)["status"] == "queued"
        assert "different" not in jobs.by_key
    finally:
        finish.set()
        jobs.close()


def test_half_open_circuit_retains_status_if_local_transfer_budget_blocks_probe(tmp_path, monkeypatch):
    availability = {"checkedAtUnix": int(time.time()), "status": "degraded"}
    previous_until = time.monotonic() - 2
    transfers = upstream.RollingTransfers(Settings(cache=tmp_path, irsa_daily_bytes=2))
    transfers.charge("irsa", 2)
    monkeypatch.setattr(upstream, "TRANSFERS", transfers)
    monkeypatch.setattr(upstream, "CIRCUITS", {"discovery": upstream.Circuit(until=previous_until),
                                             "images": upstream.Circuit()})
    monkeypatch.setattr(upstream, "LAST_PROBE", availability)

    def wire_call(*args, **options):
        pytest.fail("An exhausted transfer budget reached the wire")

    monkeypatch.setattr(upstream.requests, "get", wire_call)
    with pytest.raises(Problem) as rejected:
        upstream.fetch("https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1", limit=100,
                       deadline=time.monotonic() + 2, purpose="metadata")
    assert rejected.value.code == "DAILY_BUDGET"
    discovery = upstream.CIRCUITS["discovery"]
    assert upstream.LAST_PROBE is availability and discovery.until == previous_until and not discovery.half_open


def test_successful_cube_probe_preserves_degraded_discovery_status(monkeypatch):
    monkeypatch.setattr(upstream, "CIRCUITS", {"discovery": upstream.Circuit(), "images": upstream.Circuit()})
    monkeypatch.setattr(upstream, "LAST_PROBE", None)
    monkeypatch.setattr(upstream, "LAST_DISCOVERY_PROBE", None)
    upstream.record_probe(False, True, "metadata")
    upstream.record_probe(False, False, "cube")
    assert upstream.LAST_PROBE["purpose"] == "cube" and upstream.LAST_PROBE["status"] == "reachable"
    assert upstream.LAST_DISCOVERY_PROBE["purpose"] == "metadata" and upstream.LAST_DISCOVERY_PROBE["status"] == "degraded"


def test_store_idempotent_assets_and_canonical_frame(tmp_path):
    store = Store(Settings(cache=tmp_path))
    data = {"image": np.full((3, 3), 1.0), "valid": np.ones((3, 3), dtype=bool)}
    frame = store.save_frame("series", {"frameId": "frame"}, data, b"png content", b"mask")
    assert store.prepared("series", "frame") == frame
    np.testing.assert_equal(store.load_arrays("series", frame), data)
    assert store.public_asset(frame["imageUrl"].split("/")[-1]).read_bytes() == b"png content"
    png = Path(store.assets, frame["imageUrl"].split("/")[-1])
    png.unlink()
    assert store.prepared("series", "frame") is None


def test_bounded_upstream_address_and_accounting():
    path = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/foo/file.fits"
    assert check_url(path + "?center=0.001,-90&size=0.05", "cutout").hostname == "irsa.ipac.caltech.edu"
    for bad in (path, path + "?center=1,2&size=0.5", path + "?center=1,2&size=0.05&raw=1",
                path.replace("/foo/", "/../") + "?center=1,2&size=0.05",
                path.replace("ipac.caltech.edu", "example.net") + "?center=1,2&size=0.05"):
        with pytest.raises(UpstreamError, match="archive|cutout"):
            check_url(bad, "cutout")
    budget = TransferBudget(8, 2)
    budget.attempt()
    budget.charge(7)
    budget.attempt()
    with pytest.raises(UpstreamError, match="budget"):
        budget.attempt()
    with pytest.raises(UpstreamError, match="byte limit"):
        budget.charge(2)


def test_app_declares_same_origin_routes(tmp_path):
    app = create_app(Settings(cache=tmp_path, web=tmp_path))
    routes = set(app.openapi()["paths"])
    routes.update(route.path for route in app.routes if hasattr(route, "path"))
    assert {"/", "/explore", "/readyz", "/api/v1/series", "/data/{name}", "/presets"} <= routes


def test_readiness_checks_the_installed_bundle_and_cache_schema(tmp_path):
    dist = tmp_path / "dist"
    shutil.copytree(ROOT / "web" / "public" / "presets", dist / "presets")
    store = Store(Settings(cache=tmp_path / "cache", web=dist, presets=ROOT / "presets"))
    assert 0 < store.example_bundle() < 100 * MIB
    assert store.cache_available()
    barnard = dist / "presets" / "barnard"
    (barnard / next(barnard.glob("*.png")).name).unlink()
    assert store.example_bundle() is None
    store.db.unlink()
    assert not store.cache_available()


def test_telemetry_reports_observations_and_only_alerts_for_sustained_failure(tmp_path, monkeypatch, caplog):
    from types import SimpleNamespace

    settings = Settings(cache=tmp_path, monitor=True)
    service = Service(settings)
    telemetry = Telemetry(service)
    transfers = upstream.RollingTransfers(settings)
    monkeypatch.setattr(upstream, "TRANSFERS", transfers)
    transfers.charge("irsa", 19)
    service.store.get("series", "first")
    service.store.put("series", "first", {"status": "succeeded"})
    service.store.get("series", "first")

    async def downstream(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 429})
        await send({"type": "http.response.body", "body": b"limit"})

    async def noop(_message):
        pass

    try:
        asyncio.run(RequestTraffic(downstream)({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(telemetry=telemetry)),
                                                "query_string": b"secret=never-recorded"}, None, noop))
        work = telemetry.sample()
        assert work["upstream24hBytes"] == {"irsa": 19, "catalog": 0}
        assert work["cacheHits"] == work["cacheMisses"] == 1
        with caplog.at_level(logging.INFO, logger="uvicorn.error.spherex.telemetry"):
            for interval in range(ALERT_PERIODS + 1):
                now = int(time.time()) + interval * INTERVAL
                monkeypatch.setattr(upstream, "LAST_PROBE", {"checkedAtUnix": now, "status": "degraded"})
                telemetry.report({**work, "queueRejections": 1}, now)
        metrics = [json.loads(record.message.split(" ", 1)[1]) for record in caplog.records if record.message.startswith("spherex_metrics ")]
        assert metrics[0]["requests"] == metrics[0]["http429"] == 1 and metrics[0]["responseBodyBytes"] == 5
        assert metrics[1]["requests"] == 0
        assert caplog.text.count("reason=queue_saturation") == caplog.text.count("reason=archive_degraded") == 1
        assert "never-recorded" not in caplog.text
    finally:
        service.jobs.close()


def test_daily_release_inventory_retains_the_last_complete_snapshot(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    calls = []
    listings = {
        "": ["dr1/", "qr2/", "qr3/", "qr4/"],
        "dr1/level2/": ["dr1/level2/2026W20_1A/", "dr1/level2/2025W52_2A/"],
        "qr3/level2/": ["qr3/level2/2026W40_2A/"],
    }

    def fetch_listing(url, *, limit, deadline, purpose, budget):
        parts = check_url(url, purpose)
        prefix = parse_qs(parts.query, keep_blank_values=True)["prefix"][0]
        assert limit == 128 * 1024 and deadline > time.monotonic()
        calls.append(prefix)
        items = "".join(f"<CommonPrefixes><Prefix>{path}</Prefix></CommonPrefixes>" for path in listings[prefix])
        truncated = str(prefix == "qr3/level2/" and reject_listing).lower()
        data = f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Prefix>{prefix}</Prefix><IsTruncated>{truncated}</IsTruncated>{items}</ListBucketResult>'.encode()
        budget.attempt()
        budget.charge(len(data))
        return data

    reject_listing = False
    monkeypatch.setattr(release_index, "fetch", fetch_listing)
    service = Service(Settings(cache=tmp_path, disk_reserve=0))
    try:
        release_index.schedule_if_due(service)
    finally:
        service.jobs.close()
    info = service.store.get("release-index", "snapshot")[0]
    assert calls == ["", "dr1/level2/", "qr3/level2/"]
    assert info["published"] == ["DR1", "QR2", "QR3", "QR4"]
    assert info["planningPeriods"]["DR1"] == {"count": 2, "latestPlanningPeriod": "2026W20_1A"}
    release_index.schedule_if_due(service)
    assert len(calls) == 3

    reject_listing = True
    with pytest.raises(Problem, match="incomplete release listing"):
        release_index.refresh(service.store)
    assert service.store.get("release-index", "attempt")[0]["status"] == "failed"
    assert service.store.get("release-index", "snapshot")[0] == info


def test_ten_concurrent_clients_coalesce_and_preserve_analysis_slot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    release = threading.Event()
    jobs = Jobs(Settings(cache=tmp_path, job_workers=2))

    def work():
        assert release.wait(3)
        return ready({"ready": True})

    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(lambda i: jobs.submit('shared', f'ip{i}', f'session{i}', 'frame', work), range(10)))
        assert len({item['jobId'] for item in results}) == 1
        first = jobs.submit('analysisA', 'analysisA', 'analysisA', 'compare', work, extended=True)
        second = jobs.submit('analysisB', 'analysisB', 'analysisB', 'compare', work, extended=True)
        assert first['status'] == 'running' and second['status'] == 'queued'
        assert len(jobs.running) == 2
    finally:
        release.set()
        jobs.close()


def test_random_job_ids_are_valid_for_polling_even_when_nonce_starts_with_punctuation(tmp_path, monkeypatch):
    from pydantic import TypeAdapter

    from server import jobs as job_module
    from server.contracts import ID, JOB_ID

    monkeypatch.setattr(job_module.secrets, 'token_urlsafe', lambda _: '_nonce-with-urlsafe-punctuation')
    queue = Jobs(Settings(cache=tmp_path))
    try:
        job = queue.submit('key', 'local', 'session', 'test', lambda: ready({}))
        assert TypeAdapter(ID).validate_python(job['jobId']) == 'j_nonce-with-urlsafe-punctuation'
        assert TypeAdapter(JOB_ID).validate_python('_nonce-with-urlsafe-punctuation') == '_nonce-with-urlsafe-punctuation'
    finally:
        queue.close()
