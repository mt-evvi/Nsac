"""Bounded comparisons and source measurements on prepared science arrays."""

from datetime import datetime, timedelta
from math import hypot, sqrt

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from PIL import Image
from scipy.ndimage import binary_erosion, convolve, distance_transform_edt, gaussian_filter, maximum_filter
from scipy.spatial import cKDTree

from .imaging import wcs_for
from .store import content_key

MIN_OVERLAP = 0.60
MAX_REFERENCE_RESIDUAL = 0.30
MAX_PROFILE_DIFFERENCE = 0.15
REGISTRATION_FLOOR_PX = 0.15
MANUAL_FLOOR_PX = 0.50
SOURCE_LIMIT = 50
CENTROID_MATCH_PX = 0.001
MAX_ASSOCIATION_SPEED_PX_PER_DAY = 0.12
MAX_ASSOCIATION_RADIUS_PX = 8.0
ASSOCIATION_SIGMA = 3.0


class AnalysisError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def frame_time(metadata):
    start = datetime.fromisoformat(metadata["startUtc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(metadata.get("endUtc", metadata["startUtc"]).replace("Z", "+00:00"))
    return start + (end - start) / 2


def _utc(time):
    return time.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sigma(values):
    if not len(values):
        return 0.0
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


def _valid(frame):
    image, variance = frame["image"], frame["variance"]
    return frame["valid"] & np.isfinite(image) & np.isfinite(variance) & (variance > 0)


def _passes(a_wave, a_width, b_wave, b_width):
    narrower = np.minimum(a_width, b_width)
    overlap = np.minimum(a_wave + a_width / 2, b_wave + b_width / 2)
    overlap -= np.maximum(a_wave - a_width / 2, b_wave - b_width / 2)
    return (narrower > 0) & (abs(a_wave - b_wave) <= narrower / 2) & (overlap >= narrower / 2)


def _passband(frame, key, field):
    if key in frame:
        return np.asarray(frame[key], dtype=float)
    return np.asarray(frame["metadata"].get(field) or np.nan, dtype=float)


def _compatible_pair(a, b):
    first, second = a["metadata"], b["metadata"]
    if first["frameId"] == second["frameId"] or first["visitId"] == second["visitId"]:
        raise AnalysisError("SAME_VISIT", "Choose two independent visits for comparison.")
    if first["grid"] != second["grid"]:
        raise AnalysisError("INCOMPATIBLE_GRID", "The two frames do not share a registered grid.")
    first_wave = first.get("wavelengthUm")
    second_wave = second.get("wavelengthUm")
    first_width = first.get("bandwidthUm")
    second_width = second.get("bandwidthUm")
    if first["detector"] != second["detector"] or not (
        first_wave and second_wave and first_width and second_width
        and _passes(first_wave, first_width, second_wave, second_width)
    ):
        raise AnalysisError("INCOMPATIBLE_WAVELENGTH", "Choose visits with overlapping passbands on the same detector.")
    geometric = _valid(a) & _valid(b)
    local = _passes(_passband(a, "wavelength", "wavelengthUm"), _passband(a, "bandwidth", "bandwidthUm"),
                    _passband(b, "wavelength", "wavelengthUm"), _passband(b, "bandwidth", "bandwidthUm"))
    valid = geometric & local
    if valid.mean() < MIN_OVERLAP:
        raise AnalysisError("LOW_OVERLAP", "Less than 60% of the field has common valid, wavelength-matched pixels.")
    calibrated = all(
        frame["metadata"].get("wavelengthCalibration") in {"cwave-cband", "synthetic"}
        and "wavelength" in frame and "bandwidth" in frame
        for frame in (a, b)
    )
    return valid, {
        "frameAUm": first_wave, "frameBUm": second_wave, "frameABandwidthUm": first_width,
        "frameBBandwidthUm": second_width, "calibrated": calibrated,
        "localMismatchFraction": float((geometric & ~local).mean()),
        "method": "Per-pixel passband intersection, minimum half the narrower width.",
    }


def _native_sources(frame, limit, region=None, *, correlated=False):
    image, variance = frame["image"], frame["variance"]
    valid = _valid(frame)
    if np.count_nonzero(valid) < 25:
        return []
    background = float(np.median(image[valid]))
    filled = np.where(valid, image - background, 0)
    filtered = gaussian_filter(filled, 0.9)
    noise = max(_sigma(filtered[valid]), np.median(np.sqrt(variance[valid])) * 0.32)
    mask_distance = distance_transform_edt(np.pad(valid, 1))[1:-1, 1:-1]
    peaks = (filtered == maximum_filter(filtered, size=5)) & (filtered > 5 * noise) & (mask_distance > 3)
    ys, xs = np.where(peaks)
    eligible = ((y, x) for y, x in zip(ys, xs) if _in_region(x, y, region))
    by_strength = sorted(eligible, key=lambda p: (-filtered[p], p[0], p[1]))[:limit * 3]
    sources = []
    oy, ox = np.mgrid[-3:4, -3:4]
    radius = np.hypot(ox, oy)
    core = radius <= 2.9
    annulus = radius >= 3
    for y, x in by_strength:
        sl = np.s_[y - 3:y + 4, x - 3:x + 4]
        local_valid = valid[sl]
        sky = local_valid & annulus
        signal = local_valid & core
        if signal.sum() < 20 or sky.sum() < 12:
            continue
        patch = image[sl]
        sky_values = patch[sky]
        level = float(np.median(sky_values))
        local_noise = max(_sigma(sky_values), float(np.median(np.sqrt(variance[sl][sky]))))
        flux = float(np.sum(patch[signal] - level))
        signal_variance = variance[sl][signal]
        sky_error = signal.sum() * local_noise
        if correlated:
            # Add the standard deviations to bound covariance across the aperture and sky annulus.
            flux_error = float(np.sqrt(signal_variance).sum() + sky_error)
        else:
            flux_error = sqrt(float(signal_variance.sum()) + sky_error**2 / sky.sum())
        snr = flux / flux_error
        if snr < 5:
            continue
        weights = np.clip(patch[signal] - level - 0.5 * local_noise, 0, None)
        if weights.sum() <= 0:
            continue
        dx = float(np.average(ox[signal], weights=weights))
        dy = float(np.average(oy[signal], weights=weights))
        ex, ey = ox[signal] - dx, oy[signal] - dy
        shape = np.cov([ex, ey], aweights=weights, bias=True)
        minor, major = np.linalg.eigvalsh(shape)
        if minor < 0.38 or major > 2.8 or major / minor > 3.2 or hypot(dx, dy) > 1.25:
            continue
        width = sqrt((minor + major) / 2)
        cx, cy = float(x + dx), float(y + dy)
        if not _in_region(cx, cy, region):
            continue
        sigma = max(0.08, width / snr)
        sources.append({
            "frameId": frame["metadata"]["frameId"], "pixel": {"x": cx, "y": cy}, "sigmaPx": sigma,
            "covariancePx2": [[sigma * sigma, 0.0], [0.0, sigma * sigma]], "widthPx": width,
            "flux": flux, "fluxError": flux_error, "fluxUnit": "MJy/sr pixel sum",
            "snr": float(snr), "maskDistancePx": float(mask_distance[y, x]),
            "method": "aperture moments on the aligned grid",
        })
        if len(sources) >= limit:
            break
    return sources


def _pixels(sources):
    return np.asarray([(s["pixel"]["x"], s["pixel"]["y"]) for s in sources], dtype=float).reshape(-1, 2)


def _references(a_sources, b_sources):
    a_points = _pixels(a_sources)
    b_points = _pixels(b_sources)
    if not len(a_points) or not len(b_points):
        return []
    dist, nearest_b = cKDTree(b_points).query(a_points, distance_upper_bound=0.75)
    _, nearest_a = cKDTree(a_points).query(b_points, distance_upper_bound=0.75)
    references = []
    for i, j in enumerate(nearest_b):
        if not np.isfinite(dist[i]) or nearest_a[j] != i:
            continue
        first, second = a_sources[i], b_sources[j]
        ratio = second["flux"] / first["flux"]
        if min(first["snr"], second["snr"]) >= 12 and 0.80 <= ratio <= 1.25:
            references.append((first, second))
    return references


def _diagnostics(references):
    if references:
        first, second = zip(*references)
        offsets = _pixels(second) - _pixels(first)
        scales = np.array([b["flux"] / a["flux"] for a, b in references])
        widths = np.array([b["widthPx"] / a["widthPx"] for a, b in references])
        median_offset = np.median(offsets, axis=0)
        median_distance = float(np.median(np.linalg.norm(offsets, axis=1)))
        scatter = float(np.median(np.linalg.norm(offsets - median_offset, axis=1)))
        log_scales = np.log(scales)
        log_widths = np.log(widths)
        scale = float(np.exp(np.median(log_scales)))
        width_ratio = float(np.exp(np.median(log_widths)))
        scale_scatter = _sigma(log_scales)
        width_scatter = _sigma(log_widths)
    else:
        median_offset = median_distance = scatter = scale = width_ratio = scale_scatter = width_scatter = None
    registration_ok = len(references) >= 3 and median_distance < MAX_REFERENCE_RESIDUAL
    matching_ok = (registration_ok and 0.90 <= scale <= 1.11 and 0.90 <= width_ratio <= 1.11
                   and scale_scatter <= 0.07 and width_scatter <= 0.07)
    return {
        "referenceCount": len(references), "medianOffsetPx": median_offset.tolist() if references else None,
        "medianResidualPx": median_distance, "medianCenteredResidualPx": scatter,
        "relativeScaleBoverA": scale, "relativeWidthBoverA": width_ratio,
        "relativeScaleLogScatter": scale_scatter, "relativeWidthLogScatter": width_scatter,
        "registrationVerified": registration_ok, "relativeScaleAndWidthVerified": matching_ok,
        "method": "Common TAN grid, mutual stable-source centroid checks",
    }


def _effective_psf(frame):
    psf = np.asarray(frame.get("effectivePsf"), dtype=float)
    if psf.shape != (9, 9) or not np.isfinite(psf).all() or np.any(psf < 0):
        return None
    if not np.isclose(psf.sum(), 1, rtol=0, atol=1e-5):
        return None
    yy, xx = np.mgrid[-4:5, -4:5]
    centroid = np.hypot(np.sum(psf * xx), np.sum(psf * yy))
    radius = sqrt(float(np.sum(psf * (xx**2 + yy**2))))
    if centroid > 0.30 or not 0.35 <= radius <= 3.0:
        return None
    return psf / psf.sum()


def _convolved(frame, kernel, valid, overlap):
    image = convolve(np.where(valid, frame["image"], 0.0).astype(float), kernel, mode="constant")
    variance = convolve(np.where(valid, frame["variance"], 0.0).astype(float), kernel**2, mode="constant")
    return {**frame, "image": image, "variance": variance, "valid": overlap}


def _profile_differences(a_image, b_image, valid, references):
    yy, xx = np.mgrid[-3:4, -3:4]
    annulus = np.hypot(xx, yy) >= 3
    differences = []
    for first, second in references:
        x, y = np.rint(np.mean(_pixels([first, second]), axis=0)).astype(int)
        if not (3 <= x < valid.shape[1] - 3 and 3 <= y < valid.shape[0] - 3):
            continue
        stamp = np.s_[y - 3:y + 4, x - 3:x + 4]
        if not valid[stamp].all():
            continue
        a = np.maximum(a_image[stamp] - np.median(a_image[stamp][annulus]), 0)
        b = np.maximum(b_image[stamp] - np.median(b_image[stamp][annulus]), 0)
        if a.sum() > 0 and b.sum() > 0:
            differences.append(float(np.abs(a / a.sum() - b / b.sum()).sum() / 2))
    return differences


def _sky_pixels(a_image, b_image, valid, sources, exclusion_radius):
    sky = valid.copy()
    yy, xx = np.indices(sky.shape)
    for source in sources:
        sky &= (xx - source["pixel"]["x"]) ** 2 + (yy - source["pixel"]["y"]) ** 2 > exclusion_radius**2
    if sky.sum() < 25:
        for image in (a_image, b_image):
            sky &= image < np.percentile(image[valid], 75)
    return sky


def _cross_convolved(a, b, valid, registration):
    a_psf, b_psf = _effective_psf(a), _effective_psf(b)
    details = {"preMatchReferenceCount": registration["referenceCount"],
               "preMatchMedianResidualPx": registration["medianResidualPx"]}
    if a_psf is None or b_psf is None:
        return None, {**details, "psfMatchingStatus": "MISSING_VALID_KERNEL"}
    if not registration["registrationVerified"]:
        return None, {**details, "psfMatchingStatus": "UNVERIFIED_REGISTRATION"}

    # Every pixel in either kernel must be covered, unflagged and locally passband compatible.
    support = (a_psf > 0) | (b_psf > 0)
    # Convolution reflects its kernel around the output pixel.
    overlap = valid & binary_erosion(valid, structure=np.flip(support), border_value=0)
    details["postMatchValidFraction"] = float(overlap.mean())
    if details["postMatchValidFraction"] < MIN_OVERLAP:
        return None, {**details, "psfMatchingStatus": "LOW_KERNEL_SUPPORT"}
    first = _convolved(a, b_psf, valid, overlap)
    second = _convolved(b, a_psf, valid, overlap)
    first_sources = _native_sources(first, 50)
    second_sources = _native_sources(second, 50)
    references = _references(first_sources, second_sources)
    diagnostics = _diagnostics(references)
    profiles = _profile_differences(first["image"], second["image"], overlap, references)
    median_profile = float(np.median(profiles)) if profiles else None
    details.update(postMatchReferenceCount=diagnostics["referenceCount"],
                   postMatchMedianResidualPx=diagnostics["medianResidualPx"],
                   psfProfileReferenceCount=len(profiles), psfProfileMedianDifference=median_profile)
    if not diagnostics["relativeScaleAndWidthVerified"] or len(profiles) < 3 or median_profile > MAX_PROFILE_DIFFERENCE:
        return None, {**details, "psfMatchingStatus": "UNVERIFIED_KERNEL_MATCH"}
    sky = _sky_pixels(first["image"], second["image"], overlap, first_sources + second_sources, 5)
    if sky.sum() < 25:
        return None, {**details, "psfMatchingStatus": "INSUFFICIENT_SKY"}
    diagnostics.update(details, epsfValidated=True, psfMatchingStatus="MATCHED",
                       method="Cross-convolved local ePSFs, checked against stable reference profiles")
    return (first, second, overlap, sky), diagnostics


_PSF_WARNINGS = {
    "MISSING_VALID_KERNEL": "A valid archived effective PSF is missing from one or both frames.",
    "UNVERIFIED_REGISTRATION": "Matching effective PSFs requires vetted registration before convolution.",
    "LOW_KERNEL_SUPPORT": "After growing the mask over the PSF footprints, less than 60% of the field is usable.",
    "UNVERIFIED_KERNEL_MATCH": "The convolved images did not agree on at least three stable source centroids, scales and profiles.",
    "INSUFFICIENT_SKY": "Too few source-free pixels remain after PSF matching.",
}


def _matched(a, b, a_sources=None, b_sources=None):
    valid, wavelength = _compatible_pair(a, b)
    a_sources = _native_sources(a, 50) if a_sources is None else a_sources
    b_sources = _native_sources(b, 50) if b_sources is None else b_sources
    registration = _diagnostics(_references(a_sources, b_sources))
    registration["epsfValidated"] = all(f["metadata"].get("wavelengthCalibration") == "synthetic"
                                        and f["metadata"].get("epsfValidated") is True for f in (a, b))
    scale_a = scale_b = 1.0
    matched = None
    if all(f["metadata"].get("wavelengthCalibration") == "cwave-cband" for f in (a, b)) and wavelength["calibrated"]:
        matched, diagnostics = _cross_convolved(a, b, valid, registration)
        registration.update(diagnostics)
    if matched:
        a, b, valid, sky = matched
        scale_a = sqrt(registration["relativeScaleBoverA"])
        scale_b = 1 / scale_a
    else:
        sky = _sky_pixels(a["image"], b["image"], valid, a_sources + b_sources, 3.5)

    a_image = np.asarray(a["image"], dtype=float) * scale_a
    b_image = np.asarray(b["image"], dtype=float) * scale_b
    background = float(np.median((b_image - a_image)[sky])) if sky.sum() >= 25 else 0.0
    difference = b_image - a_image - background
    variance = a["variance"] * scale_a**2 + b["variance"] * scale_b**2
    residual_noise = _sigma(difference[sky])
    noise_ratio = max(1.0, _sigma(difference[sky] / np.sqrt(variance[sky])))
    quantitative = (wavelength["calibrated"] and registration["relativeScaleAndWidthVerified"]
                    and registration["epsfValidated"] and sky.sum() >= 25)
    warnings = []
    if not wavelength["calibrated"]:
        warnings.append("Wavelengths use approximate WCS-WAVE. This difference is a visual estimate.")
    if not registration["registrationVerified"]:
        warnings.append("Relative alignment requires at least three stable reference sources within 0.3 native pixel.")
    elif not registration["relativeScaleAndWidthVerified"]:
        warnings.append("Reference sources disagree in brightness scale or width.")
    if not registration["epsfValidated"]:
        detail = _PSF_WARNINGS.get(registration.get("psfMatchingStatus"))
        if detail:
            warnings.append(detail)
        warnings.append("This is a visual comparison. Ranked residuals require verified effective PSF matching.")
    if sky.sum() < 25:
        warnings.append("Too few source-free pixels support a background match.")
    metadata = {
        "registration": registration, "wavelength": wavelength, "quantitative": bool(quantitative),
        "validFraction": float(valid.mean()), "maskedFraction": float(1 - valid.mean()), "warnings": warnings,
        "backgroundOffsetBminusAMJySr": background, "backgroundPixels": int(sky.sum()),
        "photometricScaleA": scale_a, "photometricScaleB": scale_b,
        "skyResidualNoiseMJySr": residual_noise, "heuristicNoiseInflation": float(noise_ratio),
    }
    return difference, a_image + b_image, variance, valid, metadata


def _raster(values, valid, limits, signed):
    lo, hi = limits
    normalized = np.clip((np.where(valid, values, 0.0) - lo) / (hi - lo), 0.0, 1.0)
    if signed:
        stops = ([28, 83, 174], [23, 25, 35], [250, 108, 81])
    else:
        stops = ([18, 22, 36], [105, 109, 156], [255, 219, 143])
    rgb = np.stack([np.interp(normalized, [0, 0.5, 1], row) for row in zip(*stops)], axis=-1)
    opacity = np.where(valid, 255, 0).astype(np.uint8)
    return Image.fromarray(np.flipud(np.dstack([rgb.astype(np.uint8), opacity])))


def compare(frame_a, frame_b, mode):
    diff, total, variance, valid, info = _matched(frame_a, frame_b)
    signed = mode in {"difference", "residual_score"}
    units = "MJy/sr"
    if mode == "difference":
        values = diff
    elif mode == "absolute_change":
        values = abs(diff)
    elif mode == "sum":
        values = total
    elif mode == "residual_score":
        if not info["quantitative"]:
            raise AnalysisError("UNVERIFIED_COMPARISON", "Verified registration, passbands and effective PSFs are required for a residual score.")
        values = diff / np.sqrt(np.where(valid, variance, 1.0)) / info["heuristicNoiseInflation"]
        units = "heuristic score"
        info["warnings"].append("Correlated noise and model terms are approximated. This score has no formal p-value.")
    else:
        raise AnalysisError("UNKNOWN_COMPARISON_MODE", "Choose a supported comparison mode.")
    if signed:
        maximum = max(float(np.percentile(abs(values[valid]), 99)), 1e-8)
        limits = [-maximum, maximum]
    elif mode == "sum":
        lo, hi = (float(v) for v in np.percentile(values[valid], [1, 99]))
        limits = [lo, max(hi, lo + 1e-8)]
    else:
        limits = [0.0, max(float(np.percentile(values[valid], 99)), 1e-8)]
    first, second = frame_a["metadata"], frame_b["metadata"]
    method = "Shared TAN grid and robust additive sky matching, with equal and opposite sky corrections."
    if info["registration"].get("psfMatchingStatus") == "MATCHED":
        method = "Cross-convolved archived ePSFs, symmetric relative photometric scaling and robust sky matching."
    info.update(frameA=first["frameId"], frameB=second["frameId"], timeA=first["startUtc"],
                timeB=second["startUtc"], mode=mode, units=units, limits=limits,
                method=method)
    return info, _raster(values, valid, limits, signed)


def _measure_marks(frames, marks, automatic):
    by_id = {f["metadata"]["frameId"]: f for f in frames}
    visits = set()
    measured = []
    for mark in marks:
        frame = by_id.get(mark["frameId"])
        if frame is None:
            raise AnalysisError("FRAME_NOT_PREPARED", "Prepare each marked frame first.")
        metadata = frame["metadata"]
        if metadata["visitId"] in visits:
            raise AnalysisError("SAME_VISIT", "Choose at most one measurement per independent visit.")
        visits.add(metadata["visitId"])
        grid = metadata["grid"]
        wcs = wcs_for(grid)
        if "pixel" in mark and mark["pixel"] is not None:
            x, y = mark["pixel"]["x"], mark["pixel"]["y"]
        else:
            sky = mark["sky"]
            x, y = wcs.world_to_pixel(SkyCoord(sky["raDeg"] * u.deg, sky["decDeg"] * u.deg))
        if not np.isfinite((x, y)).all() or not (-0.5 <= x < grid["width"] - 0.5 and -0.5 <= y < grid["height"] - 0.5):
            raise AnalysisError("MARK_OUTSIDE_FIELD", "Choose a mark inside the selected image.")
        source = mark if automatic else None
        centroid = mark.get("centroidPixel")
        if centroid is not None:
            source = _verified_centroid(frame, centroid)
            x, y = source["pixel"]["x"], source["pixel"]["y"]
        if not _valid(frame)[int(y + 0.5), int(x + 0.5)]:
            raise AnalysisError("MARK_MASKED", "A mark falls on a masked or uncovered pixel.")
        sky = wcs.pixel_to_world(x, y).icrs
        scale = sqrt(abs(np.linalg.det(grid["cd"]))) * 3600
        uncertainty = source.get("sigmaPx", MANUAL_FLOOR_PX) if source is not None else MANUAL_FLOOR_PX
        time = frame_time(metadata)
        measurement = {
            "frameId": mark["frameId"], "visitId": metadata["visitId"],
            "productId": metadata.get("productId"), "timeUtc": _utc(time),
            "raDeg": float(sky.ra.deg), "decDeg": float(sky.dec.deg),
            "pixel": {"x": float(x), "y": float(y)},
            "sigmaArcsec": float(hypot(uncertainty, REGISTRATION_FLOOR_PX) * scale),
            "method": source.get("method", "measured centroid") if source is not None else "manual mark",
            "original": {key: mark[key] for key in ("pixel", "sky") if mark.get(key) is not None},
        }
        if centroid is not None:
            measurement["originalPixel"] = mark["pixel"]
        if source is not None and "covariancePx2" in source:
            measurement["covariancePx2"] = source["covariancePx2"]
        measured.append((time, sky, measurement))
    return sorted(measured, key=lambda row: row[0])


def _verified_centroid(frame, pixel):
    # Region-filtered detections use centroids from the whole prepared frame.
    for source in _native_sources(frame, SOURCE_LIMIT):
        measured = source["pixel"]
        if hypot(measured["x"] - pixel["x"], measured["y"] - pixel["y"]) <= CENTROID_MATCH_PX:
            return source
    raise AnalysisError("CENTROID_UNAVAILABLE", "The chosen centroid is unavailable in this frame. Find sources again or use a manual mark.")


def _linear_forecast(measured, grid, baseline, horizon_days):
    time0, point0, _ = measured[0]
    last_time = measured[-1][0]
    offset_frame = point0.skyoffset_frame()
    offsets = [point.transform_to(offset_frame) for _, point, _ in measured]
    coords = np.array([[p.lon.wrap_at(180 * u.deg).arcsec, p.lat.arcsec] for p in offsets])
    times = np.array([(time - time0).total_seconds() / 86400 for time, _, _ in measured])
    error = np.asarray([p["sigmaArcsec"] for _, _, p in measured])
    weights = 1 / error ** 2
    reference = np.average(times, weights=weights)
    design = np.column_stack([np.ones(len(times)), (times - reference) / baseline])
    normal = design.T @ (weights[:, None] * design)
    if np.linalg.cond(normal) > 1e4:
        return "POOR_BASELINE", "The measurement dates do not constrain a stable fit.", None
    covariance = np.linalg.inv(normal)
    solution = covariance @ design.T @ (weights[:, None] * coords)
    delta = (coords - design @ solution) / error[:, None]
    if np.max(np.linalg.norm(delta, axis=1)) > 3 or float(np.sum(delta ** 2) / (2 * len(times) - 4)) > 2.5:
        return "POOR_FIT", "The measured positions disagree with a linear path.", None
    speed_sigma = float(np.linalg.norm(solution[1]) / sqrt(covariance[1, 1]))
    if speed_sigma <= 3:
        return "UNRESOLVED_MOTION", "The fitted movement is smaller than three times its uncertainty.", None
    cap = min(30.0, baseline / 2, horizon_days if horizon_days is not None else 30.0)
    wcs = wcs_for(grid)
    scale = sqrt(abs(np.linalg.det(grid["cd"]))) * 3600
    boundary = min(grid["width"], grid["height"]) * scale / 4
    samples = []
    actual_horizon = 0.0
    for day in np.linspace(0, cap, 25):
        design_row = np.array([1, (baseline + day - reference) / baseline])
        lon, lat = design_row @ solution
        predicted = SkyCoord(lon * u.arcsec, lat * u.arcsec, frame=offset_frame).icrs
        x, y = wcs.world_to_pixel(predicted)
        sigma = sqrt(float(design_row @ covariance @ design_row) + (REGISTRATION_FLOOR_PX * scale) ** 2)
        radius = sqrt(5.991) * sigma
        if radius > boundary or not (0 <= x < grid["width"] and 0 <= y < grid["height"]):
            break
        actual_horizon = float(day)
        samples.append({
            "x": float(x), "y": float(y), "raDeg": float(predicted.ra.deg), "decDeg": float(predicted.dec.deg),
            "timeUtc": _utc(last_time + timedelta(days=float(day))), "sigmaArcsec": sigma,
            "ellipse95Arcsec": radius,
        })
    if len(samples) < 2:
        return "FIELD_OR_UNCERTAINTY_LIMIT", "The path leaves the field or exceeds the uncertainty limit.", None
    return "AVAILABLE", "Significant apparent motion across independent visits.", {
        "samples": samples, "horizonDays": actual_horizon, "model": "Weighted linear apparent sky path",
        "uncertainty": "Approximate 95% radius including a 0.15-pixel registration floor",
        "motionSigma": speed_sigma, "baselineDays": baseline,
    }


def track(frames, *, marks, horizon_days=None, automatic=False, ambiguous=False):
    if not 2 <= len(marks) <= 8:
        raise AnalysisError("INVALID_MARK_COUNT", "Choose two to eight measured positions.")
    measured = _measure_marks(frames, marks, automatic)
    first_time, first, first_info = measured[0]
    last_time, last, last_info = measured[-1]
    baseline = (last_time - first_time).total_seconds() / 86400
    if baseline <= 0:
        raise AnalysisError("SAME_VISIT", "Choose dates with different timestamps.")
    separation = float(first.separation(last).arcsec)
    uncertainty = hypot(first_info["sigmaArcsec"], last_info["sigmaArcsec"])
    if ambiguous:
        status, reason = "AMBIGUOUS_ASSOCIATION", "More than one detection could belong to this source."
    elif len(measured) < 3:
        status, reason = "TOO_FEW_EPOCHS", "A forecast requires at least three independent visits."
    elif not automatic:
        status, reason = "UNVERIFIED_ASSOCIATION", "Use a vetted detected source to estimate a future path."
    else:
        status, reason = "AVAILABLE", None
    forecast = None
    if status == "AVAILABLE":
        frame_map = {f["metadata"]["frameId"]: f for f in frames}
        grid = frame_map[first_info["frameId"]]["metadata"]["grid"]
        status, reason, forecast = _linear_forecast(measured, grid, baseline, horizon_days)
    return {
        "measurements": [p for _, _, p in measured], "baselineDays": baseline,
        "separationArcsec": separation, "positionAngleDeg": float(first.position_angle(last).deg) if separation > 1e-8 else None,
        "rateArcsecPerDay": separation / baseline, "uncertaintyArcsec": uncertainty,
        "forecastStatus": status, "forecastReason": reason, "forecast": forecast,
    }


def _centroid_covariance(source):
    if source.get("covariancePx2") is not None:
        return np.asarray(source["covariancePx2"], dtype=float)
    return np.eye(2) * source.get("sigmaPx", MANUAL_FLOOR_PX)**2


def _within_motion_envelope(displacement, covariance, travel):
    distance = hypot(*displacement)
    if distance <= travel:
        return True
    direction = displacement / distance
    # The relative position includes a registration floor for both independent visits.
    variance = float(direction @ covariance @ direction) + 2 * REGISTRATION_FLOOR_PX**2
    return distance - travel <= ASSOCIATION_SIGMA * sqrt(variance)


def _associate(groups, limit):
    tracks = []
    for time, sources in groups:
        points = _pixels(sources)
        tree = cKDTree(points)
        covariances = [_centroid_covariance(source) for source in sources]
        claims = {}
        active = []
        for index, candidate in enumerate(tracks):
            last_time, previous = candidate["points"][-1]
            days = (time - last_time).total_seconds() / 86400
            travel = MAX_ASSOCIATION_SPEED_PX_PER_DAY * days
            last = _pixels([previous])[0]
            covariance = _centroid_covariance(previous)
            region = [match for match in tree.query_ball_point(last, MAX_ASSOCIATION_RADIUS_PX)
                      if _within_motion_envelope(points[match] - last, covariance + covariances[match], travel)]
            if len(region) > 1:
                candidate["ambiguous"] = True
            for match in region:
                claims.setdefault(match, []).append(index)
            active.append(len(region))
        matched = set()
        for match, owners in sorted(claims.items()):
            if len(owners) > 1:
                for index in owners:
                    tracks[index]["ambiguous"] = True
            else:
                index = owners[0]
                if active[index] == 1:
                    tracks[index]["points"].append((time, sources[match]))
                    matched.add(match)
        for index, source in enumerate(sources):
            if index not in matched and len(tracks) < limit:
                tracks.append({"points": [(time, source)], "ambiguous": index in claims})
    return tracks


def _in_footprint(source, valid):
    x, y = source["pixel"]["x"], source["pixel"]["y"]
    return valid[int(y + 0.5), int(x + 0.5)]


def _in_region(x, y, region):
    return not region or (region["x"] <= x < region["x"] + region["width"]
                          and region["y"] <= y < region["y"] + region["height"])


def _matched_brightness(anchor, other, comparison):
    difference, variance, valid, noise_inflation = comparison
    center_x, center_y = np.mean(_pixels([anchor, other]), axis=0)
    x, y = np.rint([center_x, center_y]).astype(int)
    if not (3 <= x < valid.shape[1] - 3 and 3 <= y < valid.shape[0] - 3):
        return 0.0
    yy, xx = np.mgrid[y - 3:y + 4, x - 3:x + 4]
    core = (xx - center_x)**2 + (yy - center_y)**2 <= 2.9**2
    if not valid[yy[core], xx[core]].all():
        return 0.0
    pixels = yy[core], xx[core]
    # A sum of standard deviations bounds the error of the aperture sum even with correlated resampling noise.
    noise = np.sqrt(variance[pixels]).sum() * noise_inflation
    return float(abs(difference[pixels].sum()) / noise)


def _isolated_input_spike(frame, pixel, direction):
    """Veto an isolated native-grid outlier that matching kernels would spread."""
    x, y = round(pixel["x"]), round(pixel["y"])
    stamp = np.s_[y - 2:y + 3, x - 2:x + 3]
    image = frame["image"][stamp]
    variance = frame["variance"][stamp]
    if image.shape != (5, 5):
        return False
    valid = frame["valid"][stamp] & np.isfinite(image) & np.isfinite(variance) & (variance > 0)
    sky = valid.copy()
    core = np.s_[1:4, 1:4]
    sky[core] = False
    if sky.sum() < 8:
        return False
    background = np.median(image[sky])
    contrast = np.maximum((image[core] - background) * direction, 0)
    core_valid = valid[core]
    excess = np.where(core_valid, contrast, 0)
    peak_index = np.unravel_index(excess.argmax(), excess.shape)
    peak = excess[peak_index]
    if not core_valid[peak_index]:
        return False
    noise = max(_sigma(image[sky]), sqrt(variance[core][peak_index]))
    return peak > 8 * noise and peak >= 0.90 * excess.sum()


def _signed_residual_groups(reference, frame, comparison, limit, region):
    difference, variance, valid, noise_inflation = comparison
    first, second = reference["metadata"], frame["metadata"]
    paired = {"frameA": first["frameId"], "frameB": second["frameId"],
              "timeA": _utc(frame_time(first)), "timeB": _utc(frame_time(second)),
              "label": "single-pair change", "method": "Signed residual aperture moments with a correlated-noise bound"}
    wcs = wcs_for(first["grid"])
    residual = {"metadata": second, "valid": valid, "variance": variance * noise_inflation**2}
    groups = []
    # Distinct measurements for brighter and fainter groups, each with positive significance.
    for sign, direction in (("positive", 1), ("negative", -1)):
        residual["image"] = difference * direction
        sources = _native_sources(residual, limit, region=region, correlated=True)
        if not sources:
            continue
        points = wcs.pixel_to_world(*_pixels(sources).T).icrs
        for source, point in zip(sources, points):
            pixel = source["pixel"]
            if _isolated_input_spike(frame, pixel, direction) or _isolated_input_spike(reference, pixel, -direction):
                continue
            measured = {key: source[key] for key in (
                "pixel", "covariancePx2", "snr", "fluxError", "fluxUnit", "maskDistancePx", "widthPx",
            )}
            groups.append({**measured, **paired, "sign": sign, "raDeg": float(point.ra.deg),
                           "decDeg": float(point.dec.deg), "flux": source["flux"] * direction})
    return groups


def detect(frames, *, region=None, limit=SOURCE_LIMIT):
    if not 2 <= len(frames) <= 8:
        raise AnalysisError("INVALID_FRAME_COUNT", "Choose two to eight prepared frames.")
    ordered = sorted(frames, key=lambda frame: frame_time(frame["metadata"]))
    chosen = []
    visits = set()
    warnings = []
    for frame in ordered:
        visit = frame["metadata"]["visitId"]
        if visit not in visits:
            chosen.append(frame)
            visits.add(visit)
    if len(chosen) < len(ordered):
        warnings.append("Retained at most one exposure per independent visit.")
    if len(chosen) < 2:
        raise AnalysisError("SAME_VISIT", "Choose at least two different independent visits.")
    reference = chosen[0]
    certified = [(reference, _native_sources(reference, limit))]
    comparisons = {}
    tested = []
    sources_preview = []
    residual_groups = []
    for frame in chosen:
        frame_id = frame["metadata"]["frameId"]
        tested.append(frame_id)
        native = certified[0][1] if frame is reference else _native_sources(frame, limit)
        sources_preview.append({"frameId": frame_id, "sources": native})
        if frame is reference:
            continue
        try:
            diff, _, variance, valid, metadata = _matched(reference, frame, certified[0][1], native)
        except AnalysisError as problem:
            warnings.append(f"{frame_id}: {problem.message}")
            continue
        if not metadata["quantitative"]:
            warnings.append(f"{frame_id}: candidate ranking requires a calibrated, vetted comparison.")
            continue
        comparisons[frame_id] = diff, variance, valid, metadata["heuristicNoiseInflation"]
        residual_groups.extend(_signed_residual_groups(reference, frame, comparisons[frame_id], limit + 1, region))
        certified.append((frame, native))
    candidates = []
    if comparisons:
        groups = []
        reference_id = reference["metadata"]["frameId"]
        reference_valid = np.logical_or.reduce([comparison[2] for comparison in comparisons.values()])
        for frame, sources in certified:
            valid = reference_valid if frame is reference else comparisons[frame["metadata"]["frameId"]][2]
            selected = [s for s in sources if _in_footprint(s, valid)
                        and _in_region(s["pixel"]["x"], s["pixel"]["y"], region)]
            groups.append((frame_time(frame["metadata"]), selected))
        qualified = [frame for frame, _ in certified]
        for association in _associate(groups, 100):
            marks = [source for _, source in association["points"]]
            if len(marks) < 2:
                continue
            ambiguous = association["ambiguous"]
            result = track(qualified, marks=marks, automatic=True, ambiguous=ambiguous)
            position_score = result["separationArcsec"] / result["uncertaintyArcsec"]
            brightness_score = 0.0
            if marks[0]["frameId"] == reference_id:
                brightness_score = max(_matched_brightness(marks[0], source, comparisons[source["frameId"]])
                                       for source in marks[1:])
            if ambiguous:
                label, reason = "ambiguous", "Multiple local detections are consistent with this association."
            elif result["forecastStatus"] == "AVAILABLE":
                label, reason = "motion candidate", "Consistent significant displacement across independent visits."
            elif position_score >= 3:
                label, reason = "single-pair change", "Significant apparent displacement. Additional vetted visits are needed."
            elif brightness_score >= 5:
                label, reason = "possible variable", "Position is consistent and the matched aperture changed across visits."
            else:
                continue
            candidates.append({
                "candidateId": content_key("detection-v2", marks, ambiguous), "label": label, "reason": reason,
                "ambiguous": ambiguous, "marks": marks,
                "positionScore": position_score, "brightnessScore": brightness_score,
                "brightnessMethod": "Common-aperture difference with a conservative correlated-noise bound",
                "score": min(50.0, max(position_score, brightness_score)) * sqrt(len(marks)) / (2 if ambiguous else 1),
            })
    candidates.sort(key=lambda item: (-item["score"], item["candidateId"]))
    residual_groups.sort(key=lambda item: (-item["snr"], item["timeB"], item["pixel"]["y"], item["pixel"]["x"]))
    if len(residual_groups) > limit:
        warnings.append(f"Showing the {limit} strongest signed residual groups from the tested visits.")
    return {
        "candidates": candidates[:limit], "testedFrameIds": tested, "sources": sources_preview,
        "residualGroups": residual_groups[:limit], "warnings": warnings, "partial": bool(warnings),
    }

