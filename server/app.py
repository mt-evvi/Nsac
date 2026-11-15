"""Same-origin browser shell, archive jobs, and immutable display assets."""

import asyncio
import re
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from functools import partial

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .analysis_api import router as analysis_router
from .config import MIB, SETTINGS
from .contracts import ID, JOB_ID, FrameOptions, Problem, SeriesQuery, ready
from .jobs import Jobs
from .release_index import schedule_if_due
from .store import Store, content_key
from .telemetry import RequestTraffic, Telemetry
from .upstream import check_admission

ASSET_NAME = re.compile(r"[a-f0-9]{32}\.png\Z")
SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{24}\Z")
COOKIE = "spherex_session"


class RequestBounds:
    def __init__(self, app, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                response = problem_response(Problem("REQUEST_TOO_LARGE", "Maximum API request size is 16 KiB.", 413))
                await response(scope, receive, send)
                return
            if not message.get("more_body"):
                break

        async def bounded_receive():
            if body is not None:
                return drain_body()
            return await receive()

        def drain_body():
            nonlocal body
            payload = bytes(body)
            body = None
            return {"type": "http.request", "body": payload, "more_body": False}

        await self.app(scope, bounded_receive, send)


def problem_response(exc):
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse(exc.payload(), status_code=exc.status, headers=headers)


def session_info(request):
    value = request.cookies.get(COOKIE, "")
    if SESSION_TOKEN.fullmatch(value):
        return value, False
    return secrets.token_urlsafe(18), True


def session_cookie(request, response, session):
    response.set_cookie(COOKIE, session, httponly=True, samesite="lax", secure=request.url.scheme == "https")


class Service:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings)
        self.jobs = Jobs(settings)
        self.cursor_secret = secrets.token_hex(32)
        self.bundle_bytes = self.store.example_bundle()

    def schedule(self, request, key, stage, work, *, detached=False, transfer_kind=None, **options):
        self.store.check_capacity()
        client = request.client.host if request.client else "local"
        session, new = session_info(request)
        requester = f"refresh-{key}" if detached else session
        admit = partial(check_admission, transfer_kind) if transfer_kind else None
        job = self.jobs.submit(key, client, requester, stage, work, admit=admit, **options)
        response = JSONResponse(job, status_code=202, headers={"Cache-Control": "no-store"})
        if new and not detached:
            session_cookie(request, response, session)
        return response

    def manifest(self, series_id):
        preset = self.store.preset(series_id)
        if preset is not None:
            return preset
        row = self.store.get("series", series_id)
        if row is None or row[1] > self.settings.stale_ttl:
            raise Problem("SERIES_EXPIRED", "Discover this field again to restore its archive index.", 404, True)
        return row[0]

    def page(self, envelope, offset=0):
        data = envelope["data"]
        frames = data["frames"]
        limit = self.settings.page_size
        series_id = data["seriesId"]
        subset = []
        for frame in frames[offset:offset + limit]:
            if frame.get("imageUrl"):
                subset.append(frame)
            else:
                subset.append(self.store.prepared(series_id, frame["frameId"]) or frame)
        next_offset = offset + limit
        cursor = content_key(self.cursor_secret, series_id, next_offset) if next_offset < len(frames) else None
        return {**envelope, "data": {**data, "frames": subset, "nextCursor": cursor, "indexedFrameCount": len(frames)}}

    def frame(self, series_id, frame_id):
        manifest = self.manifest(series_id)["data"]
        frame = next((item for item in manifest["frames"] if item["frameId"] == frame_id), None)
        if frame is None:
            frame = self.store.prepared(series_id, frame_id)
        if frame is None:
            raise Problem("FRAME_NOT_FOUND", "The frame does not belong to this series.", 404)
        return manifest, frame

    def analysis_frame(self, series_id, frame_id):
        _, frame = self.frame(series_id, frame_id)
        frame = self.store.prepared(series_id, frame_id) or frame
        return frame, self.store.load_arrays(series_id, frame)


def create_app(settings=SETTINGS):
    async def refresh_release_inventory(service):
        while True:
            with suppress(Problem):
                schedule_if_due(service)
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = Service(settings)
        tasks = []
        if settings.refresh_releases:
            tasks.append(asyncio.create_task(refresh_release_inventory(app.state.service)))
        if settings.monitor:
            app.state.telemetry = Telemetry(app.state.service)
            tasks.append(asyncio.create_task(app.state.telemetry.run()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            app.state.service.jobs.close()

    app = FastAPI(title="Planet X and SPHEREx", version="1", lifespan=lifespan)
    app.add_middleware(RequestBounds, limit=settings.body_limit)
    if settings.monitor:
        app.add_middleware(RequestTraffic)

    @app.exception_handler(Problem)
    async def handle_problem(_request, exc):
        return problem_response(exc)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc):
        issues = exc.errors()
        location = ".".join(str(part) for part in issues[0]["loc"][1:]) if issues else ""
        prefix = f"{location}: " if location and re.fullmatch(r"[A-Za-z0-9_.]{1,64}", location) else ""
        error = issues[0] if issues else {}
        message = error.get("msg", "Check the request parameters.")
        return problem_response(Problem("INVALID_REQUEST", f"{prefix}{message}"))

    @app.exception_handler(HTTPException)
    async def http_problem(request, exc):
        if request.url.path.startswith("/api/"):
            return problem_response(Problem("NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
                                            "The requested API resource is unavailable.", exc.status_code))
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def readiness(request: Request):
        from . import upstream

        service = request.app.state.service
        static = (settings.web / "index.html").is_file()
        database = service.store.cache_available()
        bundles = service.bundle_bytes is not None and service.bundle_bytes <= 100 * MIB
        release_index = service.store.get("release-index", "attempt") if settings.refresh_releases and database else None
        status = "ready" if static and bundles and database else "unavailable"
        return JSONResponse({"status": status, "release": settings.release, "schemaVersion": 1,
                             "static": static, "presets": bundles, "cache": database, "archive": upstream.LAST_PROBE,
                             "archiveDiscovery": upstream.LAST_DISCOVERY_PROBE,
                             "releaseIndex": release_index[0] if release_index else None}, status_code=200 if status == "ready" else 503)

    @app.post("/api/v1/series")
    def discover(query: SeriesQuery, request: Request):
        from . import archive

        service = request.app.state.service
        normalized = query.normalized()
        day = datetime.now(UTC).date().isoformat() if "end" not in normalized else None
        series_id = content_key("series", archive.PIPELINE_VERSION, normalized, day)
        row = service.store.get("series", series_id)
        legacy = False
        if row is None:
            for version in archive.COMPATIBLE_INDEX_VERSIONS:
                prior = service.store.get("series", content_key("series", version, normalized, day))
                if prior and prior[1] <= settings.stale_ttl and prior[0]["data"].get("frames"):
                    row, legacy = prior, True
                    break
        if row is not None:
            data, age = row
            no_coverage = data["data"].get("searchStatus") in {"NO_COVERAGE", "NO_COMPARABLE_FRAMES"}
            ttl = settings.empty_ttl if no_coverage or data["status"] == "partial" else settings.metadata_ttl
            if age < ttl and not legacy:
                return service.page(data)

        def work():
            manifest = archive.discover(normalized)
            warnings = manifest.pop("warnings", [])
            incomplete = manifest.get("searchStatus") in {"PARTIAL", "partial"} or manifest.get("complete") is False
            data = {"schemaVersion": 1, **manifest, "seriesId": series_id}
            envelope = ready(data, warnings, incomplete)
            service.store.put("series", series_id, envelope)
            return service.page(envelope)

        has_stale = row is not None and not no_coverage and age <= settings.stale_ttl
        try:
            response = service.schedule(request, series_id, "discovering archive observations", work, detached=has_stale,
                                        transfer_kind="irsa")
        except Problem:
            if not has_stale:
                raise
            response = None
        if has_stale:
            checked = datetime.fromtimestamp(datetime.now(UTC).timestamp() - age, UTC).isoformat()
            origin = " from the preceding compatible index" if legacy else ""
            warning = f"Showing cached archive metadata{origin} checked {checked}. Refresh for newly published observations."
            return service.page({**data, "status": "partial", "warnings": [*data["warnings"], warning]})
        return response

    @app.get("/api/v1/series/{series_id}")
    def get_series(series_id: ID, request: Request, cursor: ID | None = None):
        service = request.app.state.service
        envelope = service.manifest(series_id)
        offset = 0
        if cursor is not None:
            limit = settings.page_size
            offsets = range(limit, len(envelope["data"]["frames"]), limit)
            offset = next((start for start in offsets if content_key(service.cursor_secret, series_id, start) == cursor), -1)
            if offset < 0:
                raise Problem("INVALID_CURSOR", "The page cursor does not belong to this series.")
        return service.page(envelope, offset)

    @app.get("/api/v1/series/{series_id}/frames/{frame_id}")
    def get_frame(series_id: ID, frame_id: ID, request: Request):
        service = request.app.state.service
        _, frame = service.frame(series_id, frame_id)
        return ready(service.store.prepared(series_id, frame_id) or frame)

    @app.post("/api/v1/series/{series_id}/frames/{frame_id}")
    def prepare_frame(series_id: ID, frame_id: ID, request: Request, options: FrameOptions | None = None):
        from . import imaging

        service = request.app.state.service
        manifest, candidate = service.frame(series_id, frame_id)
        options = options or FrameOptions()
        mode = options.representation
        result_id = frame_id if mode == "exposure" else content_key("coadd-v2", frame_id)
        variant = service.store.get("coadd-variant", f"{series_id}:{result_id}") if mode == "coadd" else None
        cached = service.store.prepared(series_id, variant[0] if variant else result_id)
        if cached:
            return ready(cached)
        if mode == "exposure" and candidate.get("imageUrl"):
            return ready(candidate)

        def work():
            if mode == "coadd":
                frame, arrays, png, mask = imaging.coadd(manifest, candidate, service.store, result_id)
            else:
                existing_stretch = service.store.get("stretch", series_id)
                from .spectra import calibration_paths

                spectral, *_ = next(calibration_paths(candidate["release"].lower(), candidate["detector"], service.store.root))
                info, arrays, png, mask = imaging.prepare(
                    manifest["query"], candidate, manifest["grid"], stretch=existing_stretch[0] if existing_stretch else None,
                    spectral_calibration=spectral if spectral.is_file() else None,
                )
                if not existing_stretch and options.priority == "interactive":
                    service.store.set_if_absent("stretch", series_id, info["stretch"])
                    shared = service.store.get("stretch", series_id)[0]
                    if shared != info["stretch"]:
                        info["stretch"], png, mask = imaging.render_frame(arrays, shared)
                frame = {**candidate, **info, "frameId": frame_id}
            frame = service.store.save_frame(series_id, frame, arrays, png, mask)
            if mode == "coadd":
                service.store.put("coadd-variant", f"{series_id}:{result_id}", frame["frameId"])
            return ready(frame, frame.get("warnings", []))

        return service.schedule(request, f"{series_id}:{result_id}", "fetching and aligning the frame", work,
                                transfer_kind="irsa" if mode == "exposure" else None,
                                priority=2 if options.priority == "prefetch" else 0)

    @app.get("/api/v1/jobs/{job_id}")
    def read_job(job_id: JOB_ID, request: Request):
        result = request.app.state.service.jobs.read(job_id)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.delete("/api/v1/jobs/{job_id}", status_code=204)
    def cancel_job(job_id: JOB_ID, request: Request):
        session, _ = session_info(request)
        request.app.state.service.jobs.abandon(job_id, session)
        return Response(status_code=204)

    @app.get("/data/{name}", include_in_schema=False)
    def derived_asset(name: str, request: Request):
        path = request.app.state.service.store.public_asset(name) if ASSET_NAME.fullmatch(name) else None
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/", include_in_schema=False)
    @app.get("/explore", include_in_schema=False)
    def shell(request: Request):
        index = settings.web / "index.html"
        if not index.is_file():
            raise Problem("BUILD_REQUIRED", "Build the Vite frontend before starting the full site.", 503)
        session, new = session_info(request)
        response = FileResponse(index, headers={"Cache-Control": "no-cache"})
        if new:
            session_cookie(request, response, session)
        return response

    app.include_router(analysis_router)

    for name in ("assets", "presets"):
        app.mount(f"/{name}", StaticFiles(directory=settings.web / name, check_dir=False), name=name)
    return app


app = create_app()
