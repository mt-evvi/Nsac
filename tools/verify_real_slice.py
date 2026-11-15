"""Reproduce a two-visit comparison from bounded public IRSA cutouts."""

import json
import time
from argparse import ArgumentParser
from hashlib import file_digest, sha256
from pathlib import Path

from server import analysis, imaging
from server.config import MIB
from server.upstream import IRSA_CLOUD, TransferBudget, fetch

FIELDS = {
    "barnard": ({"raDeg": 269.45, "decDeg": 4.768, "fovArcmin": 3.0}, 6, (
        ("DR1", "2025W33_2C", "2025W33_2C_0321_1", "l2b-v27-2026-228", 0.05),
        ("DR1", "2026W12_2A", "2026W12_2A_0520_4", "l2b-v27-2026-235", 0.066),
    )),
    "rw-aurigae-control": ({"raDeg": 76.95654167, "decDeg": 30.54311111, "fovArcmin": 8.0}, 1, (
        ("DR1", "2025W36_1A", "2025W36_1A_0663_1", "l2b-v27-2026-232", 0.16741667),
        ("QR3", "2026W37_1A", "2026W37_1A_0524_1", "l2b-v27-2026-255", 0.16741667),
    )),
}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fits-dir", type=Path, help="Directory with downloaded FITS named by observation ID.")
    parser.add_argument("--field", choices=FIELDS, default="barnard")
    opts = parser.parse_args()
    opts.output.mkdir(parents=True, exist_ok=True)
    query, detector, products = FIELDS[opts.field]
    calibration_name = f"spectral_wcs_D{detector}_spx_cal-swcs-v5-2026-191.fits"
    calibration = (opts.fits_dir or opts.output) / calibration_name
    if not calibration.is_file():
        root = f"https://{IRSA_CLOUD}/dr1/spectral_wcs/cal-swcs-v5-2026-191/{detector}"
        calibration = opts.output / calibration_name
        calibration.write_bytes(fetch(f"{root}/{calibration_name}", limit=37 * MIB,
                                      deadline=time.monotonic() + 30, purpose="calibration"))
    with calibration.open("rb") as stream:
        calibration_hash = file_digest(stream, "sha256").hexdigest()
    grid = imaging.grid_for(query)
    frames = []
    stretch = None
    for release, run, obs, version, width in products:
        product = f"level2_{obs}D{detector}_spx_{version}"
        address = f"https://irsa.ipac.caltech.edu/ibe/data/spherex/{release.lower()}/level2/{run}/{version}/{detector}/{product}.fits"
        entry = {"frameId": obs, "visitId": obs, "obsId": obs, "productId": product, "release": release,
                 "archiveUrl": address, "detector": detector}
        cutout_query = {**query, "cutoutSizeDeg": width}
        local = opts.fits_dir / f"{obs}.fits" if opts.fits_dir else None
        if local and local.is_file():
            payload = local.read_bytes()
        else:
            payload = imaging.download(cutout_query, entry, time.monotonic() + 30, TransferBudget(24 * MIB, 2))
        metadata, arrays, png, mask = imaging.process(payload, query, entry, grid, stretch, calibration)
        metadata.update(cutoutUrl=imaging.cutout_url(cutout_query, entry), cutoutSha256=sha256(payload).hexdigest())
        stretch = metadata["stretch"]
        frames.append({**arrays, "metadata": {**entry, **metadata, "grid": grid}})
        (opts.output / f"{obs}.png").write_bytes(png)
        (opts.output / f"{obs}-mask.png").write_bytes(mask)
    comparison, image = analysis.compare(frames[0], frames[1], "difference")
    image.save(opts.output / "difference.png")
    envelope = {"query": query, "frames": [frame["metadata"] for frame in frames], "comparison": comparison,
                "spectralCalibration": {"file": calibration_name, "sha256": calibration_hash}}
    (opts.output / "verification.json").write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
