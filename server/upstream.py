"""Allowlisted streaming transport with shared transfer and failure limits."""

import re
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from .config import MIB, SETTINGS
from .contracts import Problem

IRSA = "irsa.ipac.caltech.edu"
GAIA = "gea.esac.esa.int"
GAVO = "dc.g-vo.org"
IRSA_CLOUD = "nasa-irsa-spherex.s3.amazonaws.com"
PATHS = {
    "metadata": {IRSA: re.compile(r"/SIA/?")},
    "cutout": {IRSA: re.compile(r"/ibe/data/spherex/(?:dr1|qr3)/level2/[A-Za-z0-9_./-]+\.fits(?:\.gz)?")},
    "catalog": {IRSA: re.compile(r"/(?:TAP/sync|cgi-bin/Gator/nph-query)"), GAIA: re.compile(r"/tap-server/tap/sync"),
                GAVO: re.compile(r"/tap/sync")},
    "calibration": {IRSA_CLOUD: re.compile(
        r"/(?:dr1|qr3)/(?:spectral_wcs|solid_angle_pixel_map)/cal-(?:swcs|sapm)-v[0-9]+-[0-9]{4}-[0-9]{3}/[1-6]/[a-zA-Z0-9_-]+\.fits")},
    "cube": {IRSA_CLOUD: re.compile(r"/dr1/hips5_cube/hips_20261026/Norder5/Dir(?:0|10000)/Npix[0-9]{1,5}_cube\.fits")},
    "release-index": {IRSA_CLOUD: re.compile(r"/")},
}
SEMAPHORES = {"irsa": threading.BoundedSemaphore(2), "catalog": threading.BoundedSemaphore(1)}
HEALTH_LOCK = threading.Lock()


@dataclass
class Circuit:
    failures: list[float] = field(default_factory=list)
    until: float = 0.0
    half_open: bool = False


# Search can fail while known cutouts and cloud products remain available.
# Both capabilities still share the same connection and transfer allowances.
CIRCUITS = {"discovery": Circuit(), "images": Circuit()}
LAST_PROBE = None
LAST_DISCOVERY_PROBE = None


class UpstreamError(Problem):
    pass


def daily_budget_error():
    return UpstreamError("DAILY_BUDGET", "The upstream transfer allowance is exhausted. Try again later.", 429, True, 60)


class TransferBudget:
    """Count each decoded chunk and each attempted upstream request."""

    def __init__(self, max_bytes, max_attempts):
        self.max_bytes = max_bytes
        self.max_attempts = max_attempts
        self.bytes = 0
        self.attempts = 0
        self.lock = threading.Lock()

    def attempt(self):
        with self.lock:
            if self.attempts >= self.max_attempts or self.bytes >= self.max_bytes:
                raise UpstreamError("LIMIT_REACHED", "The request reached its archive budget.", 422)
            self.attempts += 1

    def charge(self, count):
        with self.lock:
            self.bytes += count
            if self.bytes > self.max_bytes:
                raise UpstreamError("LIMIT_REACHED", "The request reached its archive byte limit.", 422)


class RollingTransfers:
    def __init__(self, settings):
        self.root = settings.cache
        self.path = self.root / "upstream.sqlite3"
        self.ceiling = {"irsa": settings.irsa_daily_bytes, "catalog": settings.catalog_daily_bytes}

    def charge(self, kind, count):
        self.root.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=3)) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS transfers (kind TEXT, minute INTEGER, bytes INTEGER, PRIMARY KEY(kind, minute))")
            conn.execute("BEGIN IMMEDIATE")
            minute = int(time.time() / 60)
            conn.execute("DELETE FROM transfers WHERE minute < ?", (minute - 1440,))
            prior = conn.execute("SELECT COALESCE(sum(bytes), 0) FROM transfers WHERE kind = ?", (kind,)).fetchone()[0]
            if count or prior >= self.ceiling[kind]:
                conn.execute("INSERT INTO transfers VALUES (?, ?, ?) ON CONFLICT(kind, minute) DO UPDATE SET bytes = bytes + excluded.bytes",
                             (kind, minute, count))
            conn.commit()
            if prior >= self.ceiling[kind] or prior + count > self.ceiling[kind]:
                raise daily_budget_error()

    def recent_bytes(self):
        if not self.path.is_file():
            return dict.fromkeys(self.ceiling, 0)
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
            totals = dict(conn.execute("SELECT kind,SUM(bytes) FROM transfers WHERE minute >= ? GROUP BY kind",
                                       (int(time.time() / 60) - 1440,)))
        return {kind: totals.get(kind, 0) for kind in self.ceiling}


TRANSFERS = RollingTransfers(SETTINGS)


def check_url(url, purpose):
    if len(url) > 8192 or any(ord(ch) <= 32 for ch in url):
        raise UpstreamError("UNSAFE_PRODUCT", "The archive supplied an unsupported product address.")
    parts = urlsplit(url)
    paths = PATHS.get(purpose, {})
    rule = paths.get(parts.netloc)
    if (parts.scheme != "https" or not rule or not rule.fullmatch(parts.path)
            or parts.fragment or any(part in {".", ".."} for part in parts.path.split("/"))):
        raise UpstreamError("UNSAFE_PRODUCT", "The archive supplied an unsupported product address.")
    if purpose == "cutout":
        try:
            params = parse_qs(parts.query, strict_parsing=True, max_num_fields=2)
            if set(params) != {"center", "size"} or any(len(values) != 1 for values in params.values()):
                raise ValueError
            ra, dec = map(float, params["center"][0].split(","))
            size = float(params["size"][0])
            if not 0 <= ra < 360 or not -90 <= dec <= 90 or not 0 < size <= 0.17:
                raise ValueError
        except ValueError as exc:
            raise UpstreamError("UNSAFE_PRODUCT", "The image request must include a bounded sky cutout.") from exc
    if purpose == "release-index":
        try:
            params = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
            prefix, = params.pop("prefix")
            if (params != {"list-type": ["2"], "delimiter": ["/"], "max-keys": ["256"]}
                    or not re.fullmatch(r"(?:(?:dr|qr)[0-9]+/level2/)?", prefix)):
                raise ValueError
        except (KeyError, ValueError) as exc:
            raise UpstreamError("UNSAFE_PRODUCT", "The release index requires a bounded directory listing.") from exc
    return parts


def seconds_left(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UpstreamError("ARCHIVE_TIMEOUT", "The upstream request exceeded its deadline.", 503, True)
    return remaining


def circuit_for(purpose):
    return CIRCUITS["discovery" if purpose == "metadata" else "images"]


def _check_circuit(now, purpose):
    circuit = circuit_for(purpose)
    if circuit.until > now or circuit.half_open:
        message = ("Archive search is temporarily unavailable. Cached examples and known exposures can still be viewed."
                   if purpose == "metadata" else
                   "Archive image data is temporarily unavailable. Already cached images remain available.")
        raise UpstreamError("CIRCUIT_OPEN", message, 503, True, max(1, int(circuit.until - now + 1)))


def check_admission(kind):
    """Reject new transfer-dependent work without reserving the recovery probe."""
    category = "irsa" if kind == "metadata" else kind
    if category == "irsa":
        with HEALTH_LOCK:
            _check_circuit(time.monotonic(), "metadata" if kind == "metadata" else "cutout")
    try:
        used = TRANSFERS.recent_bytes()[category]
    except (OSError, sqlite3.Error) as exc:
        raise UpstreamError("TRANSFER_ACCOUNTING_UNAVAILABLE", "Transfer accounting is temporarily unavailable.", 503, True, 5) from exc
    if used >= TRANSFERS.ceiling[category]:
        raise daily_budget_error()


def allow_probe(purpose):
    with HEALTH_LOCK:
        _check_circuit(time.monotonic(), purpose)
        circuit = circuit_for(purpose)
        probe = bool(circuit.until)
        circuit.half_open = probe
        return probe


def record_probe(probe, failure, purpose):
    global LAST_PROBE, LAST_DISCOVERY_PROBE
    with HEALTH_LOCK:
        circuit = circuit_for(purpose)
        now = time.monotonic()
        if failure is None:
            if probe:
                circuit.half_open = False
            return
        LAST_PROBE = {"checkedAtUnix": int(time.time()), "status": "degraded" if failure else "reachable", "purpose": purpose}
        if purpose == "metadata":
            LAST_DISCOVERY_PROBE = LAST_PROBE
        if failure:
            circuit.failures[:] = [t for t in circuit.failures if now - t < 60]
            circuit.failures.append(now)
            if probe or len(circuit.failures) >= 3:
                circuit.until = now + 60
        elif probe:
            circuit.until = 0.0
            circuit.failures.clear()
        if probe:
            circuit.half_open = False


def fetch(url, *, limit, deadline, purpose, budget=None, byte_range=None, session=None, decode=None):
    """Stream one bounded response, optionally decoding it before recording probe success."""
    if purpose == "catalog":
        limit = min(limit, MIB)
    elif purpose != "calibration":
        limit = min(limit, 12 * MIB)
    if purpose == "cube" and (byte_range is None or not 0 <= byte_range[0] <= byte_range[1] < 512 * MIB
                              or byte_range[1] - byte_range[0] + 1 > limit):
        raise UpstreamError("LIMIT_REACHED", "Cube reads require a bounded byte range.")
    category = "catalog" if purpose == "catalog" else "irsa"
    check_url(url, purpose)
    semaphore = SEMAPHORES[category]
    if not semaphore.acquire(timeout=seconds_left(deadline)):
        raise UpstreamError("ARCHIVE_TIMEOUT", "The upstream request exceeded its deadline.", 503, True)
    try:
        return _fetch(url, limit, deadline, purpose, category, budget, byte_range, session, decode)
    finally:
        semaphore.release()


def _fetch(url, limit, deadline, purpose, category, budget, byte_range, session, decode):
    tracks_archive_health = category == "irsa" and purpose != "release-index"
    probe = allow_probe(purpose) if tracks_archive_health else False
    failure = False
    completed = False
    try:
        TRANSFERS.charge(category, 0)
        for _ in range(3):
            original = check_url(url, purpose)
            if budget is not None:
                budget.attempt()
            remaining = seconds_left(deadline)
            headers = {"User-Agent": "SPHEREx-SpaceApps/1.0", "Accept-Encoding": "identity"}
            if byte_range is not None:
                first, last = byte_range
                headers["Range"] = f"bytes={first}-{last}"
            client = session if session is not None else requests
            with client.get(url, stream=True, allow_redirects=False, timeout=(min(3, remaining), min(10, remaining)),
                            headers=headers) as response:
                code = response.status_code
                if response.is_redirect:
                    target = urljoin(url, response.headers["Location"])
                    resolved = check_url(target, purpose)
                    if purpose == "cutout" and (resolved.path != original.path or resolved.query != original.query):
                        raise UpstreamError("UNSAFE_PRODUCT", "The archive changed the requested cutout target.")
                    url = target
                    continue
                expected_status = 206 if byte_range is not None else 200
                if byte_range is not None and code == 200:
                    raise UpstreamError("LIMIT_REACHED", "The upstream server did not honor the bounded byte range.")
                if code != expected_status:
                    if code == 404:
                        raise UpstreamError("PRODUCT_MISSING", "The archive product is unavailable.", 404)
                    retryable = code == 429 or code >= 500
                    retry_after = response.headers.get("Retry-After", "")
                    wait = int(retry_after) if re.fullmatch(r"\d{1,4}", retry_after) else None
                    raise UpstreamError("UPSTREAM_UNAVAILABLE", "The upstream service did not return the requested data.",
                                        503 if retryable else 502, retryable, wait)
                if byte_range is not None:
                    content_range = response.headers.get("Content-Range", "")
                    if not re.fullmatch(rf"bytes {first}-{last}/[0-9]+", content_range):
                        raise UpstreamError("UPSTREAM_UNAVAILABLE", "The requested archive byte range was not returned.", 502)
                length = response.headers.get("Content-Length", "")
                if length.isascii() and length.isdecimal() and len(length) < 20 and int(length) > limit:
                    raise UpstreamError("LIMIT_REACHED", "The upstream response exceeds the download limit.")
                data = bytearray()
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    TRANSFERS.charge(category, len(chunk))
                    if budget is not None:
                        budget.charge(len(chunk))
                    seconds_left(deadline)
                    if len(data) + len(chunk) > limit:
                        raise UpstreamError("LIMIT_REACHED", "The upstream response exceeds the download limit.")
                    data.extend(chunk)
                if byte_range is not None and len(data) != last - first + 1:
                    raise UpstreamError("UPSTREAM_UNAVAILABLE", "The requested archive byte range was incomplete.", 502, True)
            payload = bytes(data)
            if decode is not None:
                seconds_left(deadline)
                result = decode(payload)
                seconds_left(deadline)
            else:
                result = payload
            completed = True
            return result
        raise UpstreamError("UNSAFE_PRODUCT", "The upstream service returned too many redirects.")
    except requests.exceptions.RequestException as exc:
        failure = True
        timeout = isinstance(exc, requests.exceptions.Timeout) or "timed out" in str(exc).lower()
        code = "ARCHIVE_TIMEOUT" if timeout else "UPSTREAM_UNAVAILABLE"
        raise UpstreamError(code, "The upstream connection was interrupted. Try again shortly.", 503, True) from exc
    except Problem as exc:
        failure = exc.code in {"UPSTREAM_UNAVAILABLE", "ARCHIVE_TIMEOUT"} and exc.retryable
        raise
    finally:
        if tracks_archive_health and (completed or failure or probe):
            record_probe(probe, failure if completed or failure else None, purpose)
