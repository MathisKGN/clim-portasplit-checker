from __future__ import annotations

import asyncio
import threading

from stockmonitor.interactive import (
    _apply_scan_area_overrides,
    _build_namespace,
    _load_cached_center,
    _load_last_postcode,
    _run_scanner_once_isolated,
    _save_last_postcode,
)


def test_interactive_prefs_store_postcode_and_center(tmp_path):
    _save_last_postcode(tmp_path, "94000", (48.784506, 2.452976))

    assert _load_last_postcode(tmp_path) == "94000"
    assert _load_cached_center(tmp_path, "94000") == (48.784506, 2.452976)
    assert _load_cached_center(tmp_path, "75001") is None


def test_build_namespace_carries_shared_scan_area():
    ns = _build_namespace(
        {
            "postcode": "59000",
            "area_center": (50.62925, 3.057256),
            "radius_km": 15,
            "zone_label": "59000 · 15 km",
            "custom_seeds": [("Lille", 50.6292, 3.0573)],
        },
        {},
    )

    assert ns.postcode == "59000"
    assert ns.area_center == (50.62925, 3.057256)
    assert ns.radius_km == 15
    assert ns.zone_label == "59000 · 15 km"
    assert ns.custom_seeds == [("Lille", 50.6292, 3.0573)]


def test_apply_scan_area_overrides_feeds_lm_and_casto_from_same_area():
    overrides = {}
    area = {
        "postcode": "59000",
        "area_center": (50.62925, 3.057256),
        "radius_km": 15,
        "zone_label": "59000 · 15 km",
        "custom_seeds": [("Lille", 50.6292, 3.0573)],
    }

    _apply_scan_area_overrides(overrides, area)

    assert overrides == {
        "postcode": "59000",
        "area_center": (50.62925, 3.057256),
        "radius_km": 15,
        "zone_label": "59000 · 15 km",
        "zone": "59000 · 15 km",
        "custom_seeds": [("Lille", 50.6292, 3.0573)],
    }


def test_run_scanner_once_isolated_avoids_calling_thread_asyncio_loop():
    main_thread_id = threading.get_ident()

    class LoopSensitiveScanner:
        CONFIG_KEY = "test"
        prefix = "test"

        def run_once(self, _ns):
            assert threading.get_ident() != main_thread_id
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                loop_running = False
            else:
                loop_running = True
            return {"loop_running": loop_running}

    async def run_from_active_loop():
        assert asyncio.get_running_loop().is_running()
        return _run_scanner_once_isolated(LoopSensitiveScanner(), object())

    assert asyncio.run(run_from_active_loop()) == {"loop_running": False}
