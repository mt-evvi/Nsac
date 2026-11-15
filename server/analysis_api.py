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
SPECTRUM_VERSION = "v3"


def dataset(service, series_id, frame_id, grid):
    frame, arrays = service.analysis_frame(series_id, frame_id)
    return {**arrays, "metadata": {**frame, "grid": grid}}


def cached_job(request, service, key, stage, fn, *, extended=False, ttl=None):
    existing = service.store.get("analysis", key)
    if existing and (ttl is None or existing[1] < ttl):
        data = existing[0]
        if not data["data"].get("assetUrl") or service.store.public_asset(data["data"]["assetUrl"].rsplit("/", 1)[1]):
            return data

    def work():
        from .analysis import AnalysisError

        try:
            result = fn()
        except AnalysisError as exc:
            raise Problem(exc.code, exc.message, 409) from exc
        service.store.put("analysis", key, result)
        return result

    return service.schedule(request, key, stage, work, extended=extended)


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
    for frame_id in ids:
        service.frame(series_id, frame_id)
    region = options.region.model_dump() if options.region else None
    key = content_key(ANALYSIS_VERSION, "detections", series_id, ids, region)

    def work():
        frames = [dataset(service, series_id, frame_id, grid) for frame_id in ids]
        result = run_science("detect", 12, frames, region=region)
        for item in result["candidates"]:
            service.store.put("candidate", f"{series_id}:{item['candidateId']}", item)
        return ready({**result, "analysisId": key}, result.get("warnings", []))

    return cached_job(request, service, key, "measuring sources", work, extended=True)


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
    key = content_key(ANALYSIS_VERSION, "track", series_id, options.model_dump())

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
    key = content_key(ANALYSIS_VERSION, "catalog", grid, options.catalog)
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

    return service.schedule(request, f"{key}:{options.frameId or 'reference'}", "loading catalog positions", work)


@router.post("/spectra")
def spectrum(series_id: ID, options: SpectrumQuery, request: Request):
    from . import spectra

    service = request.app.state.service
    manifest = service.manifest(series_id)["data"]
    linked = candidate(service, series_id, options.candidateId) if options.candidateId else None
    key = content_key(SPECTRUM_VERSION, "spectrum", series_id, options.model_dump(mode="json"))

    def work():
        result = spectra.extract(manifest, options.model_dump(mode="json", exclude_none=True), linked, service.store)
        return ready(result, result.get("warnings", []), bool(result.get("partial")))

    return cached_job(request, service, key, "extracting spectrum", work, extended=True,
                      ttl=service.settings.metadata_ttl)
