"""Archive discovery and image health are independent under shared hard budgets."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from server import archive, upstream
from server.config import Settings
from server.contracts import Problem


URLS = {
    "metadata": "https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1",
    "cutout": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/example/file.fits?center=1,2&size=0.05",
    "cube": "https://nasa-irsa-spherex.s3.amazonaws.com/dr1/hips5_cube/hips_20261026/Norder5/Dir0/Npix1_cube.fits",
    "calibration": "https://nasa-irsa-spherex.s3.amazonaws.com/dr1/spectral_wcs/cal-swcs-v5-2026-191/6/spectral_wcs_D6_spx_cal-swcs-v5-2026-191.fits",
}


class Response:
    def __init__(self, status=200, done=lambda: None, payload=b"abc"):
        self.status_code = status
        self.is_redirect = False
        self.headers = {"Content-Length": str(len(payload)), "Content-Range": "bytes 0-2/100"}
        self.done = done
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.done()

    def iter_content(self, chunk_size):
        yield self.payload


class Session:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.calls = []

    def get(self, url, **options):
        self.calls.append(url)
        assert options["stream"] is True and options["allow_redirects"] is False
        return Response(next(self.statuses))


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(upstream, "CIRCUITS", {"discovery": upstream.Circuit(), "images": upstream.Circuit()})
    monkeypatch.setattr(upstream, "LAST_PROBE", None)
    monkeypatch.setattr(upstream, "LAST_DISCOVERY_PROBE", None)
    transfers = upstream.RollingTransfers(Settings(cache=tmp_path))
    monkeypatch.setattr(upstream, "TRANSFERS", transfers)

    def forbidden(*_args, **_options):
        pytest.fail("Circuit tests must never call a live upstream")

    monkeypatch.setattr(upstream.requests, "get", forbidden)
    return transfers


def fetch(purpose, session):
    options = {"byte_range": (0, 2)} if purpose == "cube" else {}
    return upstream.fetch(URLS[purpose], limit=100, deadline=time.monotonic() + 3,
                          purpose=purpose, session=session, **options)


def test_discovery_outage_keeps_known_images_and_cloud_products_available(isolated):
    unavailable = Session([503] * 3)
    for _ in range(3):
        with pytest.raises(Problem) as rejected:
            fetch("metadata", unavailable)
        assert rejected.value.code == "UPSTREAM_UNAVAILABLE"
    assert upstream.CIRCUITS["discovery"].until > time.monotonic()
    for _ in range(5):
        with pytest.raises(Problem) as rejected:
            fetch("metadata", unavailable)
        assert rejected.value.code == "CIRCUIT_OPEN" and rejected.value.retry_after > 0
        assert "Archive search" in rejected.value.message
    assert len(unavailable.calls) == 3
    with pytest.raises(Problem, match="Archive search"):
        upstream.check_admission("metadata")

    upstream.check_admission("irsa")
    for purpose, status in (("cutout", 200), ("cube", 206), ("calibration", 200)):
        assert fetch(purpose, Session([status])) == b"abc"
    assert isolated.recent_bytes()["irsa"] == 9
    assert upstream.CIRCUITS["images"].until == 0
    assert upstream.LAST_DISCOVERY_PROBE["status"] == "degraded"
    assert upstream.LAST_PROBE["purpose"] == "calibration" and upstream.LAST_PROBE["status"] == "reachable"


def test_image_outage_has_its_own_failure_window_and_reason(isolated):
    unavailable = Session([503] * 3)
    for _ in range(3):
        with pytest.raises(Problem):
            fetch("cutout", unavailable)
    with pytest.raises(Problem, match="Archive image data") as rejected:
        upstream.check_admission("irsa")
    assert rejected.value.code == "CIRCUIT_OPEN" and rejected.value.retry_after > 0
    assert upstream.CIRCUITS["discovery"].until == 0
    upstream.check_admission("metadata")
    assert fetch("metadata", Session([200])) == b"abc"
    assert upstream.CIRCUITS["images"].until > time.monotonic()


def test_200_sia_payloads_must_validate_before_discovery_recovery(isolated, monkeypatch):
    malformed = b"<VOTABLE><RESOURCE>"
    query_error = b'''<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
      <RESOURCE type="results"><INFO name="QUERY_STATUS" value="ERROR">Backend unavailable</INFO></RESOURCE>
    </VOTABLE>'''
    overflow = b'''<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
      <RESOURCE type="results"><INFO name="QUERY_STATUS" value="OVERFLOW"/>
        <TABLE><FIELD name="access_url" datatype="char" arraysize="*"/>
          <FIELD name="obs_id" datatype="char" arraysize="*"/>
          <FIELD name="t_min" datatype="double"/>
          <DATA><TABLEDATA><TR><TD>example</TD><TD>image</TD><TD>60800.0</TD></TR></TABLEDATA></DATA>
        </TABLE>
      </RESOURCE>
    </VOTABLE>'''
    payloads = iter((malformed, query_error, malformed, query_error, overflow))
    calls = []

    def get(url, **_options):
        calls.append(url)
        return Response(payload=next(payloads))

    monkeypatch.setattr(upstream.requests, "get", get)
    day = date(2025, 11, 14)
    query = {"raDeg": 269.45, "decDeg": 4.768, "fovArcmin": 3}
    budget = upstream.TransferBudget(4 * 1024 * 1024, 12)

    def read():
        return archive.read_table("spherex_dr1", query, day, day, budget, time.monotonic() + 5)

    with pytest.raises(Problem) as rejected:
        read()
    assert rejected.value.code == "UPSTREAM_UNAVAILABLE" and rejected.value.retryable
    assert budget.attempts == 2
    with pytest.raises(Problem) as rejected:
        read()
    assert rejected.value.code == "CIRCUIT_OPEN"
    assert len(calls) == budget.attempts == 3
    assert upstream.LAST_DISCOVERY_PROBE["status"] == "degraded"
    assert fetch("cutout", Session([200])) == b"abc"

    discovery = upstream.CIRCUITS["discovery"]
    discovery.until = time.monotonic() - 1
    with pytest.raises(Problem) as rejected:
        read()
    assert rejected.value.code == "CIRCUIT_OPEN"
    assert len(calls) == 4 and discovery.until > time.monotonic()
    assert not discovery.half_open
    assert upstream.LAST_DISCOVERY_PROBE["status"] == "degraded"

    discovery.until = time.monotonic() - 1
    table, truncated = read()
    assert len(table) == 1 and truncated
    assert len(calls) == budget.attempts == 5
    assert discovery.until == 0 and not discovery.half_open and not discovery.failures
    assert upstream.LAST_DISCOVERY_PROBE["status"] == "reachable"
    assert isolated.recent_bytes()["irsa"] == budget.bytes + 3


def test_each_capability_admits_only_one_recovery_probe(isolated):
    for circuit in upstream.CIRCUITS.values():
        circuit.until = time.monotonic() - 1
    assert upstream.allow_probe("metadata") is True
    assert upstream.allow_probe("cube") is True
    for purpose in ("metadata", "cutout", "calibration"):
        with pytest.raises(Problem) as rejected:
            upstream.allow_probe(purpose)
        assert rejected.value.code == "CIRCUIT_OPEN"

    # An older image request completing cannot release either active recovery probe.
    upstream.record_probe(False, False, "cutout")
    assert all(circuit.half_open for circuit in upstream.CIRCUITS.values())
    upstream.record_probe(True, False, "metadata")
    assert not upstream.CIRCUITS["discovery"].half_open and upstream.CIRCUITS["discovery"].until == 0
    assert upstream.CIRCUITS["images"].half_open
    upstream.record_probe(True, True, "cube")
    assert not upstream.CIRCUITS["images"].half_open and upstream.CIRCUITS["images"].until > time.monotonic()
    assert upstream.allow_probe("metadata") is False


def test_local_transfer_limit_does_not_mark_recovery_success(isolated):
    isolated.ceiling["irsa"] = 6
    assert fetch("cutout", Session([200])) == b"abc"
    assert fetch("cube", Session([206])) == b"abc"
    discovery = upstream.CIRCUITS["discovery"]
    discovery.until = time.monotonic() - 1
    previous_until = discovery.until
    for category in ("metadata", "irsa"):
        with pytest.raises(Problem) as rejected:
            upstream.check_admission(category)
        assert rejected.value.code == "DAILY_BUDGET"
    session = Session([])
    with pytest.raises(Problem) as rejected:
        fetch("metadata", session)
    assert rejected.value.code == "DAILY_BUDGET" and not session.calls
    assert discovery.until == previous_until and not discovery.half_open
    assert upstream.LAST_DISCOVERY_PROBE is None
    assert isolated.recent_bytes()["irsa"] == 6


def test_old_failures_expire_without_cross_capability_recovery(isolated):
    discovery = upstream.CIRCUITS["discovery"]
    discovery.failures = [time.monotonic() - 61] * 3
    upstream.record_probe(False, True, "metadata")
    assert len(discovery.failures) == 1 and discovery.until == 0
    upstream.record_probe(False, True, "metadata")
    upstream.record_probe(False, True, "metadata")
    remaining = discovery.until - time.monotonic()
    assert 59 < remaining <= 60
    upstream.record_probe(False, False, "cube")
    assert discovery.until > time.monotonic()


def test_capabilities_still_share_two_outbound_connections(isolated):
    lock = threading.Lock()
    ready = threading.Barrier(3)
    two_started = threading.Event()
    third_started = threading.Event()
    release = threading.Event()
    active = maximum = calls = 0

    class BlockingSession:
        def get(self, _url, **options):
            nonlocal active, maximum, calls
            with lock:
                active += 1
                maximum = max(maximum, active)
                calls += 1
                if calls == 2:
                    two_started.set()
                if calls == 3:
                    third_started.set()
            assert release.wait(2)

            def done():
                nonlocal active
                with lock:
                    active -= 1

            return Response(206 if "Range" in options["headers"] else 200, done)

    def run(purpose):
        ready.wait(timeout=2)
        return fetch(purpose, BlockingSession())

    with ThreadPoolExecutor(max_workers=3) as workers:
        tasks = [workers.submit(run, purpose) for purpose in ("metadata", "cutout", "cube")]
        try:
            assert two_started.wait(2)
            assert not third_started.wait(.1)
        finally:
            release.set()
        assert [task.result(timeout=2) for task in tasks] == [b"abc"] * 3
    assert maximum == 2 and calls == 3 and active == 0
