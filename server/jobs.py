"""Shared single-process job admission, deduplication, and polling."""

import logging
import secrets
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from .contracts import Problem

LOG = logging.getLogger("uvicorn.error.spherex.jobs")
ACTIVE = {"queued", "running"}


@dataclass
class Job:
    id: str
    key: str
    work: Callable
    stage: str
    extended: bool
    priority: int
    enqueued: float
    requesters: set[str] = field(default_factory=set)
    status: str = "queued"
    response: dict | None = None
    finished: float | None = None

    def pending(self):
        return {"status": self.status, "jobId": self.id, "pollAfterMs": 1000, "stage": self.stage}


class Jobs:
    def __init__(self, settings, clock=time.monotonic):
        self.settings = settings
        self.clock = clock
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=settings.job_workers, thread_name_prefix="spherex")
        self.by_id = {}
        self.by_key = {}
        self.by_session = {}
        self.rate = OrderedDict()
        self.running = set()
        self.saturated = 0
        self.stopping = False
        self.timer = None

    def _rate_limit(self, client, now):
        while self.rate and (next(iter(self.rate.values()))[1] < now - 90 or
                             len(self.rate) >= self.settings.client_state_limit and client not in self.rate):
            self.rate.popitem(last=False)
        capacity = self.settings.client_burst
        tokens, last = self.rate.pop(client, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * self.settings.client_rate / 60)
        if tokens < 1:
            self.rate[client] = (tokens, now)
            wait = max(1, int((1 - tokens) * 60 / self.settings.client_rate + 0.999))
            raise Problem("RATE_LIMIT", "Too many fresh requests. Try again shortly.", 429, True, wait)
        self.rate[client] = (tokens - 1, now)

    def _finish(self, job, response):
        job.response = response
        job.status = response["status"]
        job.finished = self.clock()
        job.work = None
        self.running.discard(job.id)
        self.by_key.pop(job.key, None)
        for requester in job.requesters:
            if self.by_session.get(requester) == job.id:
                self.by_session.pop(requester)
        job.requesters.clear()

    def _expire(self):
        now = self.clock()
        for job in list(self.by_id.values()):
            if job.status == "queued" and now - job.enqueued >= self.settings.queue_seconds:
                problem = Problem("QUEUE_TIMEOUT", "The data queue timed out. Try again shortly.", 503, True, 5)
                self._finish(job, {"status": "failed", "error": problem.payload()})
            if job.finished is not None and now - job.finished >= self.settings.job_ttl:
                self.by_id.pop(job.id)

    def _pump(self):
        if self.stopping:
            return
        self._expire()
        queued = sorted((job for job in self.by_id.values() if job.status == "queued"),
                        key=lambda job: (job.priority, job.enqueued))
        for job in queued:
            if len(self.running) >= self.settings.job_workers:
                break
            if job.extended and any(self.by_id[job_id].extended for job_id in self.running):
                continue
            job.status = "running"
            self.running.add(job.id)
            self.executor.submit(self._run, job)
        waiting = [job.enqueued for job in queued if job.status == "queued"]
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if waiting:
            delay = max(0.01, min(waiting) + self.settings.queue_seconds - self.clock())
            self.timer = threading.Timer(delay, self._tick)
            self.timer.daemon = True
            self.timer.start()

    def _tick(self):
        with self.lock:
            self._pump()

    def _run(self, job):
        started = self.clock()
        try:
            response = job.work()
        except Problem as exc:
            response = {"status": "failed", "error": exc.payload()}
        except Exception:
            LOG.exception("Unhandled failure in %s", job.stage)
            response = {"status": "failed", "error": Problem(
                "PROCESSING_FAILED", "The requested data could not be processed.", 500, True
            ).payload()}
        with self.lock:
            self._finish(job, response)
            self._pump()
            running = len(self.running)
            queued = sum(item.status == "queued" for item in self.by_id.values())
        LOG.info("release=%s job=%s stage=%r outcome=%s reason=%s queued_seconds=%.3f work_seconds=%.3f active=%d queued=%d",
                 self.settings.release, job.id, job.stage, response["status"], response.get("error", {}).get("code", "-"),
                 started - job.enqueued, self.clock() - started, running, queued)

    def submit(self, key, client, session, stage, work, *, extended=False, priority=1, admit=None):
        with self.lock:
            self._expire()
            existing = self.by_key.get(key)
            owned = self.by_session.get(session)
            if owned is not None and (existing is None or owned != existing.id):
                raise Problem("SESSION_BUSY", "Wait for the current request or cancel it and try again.", 429, True, 1)
            if existing is not None:
                existing.requesters.add(session)
                self.by_session[session] = existing.id
                existing.priority = min(priority, existing.priority)
                self._pump()
                return existing.pending()
            if sum(job.status == "queued" for job in self.by_id.values()) >= self.settings.queue_limit:
                self.saturated += 1
                raise Problem("QUEUE_FULL", "The shared data queue is full. Try again shortly.", 503, True, 5)
            if admit is not None:
                admit()
            self._rate_limit(client, self.clock())
            job = Job("j" + secrets.token_urlsafe(15), key, work, stage, extended, priority, self.clock(), {session})
            self.by_id[job.id] = job
            self.by_key[key] = job
            self.by_session[session] = job.id
            self._pump()
            return job.pending()

    def read(self, job_id):
        with self.lock:
            self._expire()
            job = self.by_id.get(job_id)
            if job is None:
                raise Problem("JOB_EXPIRED", "This job has expired. Submit the request again.", 404, True)
            return job.response if job.response is not None else job.pending()

    def capacity_activity(self):
        with self.lock:
            activity = {"activeJobs": len(self.running), "queuedJobs": sum(job.status == "queued" for job in self.by_id.values()),
                        "queueRejections": self.saturated}
            self.saturated = 0
            return activity

    def abandon(self, job_id, session):
        with self.lock:
            job = self.by_id.get(job_id)
            if job is None or session not in job.requesters:
                return
            job.requesters.remove(session)
            if self.by_session.get(session) == job_id:
                self.by_session.pop(session)
            if job.status == "queued" and not job.requesters:
                self._finish(job, {"status": "failed", "error": Problem(
                    "JOB_CANCELLED", "The queued request was cancelled.", 409, True
                ).payload()})
                self._pump()

    def close(self):
        with self.lock:
            self.stopping = True
            if self.timer is not None:
                self.timer.cancel()
        self.executor.shutdown(wait=True, cancel_futures=True)
