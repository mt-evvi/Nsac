"""Versioned bounded storage for manifests, science arrays, and derived assets."""

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

import numpy as np

from .contracts import Problem

CACHE_SCHEMA = "v1"


def content_key(*parts):
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".staging-", delete=False) as f:
        staging = Path(f.name)
        try:
            f.write(payload)
            f.flush()
            f.close()
            os.replace(staging, path)
        finally:
            staging.unlink(missing_ok=True)


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.cache / CACHE_SCHEMA
        self.assets = self.root / "assets"
        self.presets = settings.web / "presets"
        if not self.presets.is_dir():
            self.presets = settings.web.parent / "public" / "presets"
        self.arrays = settings.presets
        self.assets.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "cache.sqlite3"
        with closing(self.connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, key TEXT NOT NULL, value BLOB NOT NULL,
                    created REAL NOT NULL, accessed REAL NOT NULL,
                    PRIMARY KEY (kind, key)
                );
                CREATE TABLE IF NOT EXISTS files (
                    name TEXT PRIMARY KEY, size INTEGER NOT NULL, accessed REAL NOT NULL
                );
            """)

    def connect(self):
        return sqlite3.connect(self.db, timeout=5)

    def get(self, kind, key):
        with closing(self.connect()) as conn, conn:
            row = conn.execute("SELECT value, created FROM records WHERE kind = ? AND key = ?", (kind, key)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE records SET accessed = ? WHERE kind = ? AND key = ?", (time.time(), kind, key))
        return json.loads(row[0]), max(0, time.time() - row[1])

    def put(self, kind, key, value):
        payload = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        now = time.time()
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?, ?)", (kind, key, payload, now, now))
        self.prune()

    def set_if_absent(self, kind, key, value):
        payload = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        now = time.time()
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT OR IGNORE INTO records VALUES (?, ?, ?, ?, ?)", (kind, key, payload, now, now))

    def check_capacity(self):
        if shutil.disk_usage(self.root).free < self.settings.disk_reserve:
            self.prune(reserve=True)
        if shutil.disk_usage(self.root).free < self.settings.disk_reserve:
            raise Problem("DISK_LIMIT", "Data preparation is paused while cache space is recovered.", 503, True, 60)

    def prune(self, reserve=False):
        with closing(self.connect()) as conn, conn:
            now = time.time()
            conn.execute("DELETE FROM records WHERE kind IN ('series','catalog') AND accessed < ?", (now - 48 * 3600,))
            record_bytes = conn.execute("SELECT COALESCE(SUM(length(value)), 0) FROM records").fetchone()[0]
            file_bytes = conn.execute("SELECT COALESCE(SUM(size), 0) FROM files").fetchone()[0]
            excess = record_bytes + file_bytes - self.settings.derived_limit
            if reserve:
                excess = max(excess, self.settings.disk_reserve - shutil.disk_usage(self.root).free)
            if excess <= 0:
                return
            for name, size in conn.execute("SELECT name, size FROM files ORDER BY accessed").fetchall():
                (self.assets / name).unlink(missing_ok=True)
                conn.execute("DELETE FROM files WHERE name = ?", (name,))
                excess -= size
                if excess <= 0:
                    return
            for kind, key, size in conn.execute("SELECT kind,key,length(value) FROM records ORDER BY accessed").fetchall():
                conn.execute("DELETE FROM records WHERE kind = ? AND key = ?", (kind, key))
                excess -= size
                if excess <= 0:
                    return

    def write_asset(self, payload, ext):
        if ext not in {"png", "npz"}:
            raise ValueError("Unknown asset format")
        stem = hashlib.sha256(payload).hexdigest()[:32]
        name = f"{stem}.{ext}"
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            path = self.assets / name
            if not path.exists():
                atomic_write(path, payload)
            conn.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?)", (name, len(payload), time.time()))
        return name

    def public_asset(self, name):
        if not name.endswith(".png"):
            return None
        return self._asset(name)

    def _asset(self, name):
        path = self.assets / name
        if not path.is_file():
            return None
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE files SET accessed = ? WHERE name = ?", (time.time(), name))
        return path

    def preset(self, series_id):
        if not series_id.startswith("preset-"):
            return None
        path = self.presets / series_id.removeprefix("preset-") / "manifest.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_arrays(self, series_id, frame):
        cached = self.get("frame", f"{series_id}:{frame['frameId']}")
        if cached:
            path = self._asset(cached[0]["arrayFile"])
        elif series_id.startswith("preset-"):
            path = self.arrays / series_id.removeprefix("preset-") / f"{frame['frameId']}.npz"
        else:
            path = None
        if path is None or not path.is_file():
            raise Problem("FRAME_NOT_PREPARED", "Prepare the selected frame before running analysis.", 409, True)
        with np.load(path, allow_pickle=False) as arrays:
            return {name: arrays[name] for name in arrays.files}

    def save_frame(self, series_id, frame, arrays, png, mask):
        if len(png) > 256 * 1024 or len(mask) > 256 * 1024:
            raise Problem("LIMIT_REACHED", "The frame exceeds the maximum display size.")
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        data = dict(frame, imageUrl=f"/data/{self.write_asset(png, 'png')}",
                    maskUrl=f"/data/{self.write_asset(mask, 'png')}")
        stored = {"frame": data, "arrayFile": self.write_asset(buffer.getvalue(), "npz")}
        self.put("frame", f"{series_id}:{frame['frameId']}", stored)
        return data

    def prepared(self, series_id, frame_id):
        row = self.get("frame", f"{series_id}:{frame_id}")
        if row:
            frame = row[0]["frame"]
            image = self._asset(frame["imageUrl"].rsplit("/", 1)[1])
            mask = self._asset(frame["maskUrl"].rsplit("/", 1)[1])
            if image and mask and self._asset(row[0]["arrayFile"]):
                return frame
        return None
