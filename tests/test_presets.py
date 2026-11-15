"""Integrity checks for the archive-outage playback fixtures."""

import pytest

from tools.build_presets import CATALOG
from tools.verify_presets import verify


@pytest.mark.parametrize("slug", list(CATALOG))
def test_bundled_observations(slug):
    verify(slug)
