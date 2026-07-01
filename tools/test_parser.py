"""Tests offline du parseur LM sur un fragment HTML reproduisant la structure réelle.

Cible le nouveau package stockmonitor/ (cf. stockmonitor/retailers/lm.py).
Pour exécuter : `python tools/test_parser.py` (depuis la racine du projet).
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stockmonitor.retailers import lm as lmmod
from stockmonitor.retailers.lm import LmScanner

SAMPLE = """
<section class="m-store-search-result">
  <div class="m-store-search-result__main-store">
    <div class="m-store-info-header">
      <h3 class="m-store-search-result__main-store--title">Paris-Beaubourg</h3>
    </div>
    <div class="stock-status">
      <span class="stock-status__badge stock-status__badge--red"></span>
      <span class="stock-status__text">Actuellement indisponible</span>
    </div>
    <a href="/magasins/paris-beaubourg.html">Infos magasin</a>
  </div>
  <ul>
    <li><div class="m-store-search-card">
      <div class="m-store-info-header"><h3 class="m-store-info-header__title">Meaux</h3><span>12,5 km</span></div>
      <div class="stock-status">
        <span class="stock-status__badge stock-status__badge--red"></span>
        <span class="stock-status__text">Actuellement indisponible</span>
      </div>
      <a href="/magasins/meaux.html">Infos magasin</a>
    </div></li>
    <li><div class="m-store-search-card">
      <div class="m-store-info-header"><h3 class="m-store-info-header__title">Versailles</h3><span>30,1 km</span></div>
      <div class="stock-status">
        <span class="stock-status__badge stock-status__badge--green"></span>
        <span class="stock-status__text">Disponible</span>
      </div>
      <a href="/magasins/versailles.html">Infos magasin</a>
    </div></li>
    <li><div class="m-store-search-card">
      <div class="m-store-info-header"><h3 class="m-store-info-header__title">Créteil</h3><span>18,0 km</span></div>
      <div class="stock-status">
        <span class="stock-status__badge stock-status__badge--orange"></span>
        <span class="stock-status__text">Plus que 2 en stock</span>
      </div>
      <a href="/magasins/creteil.html">Infos magasin</a>
    </div></li>
  </ul>
</section>
"""


# --------------------------------------------------------------------------- #
# 1. Parser + classify + détection de blocage (fonctions pures)
# --------------------------------------------------------------------------- #
def test_parser_basic():
    stores = lmmod._parse_stores(SAMPLE)
    assert len(stores) == 4, f"attendu 4 magasins, obtenu {len(stores)}"
    assert stores["paris-beaubourg"]["state"] == "OUT"
    assert stores["meaux"]["state"] == "OUT"
    assert stores["meaux"]["distance_km"] == "12.5"
    assert stores["versailles"]["restock"] is True
    assert stores["creteil"]["restock"] is True
    print(f"  ✓ parser : {len(stores)} magasins correctement classés")

    assert lmmod.looks_blocked(503, "<html>datadome</html>") is True
    assert lmmod.looks_blocked(200, "<html>captcha</html>") is True
    assert lmmod.looks_blocked(200, SAMPLE) is False

    cls = lmmod._classify
    assert cls("Actuellement indisponible", "stock-status__badge--red")[0] == "OUT"
    assert cls("Disponible", "stock-status__badge--green")[1] is True
    assert cls("", "")[0] == "UNKNOWN"
    assert cls("", "stock-status__badge")[0] == "UNKNOWN"
    assert cls("Bientôt disponible", "stock-status__badge--grey")[0] == "UNKNOWN"
    assert cls("Retrait magasin non disponible", "stock-status__badge--green")[0] == "OUT"
    print("  ✓ looks_blocked + classify : comportements validés")


# --------------------------------------------------------------------------- #
# 2. Mode lent (--slow) : un challenge HTTP 200 déclenche un retry (sans warmup)
# --------------------------------------------------------------------------- #
def test_sequential_recovers_http_200_challenge():
    scanner = LmScanner()
    original_seeds = lmmod.SEEDS_IDF
    original_fetch_seed = lmmod._fetch_seed
    original_sleep = lmmod.sleep_between
    original_new_page = scanner._new_page
    sleeps: list[bool] = []
    responses = iter([
        (200, "<html><title>DataDome</title>captcha</html>"),
        (200, SAMPLE),
    ])
    try:
        lmmod.SEEDS_IDF = [("Seed test", 48.0, 2.0)]
        scanner._new_page = lambda ctx, args: object()  # pas de vrai navigateur
        lmmod._fetch_seed = lambda page, lat, lon, ref: next(responses)
        lmmod.sleep_between = lambda args, long=False: sleeps.append(long)
        args = SimpleNamespace(
            product_ref="93857579", zone="idf", max_seeds=0, max_blocks=6,
            min_delay=0, max_delay=0, slow=True,
            tries_per_seed=3, stable_rounds=0, wide=False,
        )
        result = scanner.scan(object(), args)
    finally:
        lmmod.SEEDS_IDF = original_seeds
        scanner._new_page = original_new_page
        lmmod._fetch_seed = original_fetch_seed
        lmmod.sleep_between = original_sleep

    # 1 backoff (long=True) entre le 1er échec et le retry réussi.
    assert sleeps == [True], f"attendu 1 sleep long, obtenu {sleeps}"
    assert result["completed"] is True
    assert result["blocked"] == 0
    assert len(result["stores"]) == 4
    print("  ✓ mode lent : 1 challenge HTTP 200 -> 1 retry, 4 magasins")


# --------------------------------------------------------------------------- #
# 3. Mode rafale (défaut) : retry des points bloqués après backoff
# --------------------------------------------------------------------------- #
def test_batch_retries_blocked_points():
    scanner = LmScanner()
    original_seeds = lmmod.SEEDS_IDF
    original_batch = lmmod._batch_fetch
    original_sleep = lmmod.sleep_between
    original_new_page = scanner._new_page
    sleeps: list[bool] = []
    batches = iter([
        [(200, SAMPLE), (200, "<html>captcha datadome</html>")],
        [(200, SAMPLE)],
    ])
    try:
        lmmod.SEEDS_IDF = [("A", 48.0, 2.0), ("B", 49.0, 3.0)]
        scanner._new_page = lambda ctx, args: object()
        lmmod._batch_fetch = lambda page, coords, ref, batch_size=8: next(batches)
        lmmod.sleep_between = lambda args, long=False: sleeps.append(long)
        args = SimpleNamespace(
            product_ref="93857579", zone="idf", max_seeds=0, slow=False,
            batch_size=8, tries_per_seed=3, min_delay=0, max_delay=0,
            max_blocks=6, wide=False, stable_rounds=0,
        )
        result = scanner.scan(object(), args)
    finally:
        lmmod.SEEDS_IDF = original_seeds
        scanner._new_page = original_new_page
        lmmod._batch_fetch = original_batch
        lmmod.sleep_between = original_sleep

    # 1 backoff (long=True) avant le retry du point bloqué.
    assert sleeps == [True], f"attendu 1 sleep long, obtenu {sleeps}"
    assert result["completed"] is True
    assert result["blocked"] == 0
    assert len(result["stores"]) == 4
    print("  ✓ mode rafale : retry du point bloqué après backoff, 4 magasins")


# --------------------------------------------------------------------------- #
# 4. --tries-per-seed honoré en rafale : break tôt si aucun progrès
# --------------------------------------------------------------------------- #
def test_batch_honors_tries_per_seed():
    scanner = LmScanner()
    original_seeds = lmmod.SEEDS_IDF
    original_batch = lmmod._batch_fetch
    original_sleep = lmmod.sleep_between
    original_new_page = scanner._new_page
    blocked_body = "<html>geo.captcha-delivery.com</html>"
    batches = iter([
        [(200, SAMPLE), (200, blocked_body)],
        [(200, blocked_body)],
    ])
    n_calls = {"v": 0}

    def fake_batch(page, coords, ref, batch_size=8):
        n_calls["v"] += 1
        return next(batches)

    try:
        lmmod.SEEDS_IDF = [("A", 48.0, 2.0), ("B", 49.0, 3.0)]
        scanner._new_page = lambda ctx, args: object()
        lmmod._batch_fetch = fake_batch
        lmmod.sleep_between = lambda args, long=False: None
        args = SimpleNamespace(
            product_ref="93857579", zone="idf", max_seeds=0, slow=False,
            batch_size=8, tries_per_seed=2, min_delay=0, max_delay=0,
            max_blocks=6, wide=False, stable_rounds=0,
        )
        result = scanner.scan(object(), args)
    finally:
        lmmod.SEEDS_IDF = original_seeds
        scanner._new_page = original_new_page
        lmmod._batch_fetch = original_batch
        lmmod.sleep_between = original_sleep

    assert n_calls["v"] == 2, f"attendu 2 appels batch_fetch, obtenu {n_calls['v']}"
    assert result["blocked"] == 1
    assert result["completed"] is False
    assert len(result["stores"]) == 4
    print("  ✓ --tries-per-seed : break tôt sans progrès, 1 point reste bloqué")


# --------------------------------------------------------------------------- #
# 5. Scan incomplet préserve les anciens restocks dans state.json
# --------------------------------------------------------------------------- #
def test_partial_scan_keeps_previous_alert_state():
    scanner = LmScanner()
    original_notify = scanner.notify
    notified: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            scanner.notify = lambda fresh_stores, fresh_online, result, args: notified.extend(fresh_stores)
            state_path = Path(tmp) / scanner.paths(SimpleNamespace(data_dir=tmp)).get("state").name
            state_path.write_text(json.dumps({"in_stock": ["old-store"]}),
                                  encoding="utf-8")
            args = SimpleNamespace(data_dir=tmp, product_ref="93857579",
                                   notify_cmd=None)
            result = {"stores": {}, "completed": False, "blocked": 1,
                      "extra": {}}
            # un restock frais signalé sur le scan incomplet
            in_stock = [{"slug": "new-store", "id": "new-store", "name": "New Store",
                         "state": "IN", "restock": True}]
            fresh_stores, _ = scanner.handle_alerts(in_stock, result, args)
            state = json.loads(state_path.read_text(encoding="utf-8"))
        finally:
            scanner.notify = original_notify

    assert [s["slug"] for s in fresh_stores] == ["new-store"]
    assert [s["slug"] for s in notified] == ["new-store"]
    assert state["in_stock"] == ["new-store", "old-store"]
    assert state["last_scan_completed"] is False
    print("  ✓ état partiel : ancien restock conservé dans state.json")


if __name__ == "__main__":
    print("Tests du parseur Leroy Merlin :")
    test_parser_basic()
    test_sequential_recovers_http_200_challenge()
    test_batch_retries_blocked_points()
    test_batch_honors_tries_per_seed()
    test_partial_scan_keeps_previous_alert_state()
    print("\n✅ Tous les tests passent.")
