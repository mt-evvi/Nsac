"""Local operational counters with no visitor identifiers or request content."""

import asyncio
import json
import logging
import resource
import sqlite3
import time
from collections import Counter

from . import upstream

LOG = logging.getLogger("uvicorn.error.spherex.telemetry")
INTERVAL = 60
ALERT_PERIODS = 3


class RequestTraffic:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        telemetry = scope["app"].state.telemetry

        async def observe(message):
            if message["type"] == "http.response.start":
                telemetry.requests[message["status"]] += 1
            elif message["type"] == "http.response.body":
                telemetry.response_bytes += len(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, observe)


class Telemetry:
    def __init__(self, service):
        self.service = service
        self.requests = Counter()
        self.response_bytes = 0
        self.alert_streak = {"queue_saturation": 0, "archive_degraded": 0}

    def sample(self):
        return {
            **self.service.store.cache_activity(), **self.service.jobs.capacity_activity(),
            "upstream24hBytes": upstream.TRANSFERS.recent_bytes(),
            "peakServerRssBytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "peakExitedWorkerRssBytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024,
        }

    def report(self, work, now):
        probe = upstream.LAST_PROBE
        discovery = upstream.LAST_DISCOVERY_PROBE
        logs = {"release": self.service.settings.release, "seconds": INTERVAL,
                "requests": self.requests.total(), "http429": self.requests[429], "http503": self.requests[503],
                "responseBodyBytes": self.response_bytes, "bundledExampleBytes": self.service.bundle_bytes,
                "archive": probe, "archiveDiscovery": discovery, **work}
        self.requests.clear()
        self.response_bytes = 0
        LOG.info("spherex_metrics %s", json.dumps(logs, separators=(",", ":")))
        symptoms = {
            "queue_saturation": work["queueRejections"] > 0 or work["queuedJobs"] >= self.service.settings.queue_limit,
            "archive_degraded": any(status and status["status"] == "degraded" and now - status["checkedAtUnix"] <= INTERVAL
                                    for status in (probe, discovery)),
        }
        for reason, active in symptoms.items():
            self.alert_streak[reason] = self.alert_streak[reason] + 1 if active else 0
            if self.alert_streak[reason] == ALERT_PERIODS:
                LOG.warning("spherex_alert release=%s reason=%s sustained_seconds=%d",
                            self.service.settings.release, reason, ALERT_PERIODS * INTERVAL)

    async def run(self):
        while True:
            await asyncio.sleep(INTERVAL)
            try:
                work = await asyncio.to_thread(self.sample)
            except (OSError, sqlite3.Error):
                LOG.warning("spherex_metrics_unavailable release=%s", self.service.settings.release)
                continue
            self.report(work, int(time.time()))
