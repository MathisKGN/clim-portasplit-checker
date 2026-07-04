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
# Helpers scanner HTTP offline
# --------------------------------------------------------------------------- #
class FakeLmSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.fetch_calls = 0
        self.remints = 0

    def mint(self, lat, lon):
        return next(self.responses)

    def fetch_stock(self, lat, lon):
        self.fetch_calls += 1
        return next(self.responses)

    def remint(self):
        self.remints += 1

    def _is_cookie_dead(self, status: int, body: str) -> bool:
        return status == 403 or (status == 200 and ("datadome" in body.lower() or "captcha" in body.lower()))


def _scan_args(seeds):
    return SimpleNamespace(
        product_ref="93857579",
        product_url=lmmod.DEFAULT_PRODUCT_URL,
        zone="idf",
        custom_seeds=seeds,
        zone_label="test",
        max_seeds=0,
        max_blocks=6,
        min_delay=0,
        max_delay=0,
        stable_rounds=0,
        wide=False,
    )


def test_http_scan_uses_mint_body_then_fetches_remaining_seeds():
    scanner = LmScanner()
    scanner._pause = lambda args, long=False: None
    sess = FakeLmSession([(200, SAMPLE), (200, SAMPLE)])
    args = _scan_args([("A", 48.0, 2.0), ("B", 49.0, 3.0)])

    result = scanner.scan(sess, args)

    assert sess.fetch_calls == 1, f"attendu 1 fetch après le mint, obtenu {sess.fetch_calls}"
    assert sess.remints == 0
    assert result["completed"] is True
    assert result["blocked"] == 0
    assert result["extra"]["engine"] == "http"
    assert len(result["stores"]) == 4
    print("  ✓ scan HTTP : body du mint réutilisé, seeds suivants fetchés")


def test_http_scan_remints_once_after_mint_challenge():
    scanner = LmScanner()
    scanner._pause = lambda args, long=False: None
    sess = FakeLmSession([
        (200, "<html><title>DataDome</title>captcha</html>"),
        (200, SAMPLE),
    ])
    args = _scan_args([("A", 48.0, 2.0)])

    result = scanner.scan(sess, args)

    assert sess.remints == 1, f"attendu 1 remint, obtenu {sess.remints}"
    assert sess.fetch_calls == 1
    assert result["completed"] is True
    assert result["blocked"] == 0
    assert len(result["stores"]) == 4
    print("  ✓ scan HTTP : challenge au mint -> remint unique puis succès")


def test_http_scan_stops_on_max_blocks():
    scanner = LmScanner()
    scanner._pause = lambda args, long=False: None
    sess = FakeLmSession([(200, SAMPLE), (503, "<html>service unavailable</html>"), (200, SAMPLE)])
    args = _scan_args([("A", 48.0, 2.0), ("B", 49.0, 3.0), ("C", 50.0, 4.0)])
    args.max_blocks = 1

    result = scanner.scan(sess, args)

    assert sess.fetch_calls == 1, f"le scan aurait dû s'arrêter après 1 blocage, obtenu {sess.fetch_calls}"
    assert result["blocked"] == 1
    assert result["completed"] is False
    assert len(result["stores"]) == 4
    print("  ✓ scan HTTP : arrêt au seuil max_blocks")


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
    test_http_scan_uses_mint_body_then_fetches_remaining_seeds()
    test_http_scan_remints_once_after_mint_challenge()
    test_http_scan_stops_on_max_blocks()
    test_partial_scan_keeps_previous_alert_state()
    print("\n✅ Tous les tests passent.")
