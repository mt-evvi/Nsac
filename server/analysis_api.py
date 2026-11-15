"""On-demand analyses limited to the selected indexed field and frames."""

import io
import time

from fastapi import APIRouter, Request

from .contracts import (ID, ComparisonQuery, DetectionQuery, OverlayQuery, Problem, SpectrumQuery,
                        TrackQuery, ready)
from .store import content_key
from .workers import run_science

router = APIRouter(prefix="/api/v1/series/{series_id}")
ANALYSIS_VERSION = "v2"
DETECTION_VERSION = "v4"
TRACK_VERSION = "v3"
SPECTRUM_VERSION = "v3"


def dataset(service, series_id, frame_id, grid):
    frame, arrays = service.analysis_frame(series_id, frame_id)
    return {**arrays, "metadata": {**frame, "grid": grid}}


def cached_job(request, service, key, stage, fn, *, extended=False, ttl=None, decorate=None, transfer_kind=None):
    existing = service.store.get("analysis", key)
    if existing and (ttl is None or existing[1] < ttl):
        data = existing[0]
        if not data["data"].get("assetUrl") or service.store.public_asset(data["data"]["assetUrl"].rsplit("/", 1)[1]):
            return decorate(data) if decorate else data

    def work():
        from .analysis import AnalysisError

        try:
            result = fn()
        except AnalysisError as exc:
            raise Problem(exc.code, exc.message, 409) from exc
        service.store.put("analysis", key, result)
        return decorate(result) if decorate else result

    return service.schedule(request, key, stage, work, extended=extended, transfer_kind=transfer_kind)


def catalog_cache_key(grid, catalog):
    return content_key(ANALYSIS_VERSION, "catalog", grid, catalog)


@router.post("/comparisons")
def comparison(series_id: ID, options: ComparisonQuery, request: Request):
    service = request.app.state.service
    grid = service.manifest(series_id)["data"]["grid"]
    for frame_id in (options.frameA, options.frameB):
        service.frame(series_id, frame_id)
    key = content_key(ANALYSIS_VERSION, "comparison", series_id, options.model_dump())

    def work():
        a = dataset(service, series_id, options.frameA, grid)
        b = dataset(service, series_id, options.frameB, grid)
        metadata, image = run_science("compare", 5, a, b, options.mode)
        payload = io.BytesIO()
        image.save(payload, format="PNG", optimize=True)
        name = service.store.write_asset(payload.getvalue(), "png")
        result = {**metadata, "comparisonId": key, "assetUrl": f"/data/{name}"}
        service.store.put("comparison", f"{series_id}:{key}", [options.frameA, options.frameB])
        return ready(result, metadata.get("warnings", []))

    return cached_job(request, service, key, "comparing aligned images", work)


@router.post("/detections")
def detections(series_id: ID, options: DetectionQuery, request: Request):
    service = request.app.state.service
    grid = service.manifest(series_id)["data"]["grid"]
    ids = options.frameIds
    if options.comparisonId:
        comparison_row = service.store.get("comparison", f"{series_id}:{options.comparisonId}")
        if comparison_row is None:
            raise Problem("COMPARISON_EXPIRED", "Prepare the comparison again before detecting sources.", 404)
        ids = comparison_row[0]
    frame_metadata = {frame_id: service.frame(series_id, frame_id)[1] for frame_id in ids}
    region = options.region.model_dump() if options.region else None
    key = content_key(DETECTION_VERSION, "detections", series_id, ids, region)

    def work():
        frames = [dataset(service, series_id, frame_id, grid) for frame_id in ids]
        result = run_science("detect", 12, frames, region=region)
        for item in result["candidates"]:
            service.store.put("candidate", f"{series_id}:{item['candidateId']}", item)
        return ready({**result, "analysisId": key}, result.get("warnings", []), bool(result.get("partial")))

    def decorate(envelope):
        from .catalogs import nearby_matches

        data = envelope["data"]
        if not data["candidates"]:
            return envelope
        catalogs = []
        for catalog in ("gaia_dr3", "allwise"):
            cached = service.store.get("catalog", catalog_cache_key(grid, catalog))
            if cached and cached[1] < service.settings.catalog_ttl:
                catalogs.append(cached[0])
        if not catalogs:
            return envelope
        prepared = {frame_id: service.store.prepared(series_id, frame_id) or frame
                    for frame_id, frame in frame_metadata.items()}
        matches = nearby_matches(data["candidates"], catalogs, prepared, grid)
        candidates = [{**item, "catalogMatches": matches[item["candidateId"]]} for item in data["candidates"]]
        return {**envelope, "data": {**data, "candidates": candidates}}

    return cached_job(request, service, key, "measuring sources", work, extended=True, decorate=decorate)


def candidate(service, series_id, candidate_id):
    kept = service.store.get("candidate", f"{series_id}:{candidate_id}")
    if kept is None:
        raise Problem("CANDIDATE_EXPIRED", "Run source detection again to restore this candidate.", 404)
    return kept[0]


@router.post("/tracks")
def track(series_id: ID, options: TrackQuery, request: Request):
    service = request.app.state.service
    grid = service.manifest(series_id)["data"]["grid"]
    linked = candidate(service, series_id, options.candidateId) if options.candidateId else None
    marks = linked["marks"] if linked else [mark.model_dump(exclude_none=True) for mark in options.marks]
    ids = list(dict.fromkeys(mark["frameId"] for mark in marks))
    for frame_id in ids:
        service.frame(series_id, frame_id)
    key = content_key(TRACK_VERSION, "track", series_id, options.model_dump())

    def work():
        frames = [dataset(service, series_id, frame_id, grid) for frame_id in ids]
        result = run_science("track", 2, frames, marks=marks, horizon_days=options.horizonDays,
                                automatic=linked is not None, ambiguous=bool(linked and linked.get("ambiguous")))
        return ready(result)

    return cached_job(request, service, key, "measuring motion", work)


@router.post("/overlays")
def overlay(series_id: ID, options: OverlayQuery, request: Request):
    from . import catalogs

    service = request.app.state.service
    grid = service.manifest(series_id)["data"]["grid"]
    frame = service.frame(series_id, options.frameId)[1] if options.frameId else None
    key = catalog_cache_key(grid, options.catalog)
    cached = service.store.get("catalog", key)

    def render(rows):
        result = catalogs.project_catalog(rows, grid, frame)
        return ready(result, result.get("warnings", []), bool(result.get("truncated")))

    if cached and cached[1] < service.settings.catalog_ttl:
        return render(cached[0])

    def work():
        rows = catalogs.fetch_catalog(options.catalog, grid, time.monotonic() + 10)
        service.store.put("catalog", key, rows)
        return render(rows)

    return service.schedule(request, f"{key}:{options.frameId or 'reference'}", "loading catalog positions", work,
                            transfer_kind="catalog")


@router.post("/spectra")
def spectrum(series_id: ID, options: SpectrumQuery, request: Request):
    from . import spectra

    service = request.app.state.service
    manifest = service.manifest(series_id)["data"]
    linked = candidate(service, series_id, options.candidateId) if options.candidateId else None
    recipe = "coadded-cube-v1" if options.mode == "coadded_cube" else "spectrum"
    key = content_key(SPECTRUM_VERSION, recipe, series_id, options.model_dump(mode="json"))

    def work():
        result = spectra.extract(manifest, options.model_dump(mode="json", exclude_none=True), linked, service.store)
        return ready(result, result.get("warnings", []), bool(result.get("partial")))

    return cached_job(request, service, key, "extracting spectrum", work, extended=True,
                      ttl=service.settings.metadata_ttl, transfer_kind="irsa")
