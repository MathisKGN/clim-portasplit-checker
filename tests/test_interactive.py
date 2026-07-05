from __future__ import annotations

from stockmonitor.interactive import (
    _load_cached_center,
    _load_last_postcode,
    _save_last_postcode,
)


def test_interactive_prefs_store_postcode_and_center(tmp_path):
    _save_last_postcode(tmp_path, "94000", (48.784506, 2.452976))

    assert _load_last_postcode(tmp_path) == "94000"
    assert _load_cached_center(tmp_path, "94000") == (48.784506, 2.452976)
    assert _load_cached_center(tmp_path, "75001") is None
