from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from types import SimpleNamespace

from stockmonitor.base import ScannerBase


class DummyScanner(ScannerBase):
    RETAILER_NAME = "Dummy"
    FILE_PREFIX = "dummy"
    ENV_PREFIX = "DUMMY"
    CONFIG_KEY = "dummy"

    def scan(self, ctx, args) -> dict:
        return {"stores": {}, "completed": True, "blocked": 0, "extra": {}}

    @contextmanager
    def open_context(self, args):
        yield None

    def add_arguments(self, parser) -> None:
        pass

    def store_url(self, store: dict) -> str:
        return store.get("url", "")


def test_paths_and_env_name_use_scanner_identity(tmp_path):
    scanner = DummyScanner()
    paths = scanner.paths(SimpleNamespace(data_dir=tmp_path))

    assert paths["state"] == tmp_path / "dummy_state.json"
    assert scanner.env_name("MESSAGE") == "DUMMY_MESSAGE"


def test_handle_alerts_replaces_state_after_completed_scan_and_notifies(tmp_path):
    scanner = DummyScanner()
    args = SimpleNamespace(data_dir=tmp_path, product_ref="ref", notify_cmd=None)
    paths = scanner.paths(args)
    paths["state"].write_text(
        json.dumps({"in_stock": ["old-store"], "online_available": False}),
        encoding="utf-8",
    )
    calls = []
    scanner.notify = lambda fresh_stores, fresh_online, result, args: calls.append(
        (fresh_stores, fresh_online)
    )

    result = {
        "stores": {},
        "completed": True,
        "blocked": 0,
        "extra": {"online": {"available": True, "home_delivery": "Available"}},
    }
    in_stock = [
        {
            "id": "new-store",
            "name": "New Store",
            "state": "IN",
            "restock": True,
            "url": "https://example.com/store",
        }
    ]

    fresh_stores, fresh_online = scanner.handle_alerts(in_stock, result, args)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))

    assert [s["id"] for s in fresh_stores] == ["new-store"]
    assert fresh_online is True
    assert calls == [(in_stock, True)]
    assert state["in_stock"] == ["new-store"]
    assert state["online_available"] is True
    assert state["last_scan_completed"] is True


def test_handle_alerts_keeps_previous_restock_after_partial_scan(tmp_path):
    scanner = DummyScanner()
    args = SimpleNamespace(data_dir=tmp_path, product_ref="ref", notify_cmd=None)
    paths = scanner.paths(args)
    paths["state"].write_text(json.dumps({"in_stock": ["old-store"]}), encoding="utf-8")
    notified = []
    scanner.notify = lambda fresh_stores, fresh_online, result, args: notified.extend(
        fresh_stores
    )

    result = {"stores": {}, "completed": False, "blocked": 1, "extra": {}}
    in_stock = [
        {
            "id": "new-store",
            "name": "New Store",
            "state": "IN",
            "restock": True,
            "url": "https://example.com/store",
        }
    ]

    fresh_stores, fresh_online = scanner.handle_alerts(in_stock, result, args)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))

    assert [s["id"] for s in fresh_stores] == ["new-store"]
    assert fresh_online is False
    assert [s["id"] for s in notified] == ["new-store"]
    assert state["in_stock"] == ["new-store", "old-store"]
    assert state["last_scan_completed"] is False


def test_persist_outputs_writes_json_csv_and_history(tmp_path):
    scanner = DummyScanner()
    args = SimpleNamespace(data_dir=tmp_path, product_ref="ref")
    result = {
        "stores": {
            "b": {
                "id": "b",
                "name": "Beta",
                "state": "OUT",
                "status_text": "rupture",
                "distance_km": 2,
                "restock": False,
                "url": "https://example.com/b",
            },
            "a": {
                "id": "a",
                "name": "Alpha",
                "state": "IN",
                "status_text": "dispo",
                "distance_km": 1,
                "restock": True,
                "url": "https://example.com/a",
            },
        },
        "completed": True,
        "blocked": 0,
        "extra": {},
    }

    scanner.persist_outputs(result, args)
    paths = scanner.paths(args)

    last_run = json.loads(paths["last_run_json"].read_text(encoding="utf-8"))
    assert last_run["retailer"] == "Dummy"
    assert last_run["product_ref"] == "ref"
    assert last_run["stores"]["a"]["restock"] is True

    with paths["last_run_csv"].open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["id", "magasin", "etat", "statut_texte", "distance_km", "url"]
    assert rows[1][1] == "Alpha"
    assert rows[2][1] == "Beta"

    history = json.loads(paths["history"].read_text(encoding="utf-8"))
    assert history["in_stock"] == ["a"]
    assert history["total"] == 2
    assert history["completed"] is True
