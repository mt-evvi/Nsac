"""Bounded IRSA cutouts and alignment to a fixed, north-up ICRS grid."""

import io
import random
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from scipy.ndimage import map_coordinates
from PIL import Image

from .config import MIB
from .contracts import Problem
from .upstream import TransferBudget, UpstreamError, fetch

PIXEL_ARCSEC = 6.15
FATAL_BITS = {
    0: "transient", 1: "overflow", 2: "sampling error", 6: "nonfunctional", 7: "dichroic",
    9: "missing data", 10: "hot pixel", 11: "cold pixel", 14: "uncorrectable pixel", 15: "nonlinear",
    17: "persistence", 19: "outlier", 20: "crosstalk", 22: "ghost", 25: "streak", 26: "bloom",
    27: "snowball", 28: "halo", 29: "satellite halo",
}
FATAL_MASK = sum(1 << k for k in FATAL_BITS)
SOURCE_MASK = 1 << 21
MIN_COVERAGE = 0.25


def grid_for(query):
    pixels = min(128, max(3, int(round(query["fovArcmin"] * 60 / PIXEL_ARCSEC))))
    scale = query["fovArcmin"] / (60 * pixels)
    return {"projection": "TAN", "frame": "ICRS", "width": pixels, "height": pixels,
            "crpix": [(pixels + 1) / 2] * 2, "crval": [query["raDeg"], query["decDeg"]],
            "cd": [[-scale, 0.0], [0.0, scale]], "pixelConvention": "zero-based centers, y increases north"}


def wcs_for(grid):
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.radesys = "ICRS"
    wcs.wcs.crpix = grid["crpix"]
    wcs.wcs.crval = grid["crval"]
    wcs.wcs.cd = grid["cd"]
    wcs.wcs.set()
    return wcs


def cutout_url(query, entry):
    original = urlsplit(entry["archiveUrl"])
    if original.query or original.fragment:
        raise Problem("UNSAFE_PRODUCT", "The archive supplied an invalid image address.")
    # A rotated square can require a larger native rectangle; never ask IRSA for the original image.
    width = min(0.17, query["fovArcmin"] / 60 * 1.23 + 2 * PIXEL_ARCSEC / 3600)
    if "cutoutSizeDeg" in query:
        width = min(0.17, query["cutoutSizeDeg"])
    parameters = urlencode({"center": f'{query["raDeg"]:.8f},{query["decDeg"]:.8f}', "size": f"{width:.8f}"})
    return urlunsplit((original.scheme, original.netloc, original.path, parameters, ""))


def download(query, entry, deadline, budget):
    url = cutout_url(query, entry)
    for retry in range(2):
        try:
            return fetch(url, limit=12 * MIB, deadline=deadline, purpose="cutout", budget=budget)
        except UpstreamError as exc:
            delay = max(random.uniform(0.12, 0.38), exc.retry_after or 0)
            if retry or exc.code not in {"UPSTREAM_UNAVAILABLE", "ARCHIVE_TIMEOUT"} or not exc.retryable or time.monotonic() + delay + 1 > deadline:
                raise
            time.sleep(delay)


def read_layers(hdul):
    for name in ("IMAGE", "FLAGS", "VARIANCE"):
        if name not in hdul:
            raise Problem("BAD_FITS", "The archive cutout is missing a required data layer.")
        hdu = hdul[name]
        shape = hdu.shape
        if len(shape) != 2 or max(shape) > 128 or min(shape) < 2:
            raise Problem("LIMIT_REACHED", "The archive cutout has unexpected image dimensions.")
    raw = np.asarray(hdul["IMAGE"].data, dtype=np.float64)
    variance = np.asarray(hdul["VARIANCE"].data, dtype=np.float64)
    flags = np.asarray(hdul["FLAGS"].data, dtype=np.uint32)
    if raw.shape != variance.shape or raw.shape != flags.shape:
        raise Problem("BAD_FITS", "The science and quality layers have different dimensions.")
    if hdul["IMAGE"].header.get("BUNIT", "").replace(" ", "") != "MJy/sr":
        raise Problem("BAD_FITS", "The image has unrecognized surface-brightness units.")
    valid = np.isfinite(raw) & np.isfinite(variance) & (variance > 0) & ((flags & FATAL_MASK) == 0)
    return raw, variance, flags, valid


def alternate_wcs(header, key, hdul=None):
    clean = header.copy()
    for name in tuple(clean):
        if name.startswith(("A_", "B_", "AP_", "BP_")):
            del clean[name]
    return WCS(clean, fobj=hdul, key=key)


def resample(raw, variance, valid, x, y):
    """Conservative bilinear registration and squared-weight variance propagation."""
    finite = np.isfinite(x) & np.isfinite(y)
    x = np.where(finite, x, -2)
    y = np.where(finite, y, -2)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    dx, dy = x - x0, y - y0
    geometric = np.zeros(x.shape, dtype=float)
    weight_valid = np.zeros(x.shape, dtype=float)
    image = np.zeros(x.shape, dtype=float)
    error = np.zeros(x.shape, dtype=float)
    for col, row, weight in ((0, 0, (1 - dx) * (1 - dy)), (1, 0, dx * (1 - dy)),
                             (0, 1, (1 - dx) * dy), (1, 1, dx * dy)):
        xi, yi = x0 + col, y0 + row
        inside = finite & (xi >= 0) & (xi < raw.shape[1]) & (yi >= 0) & (yi < raw.shape[0])
        xi = xi.clip(0, raw.shape[1] - 1)
        yi = yi.clip(0, raw.shape[0] - 1)
        good = inside & valid[yi, xi]
        geometric += weight * inside
        weight_valid += weight * good
        image += weight * np.where(good, raw[yi, xi], 0)
        error += weight**2 * np.where(good, variance[yi, xi], 0)
    keep = weight_valid > 0.999
    np.divide(image, weight_valid, out=image, where=keep)
    np.divide(error, weight_valid**2, out=error, where=keep)
    image[~keep] = np.nan
    error[~keep] = np.nan
    return image.astype(np.float32), error.astype(np.float32), geometric.astype(np.float32), keep


def png_bytes(pixels):
    memory = io.BytesIO()
    Image.fromarray(np.flipud(pixels)).save(memory, format="PNG", optimize=True)
    return memory.getvalue()


def render_frame(arrays, stretch=None):
    image, valid = arrays["image"], arrays["valid"]
    if stretch is None:
        lo, hi = np.percentile(image[valid], [10, 99.5])
        stretch = [float(lo), float(max(hi, lo + 1e-6))]
    lo, hi = stretch
    scaled = np.clip((np.where(valid, image, lo) - lo) / (hi - lo), 0, 1)
    brightness = np.arcsinh(6 * scaled) / np.arcsinh(6)
    rgba = np.empty((*image.shape, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.rint(255 * brightness[:, :, None]).astype(np.uint8)
    rgba[:, :, 3] = np.where(valid, 255, 0)
    return stretch, png_bytes(rgba), png_bytes(np.where(valid, 255, 0).astype(np.uint8))


def timestamp(header, key):
    if key not in header:
        raise Problem("BAD_FITS", "The frame does not have verified observation times.")
    return Time(header[key], scale="utc").isot + "Z"


def calibrated_passbands(path, header, cx, cy, x, y):
    native = alternate_wcs(header, "A")
    native_x, native_y = native.pixel_to_world_values(x, y)
    center_x, center_y = native.pixel_to_world_values(cx, cy)
    with fits.open(path, memmap=True) as table:
        layers = [table[key] for key in ("CWAVE", "CBAND")]
        if any(layer.shape != (2040, 2040) or layer.header.get("DETCOORD") != "sky" for layer in layers):
            raise Problem("CALIBRATION_UNAVAILABLE", "The wavelength map has unsupported detector geometry.")
        center = [map_coordinates(layer.data, [[center_y], [center_x]], order=1, cval=np.nan)[0] for layer in layers]
        projected = [map_coordinates(layer.data, [native_y, native_x], order=1, cval=np.nan) for layer in layers]
    return (*center, *projected)


def effective_psf(hdul, header, cx, cy, x_grid, y_grid, native_shape):
    """Project the nearest official ePSF zone at the exposure's actual sampling phase."""
    if "EPSF" not in hdul or min(x_grid.shape) < 9:
        return None, None
    extension = hdul["EPSF"]
    rows = extension.header.get("NAXIS2", 0)
    width = extension.header.get("NAXIS1", 0)
    if not 1 <= rows <= 500 or not 0 < width <= 20000:
        return None, None
    try:
        native_x, native_y = alternate_wcs(header, "A").pixel_to_world_values(cx, cy)
        table = extension.data
        distance = np.hypot(table["XCENTER"] - native_x, table["YCENTER"] - native_y)
        if not np.isfinite(distance).any():
            return None, None
        zone = int(np.nanargmin(distance))
        response = np.asarray(table["EPSF"][zone], dtype=float)
        sx, sy = extension.header["OVSMPX"], extension.header["OVSMPY"]
        if (response.ndim != 2 or min(response.shape) < 9 or max(response.shape) > 128
                or not 1 <= sx <= 20 or not 1 <= sy <= 20 or not np.isfinite(response).all()):
            return None, None
        row, col = np.indices(native_shape, dtype=float)
        pixels = map_coordinates(response, [(row - cy) * sy + (response.shape[0] - 1) / 2,
                                            (col - cx) * sx + (response.shape[1] - 1) / 2],
                                 order=3, mode="constant", cval=0)
        pixels = np.maximum(pixels, 0)
        # Evaluate on a regular TAN grid centered on the source, including even display sizes.
        ref_row = (x_grid.shape[0] - 1) / 2
        ref_col = (x_grid.shape[1] - 1) / 2
        ky, kx = np.indices((9, 9), dtype=float)
        rows = [ky + ref_row - 4, kx + ref_col - 4]
        x = map_coordinates(x_grid, rows, order=1, mode="nearest")
        y = map_coordinates(y_grid, rows, order=1, mode="nearest")
        aligned, _, coverage, _ = resample(pixels, np.ones(native_shape), np.ones(native_shape, dtype=bool), x, y)
        if not np.isfinite(aligned).all() or np.min(coverage) < 0.999:
            return None, None
        total = float(aligned.sum())
        if total <= 0 or not 0.04 <= aligned[4, 4] / total <= 0.85:
            return None, None
        stamp = (aligned / total).astype(np.float32)
        return stamp, {"extension": "EPSF", "zone": zone, "nativeOversampling": [sx, sy],
                       "method": "Local official ePSF projected through the same native-to-TAN resampling"}
    except (KeyError, TypeError, ValueError, IndexError):
        return None, None


def process(payload, query, entry, grid, stretch=None, spectral_calibration=None):
    try:
        with fits.open(io.BytesIO(payload), memmap=False) as hdul:
            header = hdul["IMAGE"].header
            raw, variance, flags, good = read_layers(hdul)
            start, end = timestamp(header, "DATE-BEG"), timestamp(header, "DATE-END")
            if Time(end.rstrip("Z"), scale="utc") < Time(start.rstrip("Z"), scale="utc"):
                raise Problem("BAD_FITS", "The FITS observation end precedes its start.")
            if "startUtc" in entry and abs((Time(start.rstrip("Z")) - Time(entry["startUtc"].rstrip("Z"))).sec) > 240:
                raise Problem("BAD_FITS", "The FITS observation time disagrees with the archive index.")
            try:
                detector = int(header["DETECTOR"])
            except (KeyError, TypeError, ValueError) as exc:
                raise Problem("BAD_FITS", "The frame does not identify a valid detector.") from exc
            if not 1 <= detector <= 6 or entry.get("detector", detector) != detector:
                raise Problem("BAD_FITS", "The FITS detector disagrees with the archive index.")
            sky_wcs = WCS(header).celestial
            ref = SkyCoord(query["raDeg"], query["decDeg"], unit="deg", frame="icrs")
            cx, cy = sky_wcs.world_to_pixel(ref)
            if not -0.5 <= cx < raw.shape[1] - 0.5 or not -0.5 <= cy < raw.shape[0] - 0.5:
                raise Problem("LOW_OVERLAP", "The requested center falls outside this exposure.")
            rows, cols = np.indices((grid["height"], grid["width"]), dtype=float)
            sky = wcs_for(grid).pixel_to_world(cols, rows)
            x, y = sky_wcs.world_to_pixel(sky)
            image, var, coverage, valid = resample(raw, variance, good, x, y)
            calibration = "wcs-wave-preview"
            if spectral_calibration is not None:
                wave, band, wave_grid, band_grid = calibrated_passbands(spectral_calibration, header, cx, cy, x, y)
                calibration = "cwave-cband"
            elif "WCS-WAVE" in hdul and hdul["WCS-WAVE"].header["NAXIS1"] * hdul["WCS-WAVE"].header["NAXIS2"] <= 16_384:
                wave_wcs = alternate_wcs(header, "W", hdul)
                wave, band = wave_wcs.pixel_to_world_values(cx, cy)
                wave_grid, band_grid = wave_wcs.pixel_to_world_values(x, y)
            else:
                wave, band = np.nan, np.nan
                wave_grid, band_grid = np.full_like(image, np.nan), np.full_like(image, np.nan)
            mid = timestamp(header, "DATE-AVG") if "DATE-AVG" in header else start
            psf, psf_metadata = effective_psf(hdul, header, cx, cy, x, y, raw.shape)
    except (KeyError, ValueError, OSError) as exc:
        raise Problem("BAD_FITS", "The archive cutout is incomplete or has invalid FITS headers.") from exc
    footprint = float(np.mean(coverage >= 0.999))
    valid_fraction = float(np.mean(valid))
    if footprint < MIN_COVERAGE or valid_fraction < 0.05:
        raise Problem("LOW_OVERLAP", "This exposure has too little unmasked sky coverage.")
    wave = float(wave) if np.isfinite(wave) and wave > 0 else None
    band = float(band) if np.isfinite(band) and band > 0 else None
    if "wavelengthUm" in query and (wave is None or band is None or abs(query["wavelengthUm"] - wave) > band / 2):
        raise Problem("INCOMPATIBLE_WAVELENGTH", "This exposure does not cover the requested wavelength.")
    arrays = {"image": image, "variance": var, "coverage": coverage, "valid": valid,
              "wavelength": np.where(coverage > 0, wave_grid, np.nan).astype(np.float32),
              "bandwidth": np.where(coverage > 0, band_grid, np.nan).astype(np.float32)}
    stretch, png, mask = render_frame(arrays, stretch)
    notes = [name for bit, name in FATAL_BITS.items() if np.any(flags & (1 << bit))]
    warnings = ["Some pixels are masked or outside the exposure."] if valid_fraction < 0.99 else []
    if np.any(flags & ((1 << 1) | (1 << 15) | (1 << 26))):
        warnings.append("Saturation or associated artifacts are present in the cutout.")
    metadata = {"startUtc": start, "endUtc": end, "midUtc": mid, "slotKey": start[:10],
                "state": "prepared", "wavelengthUm": wave, "bandwidthUm": band, "wavelengthCalibration": calibration,
                "detector": detector, "units": "MJy/sr", "stretch": stretch, "coverageFraction": footprint,
                "validFraction": valid_fraction, "flags": notes, "warnings": warnings,
                "processingVersion": "tan-bilinear-v1", "psfFwhmArcsec": header.get("PSF_FWHM"),
                "archiveDoi": {"DR1": "10.26131/IRSA678", "QR3": "10.26131/IRSA662"}.get(entry["release"].upper()),
                "transferBytes": len(payload)}
    if spectral_calibration is not None:
        metadata["wavelengthCalibrationId"] = Path(spectral_calibration).name
    if psf is not None:
        arrays["effectivePsf"] = psf
        metadata["epsfModel"] = psf_metadata
    return metadata, arrays, png, mask


def prepare(query, entry, grid, *, budget=None, deadline=None, stretch=None, spectral_calibration=None):
    deadline = deadline if deadline is not None else time.monotonic() + 30
    budget = budget if budget is not None else TransferBudget(64 * MIB, 6)
    payload = download(query, entry, deadline, budget)
    return process(payload, query, entry, grid, stretch, spectral_calibration)


def compatible(metadata_a, metadata_b):
    wave_a, wave_b = metadata_a.get("wavelengthUm"), metadata_b.get("wavelengthUm")
    band_a, band_b = metadata_a.get("bandwidthUm"), metadata_b.get("bandwidthUm")
    return (metadata_a.get("detector") == metadata_b.get("detector") and all(v is not None for v in (wave_a, wave_b, band_a, band_b))
            and abs(wave_b - wave_a) <= min(band_a, band_b) / 2)


def coadd(manifest, candidate, store, result_id):
    """Use one visit and a short span with pixel-wise checked passband overlap."""
    series_id = manifest["seriesId"]
    query = manifest["query"]
    grid = manifest["grid"]
    anchor_time = Time(candidate["startUtc"].rstrip("Z"), scale="utc")
    choices = [frame for frame in manifest["frames"] if frame["frameId"] != candidate["frameId"]
               and frame.get("visitId") == candidate.get("visitId") and frame["detector"] == candidate["detector"]
               and abs((Time(frame["startUtc"].rstrip("Z"), scale="utc") - anchor_time).sec) <= 3600]
    if not choices or not candidate.get("visitId"):
        raise Problem("NO_COMPARABLE_FRAMES", "This visit has no other nearby exposure from the selected detector.", 409)
    deadline = time.monotonic() + 30
    budget = TransferBudget(64 * MIB, 6)

    def resolve(frame):
        kept = store.prepared(series_id, frame["frameId"]) or frame
        if kept.get("imageUrl"):
            try:
                return kept, store.load_arrays(series_id, kept)
            except Problem:
                pass
        metadata, arrays, _, _ = prepare(query, frame, grid, budget=budget, deadline=deadline)
        return {**frame, **metadata}, arrays

    anchor, first = resolve(candidate)
    valid = first["valid"] & (first["variance"] > 0)
    weight = np.divide(1, first["variance"], out=np.zeros_like(first["variance"]), where=valid)
    sum_weight = weight.copy()
    weighted = weight * np.where(valid, first["image"], 0)
    used = np.where(valid, 1, 0)
    contributors = [anchor]
    for frame in choices[:5]:
        if len(contributors) >= 4 or time.monotonic() > deadline - 1 or budget.attempts >= budget.max_attempts:
            break
        nominal = frame.get("wavelengthUm")
        if nominal is not None and anchor.get("wavelengthUm") and abs(nominal - anchor["wavelengthUm"]) > 0.12:
            continue
        try:
            metadata, arrays = resolve(frame)
        except Problem:
            continue
        if not compatible(anchor, metadata):
            continue
        narrow = np.minimum(first["bandwidth"], arrays["bandwidth"])
        common = valid & arrays["valid"] & (narrow > 0) & (np.abs(first["wavelength"] - arrays["wavelength"]) <= narrow / 2)
        if np.mean(common) < 0.6:
            continue
        weight = np.divide(1, arrays["variance"], out=np.zeros_like(sum_weight), where=common)
        sum_weight += weight
        weighted += weight * np.where(common, arrays["image"], 0)
        used += common
        contributors.append(metadata)
    if len(contributors) < 2:
        raise Problem("NO_COMPARABLE_FRAMES", "No second exposure in this visit passed the coadd wavelength and coverage checks.", 409)
    keep = used > 1
    result = dict(first, image=np.divide(weighted, sum_weight, out=np.full_like(weighted, np.nan), where=keep),
                  variance=np.divide(1, sum_weight, out=np.full_like(sum_weight, np.nan), where=keep), valid=keep)
    result.pop("effectivePsf", None)
    stretch, png, mask = render_frame(result, anchor.get("stretch"))
    data = {**anchor, "frameId": result_id, "representation": "coadd", "stretch": stretch,
            "startUtc": min(frame["startUtc"] for frame in contributors), "endUtc": max(frame["endUtc"] for frame in contributors),
            "contributors": [{key: frame[key] for key in ("productId", "archiveUrl", "startUtc", "endUtc")} for frame in contributors],
            "validFraction": float(np.mean(keep)), "warnings": ["Within-visit inverse-variance mean. Pixels require at least two contributors."]}
    data.pop("epsfModel", None)
    return data, result, png, mask
