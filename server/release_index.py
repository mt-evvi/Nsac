"""Daily bounded inventory of the documented public IRSA release mirror."""

import logging
import re
import time
from urllib.parse import urlencode
from xml.etree import ElementTree

from .archive import COLLECTIONS
from .contracts import Problem, ready
from .upstream import IRSA_CLOUD, TransferBudget, fetch

LOG = logging.getLogger("uvicorn.error.spherex.release_index")
PERIOD = 86400
LIMIT = 128 * 1024
RELEASE_PREFIX = re.compile(r"((?:dr|qr)[0-9]+)/\Z")
PLANNING_PERIOD = re.compile(r"(20[0-9]{2}W[0-9]{2}_[0-9][A-Z])/\Z")


def list_prefixes(prefix, budget, deadline):
    query = urlencode({"list-type": "2", "delimiter": "/", "max-keys": "256", "prefix": prefix})
    data = fetch(f"https://{IRSA_CLOUD}/?{query}", limit=LIMIT, deadline=deadline, purpose="release-index", budget=budget)
    try:
        result = ElementTree.fromstring(data)
        if result.findtext("{*}Prefix", default="") != prefix or result.findtext("{*}IsTruncated") != "false":
            raise ValueError("Incomplete listing")
        return [item.text for item in result.findall("{*}CommonPrefixes/{*}Prefix") if item.text]
    except (ElementTree.ParseError, ValueError) as exc:
        raise Problem("RELEASE_INDEX_UNAVAILABLE", "IRSA returned an incomplete release listing.", 503, True) from exc


def inventory():
    active = {release.lower() for _, release, _ in COLLECTIONS}
    requests = 1 + len(active)
    budget = TransferBudget(requests * LIMIT, requests)
    deadline = time.monotonic() + 20
    seen = {match[1] for path in list_prefixes("", budget, deadline) if (match := RELEASE_PREFIX.fullmatch(path))}
    periods = {}
    for release in sorted(active):
        prefix = f"{release}/level2/"
        names = [match[1] for path in list_prefixes(prefix, budget, deadline)
                 if path.startswith(prefix) and (match := PLANNING_PERIOD.fullmatch(path.removeprefix(prefix)))]
        if not names or release not in seen:
            raise Problem("RELEASE_INDEX_UNAVAILABLE", f"IRSA did not list planning periods for {release.upper()}.", 503, True)
        periods[release.upper()] = {"count": len(names), "latestPlanningPeriod": max(names)}
    return {"published": sorted(release.upper() for release in seen), "planningPeriods": periods,
            "transferBytes": budget.bytes}


def schedule_if_due(service):
    attempt = service.store.get("release-index", "attempt")
    if attempt is not None and attempt[1] < PERIOD:
        return
    service.store.check_capacity()
    service.jobs.submit("release-index", "host", "host-release-index", "checking the IRSA release index",
                        lambda: refresh(service.store), priority=3)


def refresh(store):
    try:
        snapshot = inventory()
    except Problem as exc:
        store.put("release-index", "attempt", {"checkedAtUnix": int(time.time()), "status": "failed", "reason": exc.code})
        raise
    checked = int(time.time())
    store.put("release-index", "snapshot", {"checkedAtUnix": checked, **snapshot})
    store.put("release-index", "attempt", {"checkedAtUnix": checked, "status": "succeeded"})
    LOG.info("release_index published=%s periods=%s bytes=%d", snapshot["published"], snapshot["planningPeriods"], snapshot["transferBytes"])
    return ready(snapshot)
