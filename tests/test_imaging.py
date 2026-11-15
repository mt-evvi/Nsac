from io import BytesIO

import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from astropy.io import fits
from PIL import Image

from server.contracts import Problem
from server.imaging import FATAL_MASK, SOURCE_MASK, grid_for, process, resample, wcs_for


def test_shared_grid_at_wrap_and_poles():
    for ra, dec in ((359.9999, 0), (0.0001, 89.999), (170, -90)):
        grid = grid_for(dict(raDeg=ra, decDeg=dec, fovArcmin=3))
        wcs = wcs_for(grid)
        center = (grid["width"] - 1) / 2
        sky = wcs.pixel_to_world(center, center)
        assert sky.separation(SkyCoord(ra, dec, unit="deg")).arcsec < 1e-6
        x, y = wcs.world_to_pixel(wcs.pixel_to_world(1.5, 2.7))
        np.testing.assert_allclose((x, y), (1.5, 2.7), atol=2e-7)


def test_bilinear_squared_weight_and_conservative_mask():
    raw = np.array([[2.0, 4.0], [6.0, 8.0]])
    var = np.full(raw.shape, 8.0)
    valid = np.ones(raw.shape, dtype=bool)
    x, y = np.array([[0.5, -0.5]]), np.array([[0.5, 0.5]])
    image, variance, coverage, good = resample(raw, var, valid, x, y)
    np.testing.assert_allclose(image, [[5.0, np.nan]])
    np.testing.assert_allclose(variance, [[2.0, np.nan]])
    np.testing.assert_allclose(coverage, [[1.0, 0.5]])
    assert good.tolist() == [[True, False]]
    valid[1, 1] = False
    assert not resample(raw, var, valid, x, y)[3].any()


def fixture_cutout(query, dx, *, empty=False, mover=False, survey_header=None):
    wcs = wcs_for(grid_for(query))
    wcs.wcs.crpix += [dx, 0]
    header = wcs.to_header()
    header["BUNIT"] = "MJy/sr"
    header["DETECTOR"] = 6
    header["DATE-BEG"] = "2025-08-15T20:45:11.337"
    header["DATE-END"] = "2025-08-15T20:47:06.455"
    header.update(survey_header or {})
    raw = np.zeros((29, 29), dtype=np.float32)
    raw[10, 9 + dx] = 12
    raw[18, 14 + dx + int(mover)] = 9
    flags = np.zeros(raw.shape, dtype=np.int32)
    flags[10, 9 + dx] = SOURCE_MASK
    flags[12, 14] = 1
    if empty:
        flags[:] = FATAL_MASK
    hdus = [fits.PrimaryHDU(), fits.ImageHDU(raw, header, name="IMAGE"), fits.ImageHDU(flags, name="FLAGS"),
            fits.ImageHDU(np.ones_like(raw), name="VARIANCE")]
    payload = BytesIO()
    fits.HDUList(hdus).writeto(payload)
    return payload.getvalue()


def test_cutouts_align_stationary_source_keep_moving_source_and_flip_png():
    query = {"raDeg": 359.9998, "decDeg": -25, "fovArcmin": 3}
    grid = grid_for(query)
    entry = {"release": "DR1", "detector": 6}
    _, first, _, _ = process(fixture_cutout(query, 0), query, entry, grid)
    info, second, png, mask = process(fixture_cutout(query, 2, mover=True), query, entry, grid)
    assert first["image"][10, 9] == pytest.approx(second["image"][10, 9], abs=1e-6)
    assert second["image"][18, 15] == pytest.approx(first["image"][18, 14], abs=1e-6)
    assert second["image"][18, 14] == pytest.approx(0, abs=1e-6)
    assert not second["valid"][12, 12]
    rgba = np.array(Image.open(BytesIO(png)))
    assert rgba[-11, 9, 0] > 0
    assert rgba[-13, 12, 3] == 0
    assert np.array(Image.open(BytesIO(mask)))[-13, 12] == 0
    assert info["startUtc"] == "2025-08-15T20:45:11.337Z"
    with pytest.raises(Problem) as exc:
        process(fixture_cutout(query, 0, empty=True), query, entry, grid)
    assert exc.value.code == "LOW_OVERLAP"



@pytest.mark.parametrize(("release", "angle", "expected"), [
    ("DR1", 0.0, "Survey 1"), ("DR1", 180.0, "Survey 2"),
    ("QR3", 0.0, "Survey 3"), ("QR3", 180.0, "Survey 4"),
    ("QR3", 90.0, None), ("QR3", True, None), ("QR2", 0.0, None),
])
def test_prepared_survey_pass_from_archived_angle(release, angle, expected):
    query = {"raDeg": 1.0, "decDeg": 2.0, "fovArcmin": 3}
    header = {"HIERARCH SPS_FLAGS": "all_sky", "HIERARCH NON_SURVEY": "False", "SPS_EPA": angle}
    entry = {"release": release, "detector": 6}
    info, _, _, _ = process(fixture_cutout(query, 0, survey_header=header), query, entry, grid_for(query))
    assert info.get("surveyPass") == expected


def test_survey_pass_requires_explicit_all_sky_observation():
    from server.imaging import survey_pass

    assert survey_pass({"SPS_FLAGS": "all_sky", "NON_SURVEY": False, "SPS_PA_ECL": "180"}, "QR3") == "Survey 4"
    assert survey_pass({"SPS_FLAGS": "all_sky", "NON_SURVEY": "True", "SPS_EPA": 0}, "DR1") is None
    assert survey_pass({"SPS_FLAGS": "deep", "NON_SURVEY": False, "SPS_EPA": 180}, "DR1") is None
    assert survey_pass({"SPS_FLAGS": "all_sky", "SPS_EPA": 180}, "DR1") is None


@pytest.mark.parametrize("followup_pass", ["Survey 2", "Survey 3", None])
def test_coadd_weights_nearby_matched_exposures_and_drops_anchor_psf(followup_pass):
    from server.imaging import coadd

    query = dict(raDeg=1, decDeg=1, fovArcmin=3)
    grid = grid_for(query)
    dims = grid['height'], grid['width']
    common = dict(visitId='night', detector=6, state='prepared', wavelengthUm=4.68, bandwidthUm=0.04,
                  archiveUrl='https://example.invalid/fixture', imageUrl='/unused.png', stretch=[1, 7])
    start = dict(common, frameId='a', productId='exposure-a', startUtc='2025-10-10T00:00:00.000Z',
                 endUtc='2025-10-10T00:01:00.000Z', epsfModel={'zone':1}, surveyPass='Survey 2')
    followup = dict(common, frameId='b', productId='exposure-b', startUtc='2025-10-10T00:10:00.000Z',
                    endUtc='2025-10-10T00:11:00.000Z', surveyPass=followup_pass)
    late = dict(followup, frameId='late', productId='later', startUtc='2025-10-10T02:10:00.000Z')

    class FixtureStore:
        changed = 0.0

        def prepared(self, series, frame):
            return None

        def load_arrays(self, series, frame):
            assert frame['frameId'] != 'late'
            first = frame['frameId'] == 'a'
            valid = np.ones(dims, dtype=bool)
            if not first:
                valid[0, 0] = False
            return {"image": np.full(dims, 2. if first else 4. + self.changed), "variance": np.full(dims, 1. if first else 4.),
                    "valid": valid, "coverage": np.ones(dims), "wavelength": np.full(dims, 4.68),
                    "bandwidth": np.full(dims, 0.04), "effectivePsf": np.ones((9, 9)) / 81}

    manifest = dict(seriesId='fixture', query=query, grid=grid, frames=[start, followup, late])
    display, arrays, png, mask = coadd(manifest, start, FixtureStore(), 'coadd-id')
    assert display['representation'] == 'coadd'
    assert display['frameId'] == coadd(manifest, start, FixtureStore(), 'coadd-id')[0]['frameId']
    changed = FixtureStore()
    changed.changed = 1.0
    assert display['frameId'] != coadd(manifest, start, changed, 'coadd-id')[0]['frameId']
    assert len(display['contributors']) == 2
    assert display.get('surveyPass') == ('Survey 2' if followup_pass == 'Survey 2' else None)
    assert 'epsfModel' not in display and 'effectivePsf' not in arrays
    assert arrays['image'][18, 18] == pytest.approx(2.4)
    assert arrays['variance'][18, 18] == pytest.approx(0.8)
    assert np.isnan(arrays['image'][0, 0])
    assert png and mask


def test_coadd_preserves_archive_failure_when_the_second_exposure_cannot_be_checked(monkeypatch):
    from types import SimpleNamespace

    from server import imaging
    from server.contracts import Problem

    common = {"visitId": "night", "detector": 1, "wavelengthUm": 1.0, "bandwidthUm": 0.025}
    first = {**common, "frameId": "first", "startUtc": "2025-10-10T00:00:00Z"}
    second = {**common, "frameId": "second", "startUtc": "2025-10-10T00:10:00Z"}
    manifest = {"seriesId": "test", "query": {}, "grid": {}, "frames": [first, second]}
    store = SimpleNamespace(prepared=lambda *_: None)

    def prepare(_query, frame, _grid, **_options):
        if frame is second:
            raise Problem("CIRCUIT_OPEN", "Archive is temporarily unavailable.", 503, True, 30)
        data = np.ones((4, 4))
        return {}, {"valid": data.astype(bool), "variance": data, "image": data}, None, None

    monkeypatch.setattr(imaging, "prepare", prepare)
    with pytest.raises(Problem) as rejected:
        imaging.coadd(manifest, first, store, "recipe")
    assert rejected.value.code == "CIRCUIT_OPEN" and rejected.value.status == 503 and rejected.value.retry_after == 30
