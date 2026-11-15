"""Bounded native-pixel spectroscopy using versioned IRSA calibration products."""

import io
import math
import time
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from scipy.ndimage import map_coordinates

from . import imaging
from .config import MIB
from .contracts import Problem
from .store import atomic_write
from .upstream import IRSA_CLOUD, TransferBudget, fetch

CALIBRATIONS = {
    "spectral_wcs": ("cal-swcs-v5-2026-191", 37 * MIB, ("CWAVE", "CBAND")),
    "solid_angle_pixel_map": ("cal-sapm-v3-2026-191", 20 * MIB, ("IMAGE",)),
}
ARCSEC_TO_RAD = math.pi / (180 * 3600)
REFERENCE = "https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html"


def calibration_paths(release, detector, cache):
    if release not in {"dr1", "qr3"} or detector not in range(1, 7):
        raise Problem("CALIBRATION_UNAVAILABLE", "No verified calibration is configured for this release and detector.")
    for kind, (version, limit, extensions) in CALIBRATIONS.items():
        name = f"{kind}_D{detector}_spx_{version}.fits"
        path = Path(cache, "calibrations", release, name)
        url = f"https://{IRSA_CLOUD}/{release}/{kind}/{version}/{detector}/{name}"
        yield path, url, limit, extensions


def calibration_values(release, detector, cache, native_x, native_y, deadline, budget):
    results = []
    identifiers = []
    for path, url, limit, extensions in calibration_paths(release, detector, cache):
        if not path.exists():
            if budget is None:
                raise Problem("CALIBRATION_UNAVAILABLE", "The calibrated detector maps are not cached. Try an extended spectrum.")
            payload = fetch(url, limit=limit, deadline=deadline, purpose="calibration", budget=budget)
            atomic_write(path, payload)
        with fits.open(path, memmap=True) as hdul:
            for extension in extensions:
                hdu = hdul[extension]
                if hdu.shape != (2040, 2040) or hdu.header.get("DETCOORD", "sky") != "sky":
                    raise Problem("CALIBRATION_UNAVAILABLE", "The detector map geometry is unsupported.")
                if extension == "IMAGE":
                    ix, iy = native_x.astype(int), native_y.astype(int)
                    if np.any(ix < 0) or np.any(iy < 0) or np.any(ix >= 2040) or np.any(iy >= 2040):
                        raise Problem("LOW_OVERLAP", "The source aperture intersects an uncalibrated detector edge.")
                    value = np.asarray(hdu.data[iy, ix], dtype=float)
                else:
                    x, y = float(native_x[0]), float(native_y[0])
                    xi, yi = int(math.floor(x)), int(math.floor(y))
                    if not 0 <= xi < 2039 or not 0 <= yi < 2039:
                        raise Problem("LOW_OVERLAP", "The selected source falls outside the spectral-calibration grid.")
                    dx, dy = x - xi, y - yi
                    cell = np.asarray(hdu.data[yi:yi + 2, xi:xi + 2], dtype=float)
                    value = (1 - dy) * ((1 - dx) * cell[0, 0] + dx * cell[0, 1]) + dy * ((1 - dx) * cell[1, 0] + dx * cell[1, 1])
                results.append(value)
        identifiers.append(path.name)
    return results, identifiers


def source_photometry(hdul, frame, source, method, store, deadline, calibration_budget):
    raw, variance, flags, valid = imaging.read_layers(hdul)
    header = hdul["IMAGE"].header
    x, y = WCS(header).celestial.world_to_pixel_values(source["raDeg"], source["decDeg"])
    if not 7 <= x < raw.shape[1] - 7 or not 7 <= y < raw.shape[0] - 7:
        raise Problem("LOW_OVERLAP", "The source and local background do not fit within the cutout.")
    ypix, xpix = np.indices(raw.shape, dtype=float)
    distance = np.hypot(xpix - x, ypix - y)
    aperture = distance <= 3.5
    annulus = (distance >= 5) & (distance <= 7) & valid
    # A crowded mask may mark every background pixel as a known source. In that case reject the fit.
    annulus &= (flags & imaging.SOURCE_MASK) == 0
    if np.count_nonzero(annulus) < 12 or np.any(~valid[aperture]):
        raise Problem("MASKED_SOURCE", "The source aperture or background contains too few unflagged pixels.")
    native = imaging.alternate_wcs(header, "A")
    nx, ny = native.pixel_to_world_values(np.r_[x, xpix[aperture]], np.r_[y, ypix[aperture]])
    detector = int(header["DETECTOR"])
    (wave, band, area), ids = calibration_values(frame["release"].lower(), detector, store.root, nx, ny,
                                                  deadline, calibration_budget)
    area = area[1:] * ARCSEC_TO_RAD**2 * 1e12  # MJy/sr to microJy per detector pixel
    if not np.isfinite(area).all() or not np.isfinite(wave + band) or wave <= 0 or band <= 0 or np.any(area <= 0):
        raise Problem("CALIBRATION_UNAVAILABLE", "The calibration has gaps at the selected detector location.")
    sky = raw[annulus]
    center = np.median(sky)
    scatter = 1.4826 * np.median(np.abs(sky - center))
    use = np.abs(sky - center) <= max(3 * scatter, 1e-12)
    if np.count_nonzero(use) < 12:
        raise Problem("MASKED_SOURCE", "The local background has insufficient clean support.")
    weights = 1 / variance[annulus][use]
    background = np.average(sky[use], weights=weights)
    bg_variance = max(1 / np.sum(weights), scatter**2 / len(weights))
    values = raw[aperture] - background
    noise = variance[aperture]
    fit_quality = None
    if method == "aperture":
        flux = np.sum(area * values)
        error = np.sqrt(np.sum(area**2 * noise) + bg_variance * np.sum(area)**2)
        provenance = "3.5 pixel aperture, 5–7 pixel clipped local annulus; no aperture correction"
    else:
        if "EPSF" not in hdul or hdul["EPSF"].header.get("NAXIS2", 0) > 500:
            raise Problem("CALIBRATION_UNAVAILABLE", "A supported ePSF is unavailable for this image.")
        hdu = hdul["EPSF"]
        data = hdu.data
        zone = np.argmin(np.hypot(data["XCENTER"] - nx[0], data["YCENTER"] - ny[0]))
        epsf = np.asarray(data["EPSF"][zone], dtype=float)
        sy, sx = hdu.header["OVSMPY"], hdu.header["OVSMPX"]
        yy = (ypix[aperture] - y) * sy + (epsf.shape[0] - 1) / 2
        xx = (xpix[aperture] - x) * sx + (epsf.shape[1] - 1) / 2
        response = np.maximum(map_coordinates(epsf, [yy, xx], order=3, mode="constant", cval=0), 0)
        total = np.sum(response)
        if not np.isfinite(total) or total <= 0:
            raise Problem("CALIBRATION_UNAVAILABLE", "The archived ePSF has no usable response at this pixel phase.")
        template = (response / total) / area
        kernel = (template / noise) / np.sum(template**2 / noise)
        flux = np.sum(kernel * values)
        error = np.sqrt(np.sum(kernel**2 * noise) + bg_variance * np.sum(kernel)**2)
        fit_quality = float(np.mean(np.abs(values - template * flux) / np.sqrt(noise)))
        if not np.isfinite(fit_quality) or fit_quality > 4:
            raise Problem("POOR_FIT", "The archived point-spread function gives a poor fit at the selected position.")
        provenance = "Native ePSF fit at fixed source position, 5–7 pixel clipped local annulus"
        ids.append(f"{frame['productId']}#EPSF[{zone}]")
    return {"wavelengthUm": float(wave), "bandwidthUm": float(band), "flux": float(flux), "error": float(error),
            "fitQuality": fit_quality, "units": "µJy", "sampleStatus": "measured", "method": provenance,
            "calibrationIds": ids, "startUtc": imaging.timestamp(header, "DATE-BEG"),
            "productId": frame["productId"], "frameId": frame["frameId"], "archiveUrl": frame["archiveUrl"]}


def extract(manifest, options, linked, store):
    grid = manifest["grid"]
    wcs = imaging.wcs_for(grid)
    selection = options.get("selectedSkyPosition")
    per_frame = {}
    if linked:
        if linked.get("ambiguous"):
            raise Problem("AMBIGUOUS_SOURCE", "Choose an unambiguous source or a fixed sky position.")
        for mark in linked["marks"]:
            if mark.get("pixel"):
                sky = wcs.pixel_to_world(mark["pixel"]["x"], mark["pixel"]["y"])
                per_frame[mark["frameId"]] = {"raDeg": float(sky.ra.deg), "decDeg": float(sky.dec.deg)}
    else:
        sky = SkyCoord(selection["raDeg"], selection["decDeg"], unit="deg", frame="icrs")
        x, y = wcs.world_to_pixel(sky)
        if not -0.5 <= x < grid["width"] - 0.5 or not -0.5 <= y < grid["height"] - 0.5:
            raise Problem("OUTSIDE_FIELD", "Choose a source inside the selected field.")
    mode = options["mode"]
    if mode == "coadded_cube":
        from .cubes import coadded_spectrum

        return coadded_spectrum(selection, options.get("wavelengthRange"))
    cap = 32 if mode == "extended" else 8
    deadline = time.monotonic() + (90 if mode == "extended" else 30)
    bytes_limit = (128 if mode == "extended" else 64) * MIB
    budget = TransferBudget(bytes_limit, cap * 2)
    cold = TransferBudget(192 * MIB, 12) if mode == "extended" else None
    date_window = options.get("timeRange") or {"start": manifest["query"]["start"], "end": manifest["query"]["end"]}
    lo, hi = options.get("wavelengthRange", [0.7, 5.1])
    entries = []
    for frame in manifest["frames"]:
        if not date_window["start"] <= frame["startUtc"][:10] <= date_window["end"]:
            continue
        if linked and frame["frameId"] not in per_frame:
            continue
        wave = frame.get("wavelengthUm")
        if wave is not None and not lo <= wave <= hi:
            continue
        if frame.get("archiveUrl"):
            entries.append(frame)
    entries.sort(key=lambda frame: (frame.get("detector", 0), frame["startUtc"], frame["frameId"]))
    # Round robin by detector retains broad wavelength coverage under the sample budget.
    groups = [[frame for frame in entries if frame["detector"] == i] for i in range(1, 7)]
    ordered = [group[i] for i in range(max(map(len, groups), default=0)) for group in groups if i < len(group)]
    samples = []
    for frame in ordered[:cap]:
        if time.monotonic() > deadline - 1 or budget.bytes >= bytes_limit:
            break
        source = per_frame.get(frame["frameId"], selection)
        query = dict(source, fovArcmin=2.2)
        try:
            if cold is None and any(not path.is_file() for path, *_ in calibration_paths(
                    frame["release"].lower(), frame["detector"], store.root)):
                raise Problem("CALIBRATION_UNAVAILABLE", "Try an extended spectrum to load the detector calibration.")
            payload = imaging.download(query, frame, deadline, budget)
            with fits.open(io.BytesIO(payload), memmap=False) as hdul:
                measured = source_photometry(hdul, frame, source, options["method"], store, deadline, cold)
            if lo <= measured["wavelengthUm"] <= hi:
                samples.append(measured)
        except (Problem, ValueError, OSError, KeyError) as exc:
            message = exc.message if isinstance(exc, Problem) else "The exposure could not be calibrated."
            samples.append({"startUtc": frame["startUtc"], "wavelengthUm": frame.get("wavelengthUm"),
                            "productId": frame["productId"], "sampleStatus": "missing", "reason": message})
    samples.sort(key=lambda sample: (sample["wavelengthUm"] is None, sample["wavelengthUm"] or 0, sample["startUtc"]))
    partial = not samples or len(entries) > len(samples) or any(s["sampleStatus"] == "missing" for s in samples)
    return {"mode": mode, "method": options["method"], "sources": 1, "samples": samples, "partial": partial,
            "units": "µJy", "referenceUrl": REFERENCE, "timeRange": date_window, "transferBytes": budget.bytes,
            "warnings": ["This is an exposure-by-exposure extract. Samples may be from different visits and have not been validated against IRSA forced photometry."] +
                        (["Coverage, masking, calibration availability or job limits left gaps in the spectrum."] if partial else [])}
