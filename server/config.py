"""Local deployment settings and public resource ceilings."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
GIB = 1024 * MIB


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    cache: Path = Path(os.environ.get("SPHEREX_CACHE", Path.home() / ".cache" / "spherex"))
    web: Path = Path(os.environ.get("SPHEREX_WEB", ROOT / "web" / "dist"))
    presets: Path = Path(os.environ.get("SPHEREX_PRESETS", ROOT / "presets"))
    release: str = os.environ.get("SPHEREX_RELEASE", "development")
    job_workers: int = Field(default=2, ge=1, le=2)
    queue_limit: int = Field(default=8, ge=1, le=8)
    queue_seconds: int = Field(default=45, ge=1, le=45)
    job_ttl: int = 600
    client_rate: int = 6
    client_burst: int = 3
    client_state_limit: int = 4096
    body_limit: int = 16 * 1024
    page_size: int = 100
    metadata_ttl: int = 6 * 3600
    stale_ttl: int = 24 * 3600
    empty_ttl: int = 600
    catalog_ttl: int = 24 * 3600
    derived_limit: int = 4 * GIB
    disk_reserve: int = Field(default=int(os.environ.get("SPHEREX_DISK_RESERVE_BYTES", 20 * GIB)), ge=0)
    irsa_daily_bytes: int = 8 * GIB
    catalog_daily_bytes: int = 128 * MIB


SETTINGS = Settings()
