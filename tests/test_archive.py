"""Deterministic IRSA discovery contracts independent of network availability."""

from datetime import date
from collections import Counter
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

import pytest

from server import archive
from server.contracts import Problem

QUERY = {"raDeg": 269.45, "decDeg": 4.768, "fovArcmin": 3.0}


def product(frame, obs, release, day, detector=6, hour='01', wave=4.93):
    return {"frameId": frame, "obsId": obs, "release": release, "detector": detector,
            "productId": frame, "slotKey": day, "startUtc": f"{day}T{hour}:00:00Z",
            "endUtc": f"{day}T{hour}:02:00Z", "estimatedWavelengthUm": wave,
            "estimatedBandwidthUm": 0.038, "footprintMarginPx": 100}


def test_dedup_pointings_dates_and_multi_midnight_visit():
    start, crossing, late = '2025-08-01', '2025-08-02', '2025-08-10'
    frames = [product('dr1', 'A', 'DR1', start, hour='23'), product('qr3', 'A', 'QR3', start, hour='23'),
              product('parallel', 'A', 'QR3', start, detector=2, hour='23'),
              product('midnight', 'B', 'QR3', crossing), product('late', 'C', 'QR3', late)]
    manifest = archive.make_manifest(QUERY, frames)
    assert manifest['counts'] == dict(products=4, pointings=3, observationDates=3, independentEpochs=2, preparedFrames=0)
    by_id = {frame['frameId']: frame for frame in manifest['frames']}
    assert 'dr1' not in by_id
    assert by_id['qr3']['visitId'] == by_id['midnight']['visitId']
    assert by_id['late']['visitId'] != by_id['midnight']['visitId']
    assert [item['slotKey'] for item in manifest['frames'][:3]] == [start, crossing, late]


def test_shortlist_uses_coarse_calibration_but_preserves_near_misses():
    assert archive.estimate_passband(6, (1628.5, 267.0))[:2] == pytest.approx((4.9282, 0.0368), abs=0.003)
    day = '2025-08-01'
    frames = [product('far', 'A', 'DR1', day, wave=4.72), product('close', 'B', 'DR1', day, wave=4.905),
              product('best', 'C', 'DR1', day, wave=4.93)]
    manifest = archive.make_manifest(dict(QUERY, wavelengthUm=4.93), frames)
    assert [item['frameId'] for item in manifest['frames']] == ['best', 'close']
    empty = archive.make_manifest(dict(QUERY, detector=2), frames)
    assert empty['searchStatus'] == 'NO_COMPARABLE_FRAMES'


def test_bad_votable_is_retryable_error_instead_of_no_coverage():
    with pytest.raises(Problem) as exc:
        archive.parse_votable(b'<error>temporarily unavailable</error>')
    assert exc.value.retryable and exc.value.code == 'UPSTREAM_UNAVAILABLE'


def test_partial_and_complete_empty_are_distinct():
    assert archive.make_manifest(QUERY, [], complete=False)['searchStatus'] == 'PARTIAL'
    assert archive.make_manifest(QUERY, [])['searchStatus'] == 'NO_COVERAGE'
    start, end = archive.query_dates(dict(QUERY, start='2020-01-01', end='2020-01-02'))
    assert start == date(2025, 4, 1) and end == date(2020, 1, 2)


@pytest.mark.parametrize('ignored_maxrec', [False, True])
def test_discovery_row_budget_is_shared_and_preserves_partial_frames(monkeypatch, ignored_maxrec):
    first_responses = Barrier(2, timeout=3)
    requests = {name: [] for name, _, _ in archive.COLLECTIONS}
    accepted = Counter()

    def fetch(url, *, budget, **_):
        budget.attempt()
        params = parse_qs(urlsplit(url).query)
        collection, = params['COLLECTION']
        size = int(params['MAXREC'][0])
        requests[collection].append(size)
        if len(requests[collection]) == 1:
            first_responses.wait()
        return range(size + int(ignored_maxrec)), True

    def index_table(rows, query, release, doi):
        accepted[release] += len(rows)
        return [product(release, release, release, '2025-08-01')]

    monkeypatch.setattr(archive, 'fetch', fetch)
    monkeypatch.setattr(archive, 'index_table', index_table)
    result = archive.discover(dict(QUERY, start='2025-04-01', end='2026-01-01'))
    assert result['searchStatus'] == 'PARTIAL'
    assert not result['complete']
    assert {frame['release'] for frame in result['frames']} == {'DR1', 'QR3'}
    assert all(0 < n <= 500 for sizes in requests.values() for n in sizes)
    assert sum(len(sizes) for sizes in requests.values()) <= 12
    assert sum(accepted.values()) == (1000 if ignored_maxrec else 4000)
    assert sum(collection['rows'] for collection in result['collections']) == sum(accepted.values())
    message = 'more rows than requested' if ignored_maxrec else 'combined archive row limit'
    assert any(message in warning for warning in result['warnings'])
