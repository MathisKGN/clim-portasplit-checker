from __future__ import annotations

import csv
import json

import pytest

from stockmonitor.common import (
    aggregate,
    append_history,
    ean_from_url,
    load_state,
    normalize_text,
    order_core_first,
    save_json,
    short_loop_warning,
    write_csv,
)


def test_normalize_text_is_case_and_accent_insensitive():
    assert normalize_text("Epuisé A CRETEIL") == "epuise a creteil"


def test_ean_from_url_extracts_default_casto_pattern():
    assert (
        ean_from_url("https://www.castorama.fr/x/8431312260509_CAFR.prd")
        == "8431312260509"
    )


def test_ean_from_url_raises_on_missing_identifier():
    with pytest.raises(ValueError, match="Impossible d'extraire"):
        ean_from_url("https://example.com/product/no-ean")


def test_aggregate_adds_new_stores_and_promotes_restock():
    all_stores = {}

    assert aggregate({"a": {"id": "a", "restock": False}}, all_stores) == 1
    assert all_stores["a"]["restock"] is False

    assert aggregate({"a": {"id": "a", "restock": True}}, all_stores) == 0
    assert all_stores["a"]["restock"] is True

    assert aggregate({"a": {"id": "a", "restock": False}}, all_stores) == 0
    assert all_stores["a"]["restock"] is True


def test_short_loop_warning_formats_minutes_and_seconds():
    assert "5 min" in short_loop_warning(300)
    assert "45 s" in short_loop_warning(45)


def test_order_core_first_sorts_nearest_seed_first():
    seeds = [("far", 49.0, 3.0), ("near", 48.86, 2.35)]

    assert [s[0] for s in order_core_first(seeds, (48.8566, 2.3522))] == [
        "near",
        "far",
    ]


def test_json_csv_and_history_helpers(tmp_path):
    state_path = tmp_path / "state.json"
    save_json(state_path, {"in_stock": ["creteil"]})

    assert load_state(state_path) == {"in_stock": ["creteil"]}

    state_path.write_text("{invalid", encoding="utf-8")
    assert load_state(state_path) == {}

    history_path = tmp_path / "history.jsonl"
    append_history(history_path, {"total": 2})
    assert json.loads(history_path.read_text(encoding="utf-8")) == {"total": 2}

    csv_path = tmp_path / "last_run.csv"
    write_csv(csv_path, ["id", "name"], [["1", "Paris"]])
    with csv_path.open(newline="", encoding="utf-8") as f:
        assert list(csv.reader(f)) == [["id", "name"], ["1", "Paris"]]
