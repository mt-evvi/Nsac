"""Verify that each offline example plays independent, registered archive cutouts."""

import argparse
import hashlib
import json
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image

from server.config import ROOT
from tools.build_presets import CATALOG, at_center_compatible

EXPECTED_ARCHIVE = "https://irsa.ipac.caltech.edu/ibe/data/spherex/"


def validate_frame(slug, shape, frame, root):
    assert frame["state"] == "prepared"
    assert frame["archiveUrl"].startswith(EXPECTED_ARCHIVE)
    assert frame["obsId"] in frame["productId"]
    assert frame["transferBytes"] <= 12 * 1024 * 1024
    wave, band = frame["wavelengthUm"], frame["bandwidthUm"]
    assert 0.75 <= wave <= 5 and 0 < band < 0.2
    assert frame["wavelengthCalibration"] == "cwave-cband"
    public = root / "web" / "public"
    image_path = public / frame["imageUrl"].lstrip("/")
    mask_path = public / frame["maskUrl"].lstrip("/")
    content = hashlib.sha256(image_path.read_bytes() + mask_path.read_bytes()).hexdigest()[:24]
    assert image_path.stem == content and mask_path.stem == f"{content}-mask"
    with Image.open(image_path) as png:
        raster = np.array(png)
    with Image.open(mask_path) as png:
        mask = np.array(png) > 0
    assert raster.shape == (*shape, 4) and mask.shape == shape
    path = root / "presets" / slug / f'{frame["frameId"]}.npz'
    with np.load(path, allow_pickle=False) as stored:
        arrays = {name: stored[name] for name in ("image", "variance", "valid", "coverage", "wavelength", "bandwidth")}
    assert all(value.shape == shape for value in arrays.values())
    valid = arrays["valid"]
    assert np.array_equal(np.flipud(valid), mask)
    assert np.array_equal(raster[..., 3] > 0, mask)
    assert np.isclose(valid.mean(), frame["validFraction"])
    assert np.isfinite(arrays["image"][valid]).all()
    assert (arrays["variance"][valid] > 0).all()
    assert np.isnan(arrays["image"][~valid]).all()
    return arrays


def overlap(a, b):
    width = np.minimum(a["bandwidth"], b["bandwidth"])
    offset = np.abs(a["wavelength"] - b["wavelength"])
    high = np.minimum(a["wavelength"] + a["bandwidth"] / 2, b["wavelength"] + b["bandwidth"] / 2)
    low = np.maximum(a["wavelength"] - a["bandwidth"] / 2, b["wavelength"] - b["bandwidth"] / 2)
    return float(np.mean(a["valid"] & b["valid"] & (offset <= width / 2) & (high - low >= width / 2)))


def verify(slug, *, root=ROOT):
    data = json.loads((root / "web" / "public" / "presets" / slug / "manifest.json").read_text())["data"]
    assert data["seriesId"] == f"preset-{slug}"
    frames = data["frames"]
    assert len(frames) == data["counts"]["preparedFrames"] >= 2
    assert len({frame["visitId"] for frame in frames}) == len(frames)
    assert list(frames) == sorted(frames, key=lambda frame: frame["startUtc"])
    assert len({tuple(frame["stretch"]) for frame in frames}) == 1
    shape = data["grid"]["height"], data["grid"]["width"]
    arrays = [validate_frame(slug, shape, frame, root) for frame in frames]
    pairs = [(i, j, overlap(arrays[i], arrays[j])) for i, j in combinations(range(len(frames)), 2)
             if at_center_compatible(frames[i], frames[j])]
    assert pairs and max(fraction for _, _, fraction in pairs) >= 0.25
    title = data["title"]
    coords = data["query"]
    print(f"{title} | {coords['raDeg']:.8f}°, {coords['decDeg']:+.8f}° | {coords['fovArcmin']}′ | "
          f"{data['counts']['observationDates']} archive UTC dates | {len(frames)} bundled visits | "
          f"{data['baselineDays']:.2f} days")
    for frame in frames:
        print(f"  {frame['startUtc']} {frame['release']} {frame['obsId']} D{frame['detector']} "
              f"{frame['wavelengthUm']:.6f} ± {frame['bandwidthUm']/2:.6f} µm | "
              f"{frame['coverageFraction']:.1%} covered, {frame['validFraction']:.1%} usable | "
              f"{', '.join(frame['flags'])}")
    print("  " + " ".join(f"{i + 1}/{j + 1}: {fraction:.1%}" for i, j, fraction in pairs))
    final = (datetime.fromisoformat(frames[-1]["startUtc"]) - datetime.fromisoformat(frames[0]["startUtc"]))
    assert abs(final.total_seconds() / 86400 - data["baselineDays"]) < 1e-6


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="*", metavar="PRESET")
    parser.add_argument("--root", type=Path, default=ROOT, help="Project-shaped directory containing the examples.")
    args = parser.parse_args()
    for slug in args.slugs or list(CATALOG):
        if slug not in CATALOG:
            parser.error(f"Unknown example {slug}")
        verify(slug, root=args.root)
