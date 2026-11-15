"""Reproduce the first two-visit Barnard comparison from bounded public cutouts."""

import json
import time
from argparse import ArgumentParser
from pathlib import Path

from server import analysis, imaging
from server.config import MIB
from server.upstream import IRSA_CLOUD, TransferBudget, fetch

QUERY = {"raDeg": 269.45, "decDeg": 4.768, "fovArcmin": 3.0}
PRODUCTS = [
    ("2025W33_2C", "2025W33_2C_0321_1", "l2b-v27-2026-228", 0.05),
    ("2026W12_2A", "2026W12_2A_0520_4", "l2b-v27-2026-235", 0.066),
]
CALIBRATION = "spectral_wcs_D6_spx_cal-swcs-v5-2026-191.fits"


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fits-dir", type=Path, help="Directory with downloaded FITS named by observation ID.")
    opts = parser.parse_args()
    opts.output.mkdir(parents=True, exist_ok=True)
    calibration = (opts.fits_dir or opts.output) / CALIBRATION
    if not calibration.is_file():
        root = f"https://{IRSA_CLOUD}/dr1/spectral_wcs/cal-swcs-v5-2026-191/6"
        calibration = opts.output / CALIBRATION
        calibration.write_bytes(fetch(f"{root}/{CALIBRATION}", limit=37 * MIB,
                                      deadline=time.monotonic() + 30, purpose="calibration"))
    grid = imaging.grid_for(QUERY)
    frames = []
    stretch = None
    for run, obs, version, width in PRODUCTS:
        product = f"level2_{obs}D6_spx_{version}"
        address = f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/{run}/{version}/6/{product}.fits"
        entry = {"frameId": obs, "visitId": obs, "obsId": obs, "productId": product, "release": "DR1",
                 "archiveUrl": address, "detector": 6}
        query = dict(QUERY, cutoutSizeDeg=width)
        local = opts.fits_dir / f"{obs}.fits" if opts.fits_dir else None
        if local and local.is_file():
            payload = local.read_bytes()
        else:
            payload = imaging.download(query, entry, time.monotonic() + 30, TransferBudget(24 * MIB, 2))
        metadata, arrays, png, mask = imaging.process(payload, QUERY, entry, grid, stretch, calibration)
        stretch = metadata["stretch"]
        frames.append({**arrays, "metadata": {**entry, **metadata, "grid": grid}})
        (opts.output / f"{obs}.png").write_bytes(png)
        (opts.output / f"{obs}-mask.png").write_bytes(mask)
    comparison, image = analysis.compare(frames[0], frames[1], "difference")
    image.save(opts.output / "difference.png")
    envelope = {"query": QUERY, "frames": [frame["metadata"] for frame in frames], "comparison": comparison}
    (opts.output / "verification.json").write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
