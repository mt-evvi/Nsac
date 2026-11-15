import asyncio
import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from server.app import RequestBounds, create_app
from server.config import Settings
from server.contracts import Problem, SeriesQuery, ready
from server.jobs import Jobs
from server.store import Store
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
