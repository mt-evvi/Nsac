"""Build a matched, source-linked SPHEREx preset set through the live frame pipeline."""

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
from astropy.io import fits

from server import archive, imaging
from server.config import MIB, ROOT
from server.contracts import Problem, ready
from server.upstream import TransferBudget

START = "2025-04-01"
END = "2026-11-14"
YEAR = "J2026.0"
SIMBAD = "https://simbad.u-strasbg.fr/simbad/sim-id?Ident="
CATALOG = {
    "barnard": ("Barnard’s Star", "HIP 87937", SIMBAD + "HIP+87937", YEAR, 269.45, 4.768, 3, 6, 4.9282),
    "epsilon-indi-b": ("Epsilon Indi B", "2MASS J22041052−5646577",
                       "https://www.aanda.org/articles/aa/pdf/2004/03/aa0292.pdf",
                       YEAR, 331.09656943, -56.80083957, 3, 4, 3.6),
    "wise-0855": ("WISE 0855", "WISE J085510.83−071442.5", "https://doi.org/10.3847/0004-6256/152/3/78",
                  YEAR, 133.75977, -7.24218, 5, 6, 4.53),
    "wise-0855-nasa": ("WISE 0855 · NASA coordinates", "WISE J085510.83−071442.5",
                       "https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/?tab=details",
                       "NASA challenge seed, historical WISE position", 133.79512917, -7.24514722, 6, 6, 4.53),
    "rw-aurigae": ("RW Aurigae", "RW Aur", "https://vsx.aavso.org/index.php?revid=418953&view=detail.top",
                   "J2000", 76.95654167, 30.40144444, 3, 1, 0.95),
    "r-draconis": ("R Draconis", "R Dra", "https://archive.aavso.org/index.php/aavso-bulletin-coordinates",
                   "J2000", 248.16761, 66.75498, 3, 1, 0.95),
}
SNAPSHOT = {
    "barnard": "Barnard-spherex_qr3.xml",
    "epsilon-indi-b": "Epsilon-spherex_dr1.xml Epsilon-spherex_qr3.xml",
    "wise-0855": "wise-dr1.xml wise-qr3.xml",
    "wise-0855-nasa": "WISE-0855-challenge-seed-spherex_dr1.xml WISE-0855-challenge-seed-spherex_qr3.xml",
    "rw-aurigae": "RW-Aurigae-spherex_dr1.xml RW-Aurigae-spherex_qr3.xml",
    "r-draconis": "rd-dr1.xml retry-248.1676075-qr3.xml",
}
ASTROMETRY = {
    "barnard": {"referenceRaDeg": 269.452076959, "referenceDecDeg": 4.693364967, "referenceEpoch": "J2000.0",
                 "pmRaCosDecMasYr": -801.551, "pmDecMasYr": 10362.394},
    "epsilon-indi-b": {"referenceRaDeg": 331.043833333, "referenceDecDeg": -56.782694444,
                       "referenceEpoch": "1999.855", "pmRaCosDecMasYr": 3976, "pmDecMasYr": -2500},
    "wise-0855": {"referenceRaDeg": 133.795224, "referenceDecDeg": -7.245138, "referenceEpoch": "MJD 55320.4",
                  "pmRaCosDecMasYr": -8188, "pmDecMasYr": 680,
                  "positionSource": "https://arxiv.org/abs/1404.6501"},
    "wise-0855-nasa": {"referenceRaDeg": 133.79512917, "referenceDecDeg": -7.24514722,
                       "referenceEpoch": "Historical WISE position quoted by the challenge"},
    "rw-aurigae": {"referenceRaDeg": 76.95654167, "referenceDecDeg": 30.40144444, "referenceEpoch": "J2000"},
    "r-draconis": {"referenceRaDeg": 248.1676075, "referenceDecDeg": 66.754984167, "referenceEpoch": "J2000"},
}


def catalog_reference(slug):
    _, identifier, source, epoch, _, _, _, _, _ = CATALOG[slug]
    return {"id": identifier, "source": source, "epoch": epoch, **ASTROMETRY[slug]}


NOTES = {
    "barnard": "Observation-era field from the archive audit. The bright core may saturate. Motion requires a verified relative registration and target centroid.",
    "epsilon-indi-b": "Centers the brown-dwarf pair separately from Epsilon Indi A using the observation-era audit position. The two companions fall below the native pixel scale.",
    "wise-0855": "Observation-era audit position. The NASA seed lies about 2.1 arcmin east. Field playback does not establish a detection of this faint object.",
    "wise-0855-nasa": "Centered on the literal NASA seed (08h55m10.831s, −07d14m42.53s), with a wider field to retain the modern sky position.",
    "rw-aurigae": "Near-infrared imaging of an unresolved binary. Inspect masking and blending before making a photometric claim.",
    "r-draconis": "Matched near-infrared visits at a fixed catalog position. The sampling and pixel masks limit any variability conclusion.",
}


def write_atomic(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, prefix=".build-", delete=False) as temp:
        temp.write(data)
        temp_path = Path(temp.name)
    temp_path.replace(target)
    target.chmod(0o644)


def archive_manifest(slug, query, snapshot_dir, barnard_dr1):
    if snapshot_dir is None:
        return archive.discover(query)
    query = archive.bounds(query)[0]
    sources = [snapshot_dir / name for name in SNAPSHOT[slug].split()]
    if slug == "barnard":
        sources.insert(0, barnard_dr1)
    indexed = []
    collections = []
    for (_, release, doi), source in zip(archive.COLLECTIONS, sources, strict=True):
        raw = source.read_bytes()
        table, _ = archive.parse_votable(raw)
        # The historical audit used a higher row limit than the public API.
        complete = b'QUERY_STATUS" value="OVERFLOW"' not in raw
        indexed.extend(archive.index_table(table, query, release, doi))
        collections.append({"collection": "spherex_" + release.lower(), "release": release,
                            "doi": doi, "complete": complete, "successful": True, "rows": len(table)})
    return archive.make_manifest(query, indexed, complete=all(row["complete"] for row in collections),
                                 collections=collections)


def estimate(frame, wavelength, bandwidth):
    xy = frame.get("estimatedDetectorXY")
    if not xy:
        return None
    x, y = (round(value) for value in xy)
    if not (0 <= x < wavelength.shape[1] and 0 <= y < wavelength.shape[0]):
        return None
    return float(wavelength[y, x]), float(bandwidth[y, x])


def at_center_compatible(first, second, fraction=0.5):
    def central(frame):
        return frame["wavelengthUm"], frame["bandwidthUm"]
    a, wa = central(first)
    b, wb = central(second)
    if wa <= 0 or wb <= 0:
        return False
    overlap = min(a + wa / 2, b + wb / 2) - max(a - wa / 2, b - wb / 2)
    return (first["detector"] == second["detector"] and overlap >= fraction * min(wa, wb)
            and abs(a - b) <= (1 - fraction) * min(wa, wb))


def shortlist(candidates, target, width, required=(), near_target=False):
    candidates = sorted(candidates, key=lambda frame: (frame["startUtc"], frame["productId"]))
    frozen = [frame for product in required for frame in candidates if frame["obsId"] == product]
    if len(frozen) != len(required):
        raise RuntimeError("The indexed table does not include every pinned Barnard observation.")
    if not target:
        return frozen + candidates
    possible = [frame for frame in candidates if frame.get("footprintMarginPx", 0) > width / imaging.PIXEL_ARCSEC * 0.75
                and frame.get("bandwidthUm", 0) > 0 and np.isfinite(frame["wavelengthUm"])]
    if not possible:
        return frozen
    # Maximize independent visits at one band, then proximity to the desired wavelength.
    remaining = [frame for frame in possible if 0.75 <= frame["wavelengthUm"] <= 5.0]
    if frozen:
        anchors = [frozen[0]]
    else:
        near = sorted(remaining, key=lambda frame: abs(frame["wavelengthUm"] - target))
        anchors = near[:40]
    def group(anchor):
        return [frame for frame in remaining if at_center_compatible(anchor, frame, 0.62)]
    if not anchors:
        return frozen
    goal = 2 if near_target else 5
    choice = min(anchors, key=lambda anchor: (-min(goal, len({frame["visitId"] for frame in group(anchor)})),
                                               abs(anchor["wavelengthUm"] - target)))
    eligible = group(choice)
    if not frozen:
        print(f"  shortlisted {len({frame['visitId'] for frame in eligible})} visits near {choice['wavelengthUm']:.4f} µm", flush=True)
    time_order = sorted(eligible, key=lambda frame: (frame["startUtc"], frame["productId"]))
    visits = {}
    for frame in time_order:
        visits.setdefault(frame["visitId"], []).append(frame)
    rings = []
    for repeat in range(max(map(len, visits.values()), default=0)):
        rows = [sorted(group, key=lambda frame: (abs(frame["wavelengthUm"] - choice["wavelengthUm"]),
                                                -frame.get("footprintMarginPx", 0), frame["startUtc"]))[repeat]
                for group in visits.values() if repeat < len(group)]
        # Confirm earliest and latest first, then the intervening visits.
        rings.extend(rows[:1] + rows[-1:] + rows[1:-1] if len(rows) > 1 else rows)
    fixed = {frame["obsId"] for frame in frozen}
    return frozen + [frame for frame in rings if frame["obsId"] not in fixed]


def bundle(slug, args, run_budget):
    title, _, _, _, ra, dec, fov, detector, wish = CATALOG[slug]
    query = {"raDeg": ra, "decDeg": dec, "fovArcmin": fov, "start": START, "end": END}
    archive_data = archive_manifest(slug, query, args.snapshot_dir, args.barnard_dr1)
    spectral = args.calibration_dir / f"spectral_wcs_D{detector}_spx_cal-swcs-v5-2026-191.fits"
    pinned = ("2025W33_2C_0321_1", "2026W12_2A_0520_4") if slug == "barnard" else ()
    candidates = [entry for entry in archive_data["frames"] if entry["detector"] == detector]
    if spectral.exists():
        with fits.open(spectral, memmap=True) as hdul:
            wavelength = hdul["CWAVE"].data
            bandwidth = hdul["CBAND"].data
            estimated = [(frame, estimate(frame, wavelength, bandwidth)) for frame in candidates]
        for frame, sample in estimated:
            if sample is not None:
                frame["wavelengthUm"], frame["bandwidthUm"] = sample
    elif len(pinned) < args.frames:
        raise RuntimeError(f"Missing official D{detector} spectral calibration {spectral}")
    choices = shortlist(candidates, wish, fov * 60, pinned, near_target=slug.startswith("wise-"))
    print(f"{title}: {len(choices)} candidates for {archive_data['counts']['observationDates']} archive dates", flush=True)
    started = time.monotonic()
    grid, prepared, errors = archive_data["grid"], [], []
    budget = TransferBudget(min(256 * MIB, run_budget.max_bytes - run_budget.bytes), 64)
    visited = set()
    anchor = None
    for entry in choices:
        if len(prepared) >= args.frames or time.monotonic() >= args.deadline:
            break
        if entry["visitId"] in visited:
            continue
        source_path = args.cutout_dir / f"{slug}-{entry['obsId']}-D{detector}.fits"
        if slug == "barnard" and entry["obsId"] in pinned and not source_path.exists():
            source_path = args.cutout_dir / f"{entry['obsId']}.fits"
        try:
            frame_args = {"spectral_calibration": spectral if spectral.exists() else None}
            if source_path.is_file():
                raw = source_path.read_bytes()
                if len(raw) > 12 * MIB:
                    raise ValueError("saved cutout exceeds single-response limit")
                meta, arrays, _, _ = imaging.process(raw, query, entry, grid, **frame_args)
            else:
                deadline = min(time.monotonic() + 28, args.deadline)
                raw = imaging.download(query, entry, deadline, budget)
                meta, arrays, _, _ = imaging.process(raw, query, entry, grid, **frame_args)
                write_atomic(source_path, raw)
            frame = {**entry, **meta}
            if anchor and (not at_center_compatible(anchor, frame) or not imaging.compatible(anchor, frame)):
                errors.append((entry["obsId"], "INCOMPATIBLE_WAVELENGTH"))
                continue
            if anchor is None:
                anchor = frame
            prepared.append((frame, arrays))
            visited.add(entry["visitId"])
            print(f"  {frame['startUtc']} {frame['obsId']} D{detector} {frame['wavelengthUm']:.6f} µm "
                  f"valid={frame['validFraction']:.1%}", flush=True)
        except Problem as exc:
            errors.append((entry["obsId"], exc.code))
            print(f"  {entry['obsId']} {exc.code}", flush=True)
            if exc.code in {"CIRCUIT_OPEN", "DAILY_BUDGET", "LIMIT_REACHED"}:
                break
    run_budget.charge(budget.bytes)
    if len(prepared) < 2:
        raise RuntimeError(f"Only {len(prepared)} validated frame(s) for {slug}; existing manifest preserved. {errors}")
    prepared.sort(key=lambda item: item[0]["startUtc"])
    stretch, _, _ = imaging.render_frame(prepared[0][1])
    sources, included = set(), []
    for frame, arrays in prepared:
        _, png, mask = imaging.render_frame(arrays, stretch=stretch)
        version = hashlib.sha256(png + mask).hexdigest()[:24]
        frame_id = frame["frameId"]
        base = ROOT / "web" / "public" / "presets" / slug
        write_atomic(base / f"{version}.png", png)
        write_atomic(base / f"{version}-mask.png", mask)
        array_path = ROOT / "presets" / slug / f"{frame_id}.npz"
        array_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=array_path.parent, prefix=".build-", delete=False) as tmp:
            np.savez_compressed(tmp, **arrays)
            tmp_path = Path(tmp.name)
        tmp_path.replace(array_path)
        array_path.chmod(0o644)
        frame.update({"imageUrl": f"/presets/{slug}/{version}.png", "maskUrl": f"/presets/{slug}/{version}-mask.png",
                      "stretch": stretch})
        included.append(frame)
        sources.add(frame["release"])
    baseline = datetime.fromisoformat(included[-1]["startUtc"]) - datetime.fromisoformat(included[0]["startUtc"])
    notes = ["This example contains a selected, wavelength-matched subset of the archive index.", NOTES[slug]]
    manifest = {**archive_data, "seriesId": "preset-" + slug, "frames": included, "title": title,
                "counts": {**archive_data["counts"], "preparedFrames": len(included)},
                "baselineDays": baseline.total_seconds() / 86400, "warnings": notes,
                "catalogReference": catalog_reference(slug),
                "presetSlug": slug, "referenceStretch": stretch, "fixtureSelection": "Independent matched cutouts",
                "sourceReleases": sorted(sources), "downloadBytes": budget.bytes, "generationSeconds": round(time.monotonic() - started, 2)}
    body = json.dumps(ready(manifest, warnings=notes), indent=2, allow_nan=False).encode() + b"\n"
    write_atomic(ROOT / "web" / "public" / "presets" / slug / "manifest.json", body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="+", choices=tuple(CATALOG))
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--barnard-dr1", type=Path)
    parser.add_argument("--calibration-dir", type=Path, required=True)
    parser.add_argument("--cutout-dir", type=Path, default=Path("/tmp"))
    parser.add_argument("--frames", type=int, choices=range(2, 9), default=4)
    args = parser.parse_args()
    if args.snapshot_dir and not args.barnard_dr1 and "barnard" in args.slugs:
        parser.error("--barnard-dr1 is required with a historical Barnard snapshot")
    args.deadline = time.monotonic() + 30 * 60
    budget = TransferBudget(2048 * MIB, 384)
    failed = False
    for slug in args.slugs:
        try:
            bundle(slug, args, budget)
        except (OSError, RuntimeError, Problem) as exc:
            failed = True
            print(f"{slug}: {exc}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
