from __future__ import annotations

from stockmonitor.interactive import (
    _apply_scan_area_overrides,
    _build_namespace,
    _load_cached_center,
    _load_last_postcode,
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
