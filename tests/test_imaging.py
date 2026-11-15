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


def fixture_cutout(query, dx, *, empty=False, mover=False):
    wcs = wcs_for(grid_for(query))
    wcs.wcs.crpix += [dx, 0]
    header = wcs.to_header()
    header["BUNIT"] = "MJy/sr"
    header["DETECTOR"] = 6
    header["DATE-BEG"] = "2025-08-15T20:45:11.337"
    header["DATE-END"] = "2025-08-15T20:47:06.455"
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
