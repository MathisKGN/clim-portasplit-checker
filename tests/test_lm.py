from __future__ import annotations

from types import SimpleNamespace

import pytest

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
      <div class="m-store-info-header">
        <h3 class="m-store-info-header__title">Meaux</h3><span>12,5 km</span>
      </div>
      <div class="stock-status">
        <span class="stock-status__badge stock-status__badge--red"></span>
        <span class="stock-status__text">Actuellement indisponible</span>
      </div>
      <a href="/magasins/meaux.html">Infos magasin</a>
    </div></li>
    <li><div class="m-store-search-card">
      <div class="m-store-info-header">
        <h3 class="m-store-info-header__title">Versailles</h3><span>30,1 km</span>
      </div>
      <div class="stock-status">
        <span class="stock-status__badge stock-status__badge--green"></span>
        <span class="stock-status__text">Disponible</span>
      </div>
      <a href="/magasins/versailles.html">Infos magasin</a>
    </div></li>
    <li><div class="m-store-search-card">
      <div class="m-store-info-header">
        <h3 class="m-store-info-header__title">Creteil</h3><span>18,0 km</span>
      </div>
      <div class="stock-status">
        <span class="stock-status__badge stock-status__badge--orange"></span>
        <span class="stock-status__text">Plus que 2 en stock</span>
      </div>
      <a href="/magasins/creteil.html">Infos magasin</a>
    </div></li>
  </ul>
</section>
"""


def test_parse_stores_extracts_stock_statuses_and_distances():
    stores = lmmod._parse_stores(SAMPLE)

    assert len(stores) == 4
    assert stores["paris-beaubourg"]["state"] == "OUT"
    assert stores["meaux"]["state"] == "OUT"
    assert stores["meaux"]["distance_km"] == "12.5"
    assert stores["versailles"]["restock"] is True
    assert stores["creteil"]["restock"] is True


@pytest.mark.parametrize(
    ("status_text", "badge_classes", "expected"),
    [
        ("Actuellement indisponible", "stock-status__badge--red", ("OUT", False)),
        ("Disponible", "stock-status__badge--green", ("IN", True)),
        ("", "", ("UNKNOWN", False)),
        ("", "stock-status__badge", ("UNKNOWN", False)),
        ("Bientot disponible", "stock-status__badge--grey", ("UNKNOWN", False)),
        ("Retrait magasin non disponible", "stock-status__badge--green", ("OUT", False)),
    ],
)
def test_classify_lm_status_variants(status_text, badge_classes, expected):
    assert lmmod._classify(status_text, badge_classes) == expected


def test_looks_blocked_detects_bad_endpoint_responses():
    assert lmmod.looks_blocked(503, "<html>datadome</html>") is True
    assert lmmod.looks_blocked(200, "<html>captcha</html>") is True
    assert lmmod.looks_blocked(200, SAMPLE) is False
    assert lmmod.looks_blocked(200, "") is False


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
        return status == 403 or (
            status == 200 and ("datadome" in body.lower() or "captcha" in body.lower())
        )


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


def _scanner_without_sleep():
    scanner = LmScanner()
    scanner._pause = lambda args, long=False: None
    return scanner


def test_http_scan_uses_mint_body_then_fetches_remaining_seeds():
    scanner = _scanner_without_sleep()
    sess = FakeLmSession([(200, SAMPLE), (200, SAMPLE)])
    args = _scan_args([("A", 48.0, 2.0), ("B", 49.0, 3.0)])

    result = scanner.scan(sess, args)

    assert sess.fetch_calls == 1
    assert sess.remints == 0
    assert result["completed"] is True
    assert result["blocked"] == 0
    assert result["extra"]["engine"] == "http"
    assert len(result["stores"]) == 4


def test_http_scan_remints_once_after_mint_challenge():
    scanner = _scanner_without_sleep()
    sess = FakeLmSession(
        [
            (200, "<html><title>DataDome</title>captcha</html>"),
            (200, SAMPLE),
        ]
    )
    args = _scan_args([("A", 48.0, 2.0)])

    result = scanner.scan(sess, args)

    assert sess.remints == 1
    assert sess.fetch_calls == 1
    assert result["completed"] is True
    assert result["blocked"] == 0
    assert len(result["stores"]) == 4


def test_http_scan_stops_on_max_blocks():
    scanner = _scanner_without_sleep()
    sess = FakeLmSession(
        [(200, SAMPLE), (503, "<html>service unavailable</html>"), (200, SAMPLE)]
    )
    args = _scan_args([("A", 48.0, 2.0), ("B", 49.0, 3.0), ("C", 50.0, 4.0)])
    args.max_blocks = 1

    result = scanner.scan(sess, args)

    assert sess.fetch_calls == 1
    assert result["blocked"] == 1
    assert result["completed"] is False
    assert len(result["stores"]) == 4


def test_http_scan_stops_after_configured_stable_rounds():
    scanner = _scanner_without_sleep()
    sess = FakeLmSession([(200, SAMPLE), (200, SAMPLE), (200, SAMPLE)])
    args = _scan_args([("A", 48.0, 2.0), ("B", 49.0, 3.0), ("C", 50.0, 4.0)])
    args.stable_rounds = 1

    result = scanner.scan(sess, args)

    assert sess.fetch_calls == 1
    assert result["completed"] is True
    assert len(result["stores"]) == 4
