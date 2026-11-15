"""Controlled science fixtures with known sky geometry and injected sources."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from server.analysis import AnalysisError, _matched, compare, detect, track

N = 64
SCALE = 6 / 3600
GRID = {
    "width": N, "height": N, "crpix": [32.5, 32.5],
    "crval": [359.999, 2], "cd": [[-SCALE, 0], [0, SCALE]],
}
YY, XX = np.indices((N, N))
STABLE = [(8, 9, 145), (22, 9, 135), (47, 8, 142), (49, 46, 130), (14, 47, 148)]


def scene(index, *, stable=True, random=True, **metadata):
    time = datetime(2025, 5, 1, tzinfo=timezone.utc) + timedelta(days=12 * index)
    image = np.full((N, N), 21.0)
    if random:
        image += np.random.default_rng(index).normal(0, 0.25, (N, N))
    if stable:
        for x, y, amplitude in STABLE:
            inject(image, x, y, amplitude)
    return {
        "metadata": {
            "frameId": f"frame{index}", "visitId": f"visit{index}", "detector": 3,
            "startUtc": time.isoformat(), "endUtc": time.isoformat(), "grid": GRID,
            "wavelengthUm": 2.25, "bandwidthUm": 0.04,
            "wavelengthCalibration": "synthetic", "epsfValidated": True, **metadata,
        },
        "image": image, "variance": np.full((N, N), 0.25 ** 2),
        "coverage": np.ones((N, N)), "valid": np.ones((N, N), dtype=bool),
        "wavelength": np.full((N, N), 2.25), "bandwidth": np.full((N, N), 0.04),
    }


def inject(image, x, y, amplitude):
    image += amplitude * np.exp(-((XX - x) ** 2 + (YY - y) ** 2) / (2 * 0.95 ** 2))


def mark(index, x, y):
    return {"frameId": f"frame{index}", "pixel": {"x": x, "y": y}}


def test_identical_sum_and_difference_on_common_pixels():
    a = scene(0, random=False)
    b = scene(1, random=False)
    b["valid"][40, 20] = False
    b["wavelength"][25:35, 20:30] = 2.3
    diff, total, _, valid, metadata = _matched(a, b)
    assert np.allclose(diff[valid], 0, atol=1e-12)
    assert np.allclose(total[valid], 2 * a["image"][valid], atol=1e-12)
    assert metadata["quantitative"]
    assert metadata["registration"]["referenceCount"] == len(STABLE)
    assert valid.sum() == N ** 2 - 101
    sign_info, heatmap = compare(a, b, "difference")
    sum_info, _ = compare(a, b, "sum")
    assert sign_info["limits"][0] == -sign_info["limits"][1]
    assert sum_info["units"] == "MJy/sr"
    assert heatmap.getpixel((20, N - 1 - 40))[-1] == 0
    assert heatmap.getpixel((22, N - 1 - 31))[-1] == 0


def test_signed_motion_relative_background_and_reversed_pair():
    a, b = scene(0, random=False), scene(1, random=False)
    inject(a["image"], 29, 31, 100)
    inject(b["image"], 32, 31, 100)
    b["image"] += 7
    diff, _, _, valid, info = _matched(a, b)
    reversed_diff, _, _, _, _ = _matched(b, a)
    assert info["backgroundOffsetBminusAMJySr"] == pytest.approx(7, abs=1e-10)
    assert diff[31, 29] < -95
    assert diff[31, 32] > 95
    assert np.allclose(diff[valid], -reversed_diff[valid], atol=1e-10)


def test_comparison_gates_common_passband_and_alignment():
    a, b = scene(0), scene(1, wavelengthCalibration="wcs-wave", epsfValidated=False)
    info, _ = compare(a, b, "difference")
    assert not info["quantitative"]
    assert detect([a, b])["candidates"] == []
    with pytest.raises(AnalysisError, match="effective PSFs") as rejected_score:
        compare(a, b, "residual_score")
    assert rejected_score.value.code == "UNVERIFIED_COMPARISON"
    b["wavelength"][:32] = 2.3
    with pytest.raises(AnalysisError) as rejected_overlap:
        compare(a, b, "sum")
    assert rejected_overlap.value.code == "LOW_OVERLAP"
    b["metadata"]["detector"] = 5
    with pytest.raises(AnalysisError) as rejected_band:
        compare(a, b, "sum")
    assert rejected_band.value.code == "INCOMPATIBLE_WAVELENGTH"


def test_source_recognition_quiet_field_and_injections():
    assert detect([scene(0), scene(1), scene(2)])["candidates"] == []
    frames = [scene(i) for i in range(4)]
    for i, frame in enumerate(frames):
        image = frame["image"]
        inject(image, 28 + 1.15 * i, 28.5, 55)
        inject(image, 44, 32, [30, 70, 45, 65][i])
        image[47, 25] += 200
    output = detect(frames[:3])
    assert {c["label"] for c in output["candidates"]} == {"motion candidate", "possible variable"}
    assert len(output["candidates"]) == 2
    candidate = next(c for c in output["candidates"] if c["label"] == "motion candidate")
    result = track(frames[:3], marks=candidate["marks"], automatic=True)
    held = result["forecast"]["samples"][-1]
    measured_x = 28 + 1.15 * 3
    error = abs(held["x"] - measured_x) * 6
    assert result["forecast"]["horizonDays"] == 12
    assert error < held["ellipse95Arcsec"], (error, held)
    assert len(result["forecast"]["samples"]) <= 25


def test_manual_marks_round_trip_ra_wrap_and_same_visit_rejection():
    frames = [scene(0), scene(1)]
    result = track(frames, marks=[mark(0, 33, 30), mark(1, 29, 30)])
    assert result["measurements"][0]["raDeg"] > 359
    assert result["measurements"][1]["raDeg"] < 1
    assert result["separationArcsec"] == pytest.approx(24, abs=1e-3)
    assert result["positionAngleDeg"] == pytest.approx(90, abs=0.01)
    assert result["baselineDays"] == 12
    assert result["measurements"][0]["sigmaArcsec"] >= 3
    assert result["forecastStatus"] == "TOO_FEW_EPOCHS"
    second = result["measurements"][1]
    sky_mark = {"frameId": "frame1", "sky": {"raDeg": second["raDeg"], "decDeg": second["decDeg"]}}
    assert track(frames, marks=[mark(0, 33, 30), sky_mark])["separationArcsec"] == pytest.approx(24, abs=1e-3)
    frames[1]["metadata"]["visitId"] = "visit0"
    with pytest.raises(AnalysisError) as rejected_visit:
        track(frames, marks=[mark(0, 33, 30), mark(1, 29, 30)])
    assert rejected_visit.value.code == "SAME_VISIT"
    frames[1]["metadata"]["visitId"] = "visit1"
    frames[1]["valid"][30, 29] = False
    with pytest.raises(AnalysisError) as rejected_mask:
        track(frames, marks=[mark(0, 33, 30), mark(1, 29, 30)])
    assert rejected_mask.value.code == "MARK_MASKED"


def test_forecast_refuses_stationary_ambiguous_and_curved_measurements():
    frames = [scene(i) for i in range(3)]
    fixed = [mark(i, 30, 28) for i in range(3)]
    linear = [mark(i, 30 + 2 * i, 28) for i in range(3)]
    curved = [mark(0, 30, 28), mark(1, 33, 33), mark(2, 31, 27)]
    assert track(frames, marks=fixed, automatic=True)["forecastStatus"] == "UNRESOLVED_MOTION"
    assert track(frames, marks=linear, automatic=True, ambiguous=True)["forecastStatus"] == "AMBIGUOUS_ASSOCIATION"
    assert track(frames, marks=linear)["forecastStatus"] == "UNVERIFIED_ASSOCIATION"
    bad = track(frames, marks=curved, automatic=True)
    assert bad["forecastStatus"] == "POOR_FIT"
    assert bad["forecast"] is None
    assert len(bad["measurements"]) == 3

