from __future__ import annotations

from types import SimpleNamespace

import pytest

from stockmonitor.common import ean_from_url
from stockmonitor.retailers import casto as castomod
from stockmonitor.retailers.casto import (
    CastoScanner,
    _classify,
    _filter_store_for_radius,
    _parse_store,
    extract_token,
)


SAMPLE_DATA = [
    {
        "type": "store",
        "id": "1486",
        "attributes": {
            "store": {
                "name": "Castorama Place de Clichy",
                "distance": "3.56 KM",
                "externalId": "1486",
                "seoPath": "/magasins/paris-clichy",
                "geoCoordinates": {
                    "postalCode": "75018",
                    "coordinates": {"latitude": 48.88, "longitude": 2.32},
                },
            },
            "stock": {"products": [{"ean": "X", "stockLevel": "InStock", "quantity": 4}]},
            "clickAndCollect": {
                "summary": {"availability": "AllAvailable", "primaryMessage": "Disponible"}
            },
        },
    },
    {
        "type": "store",
        "id": "1487",
        "attributes": {
            "store": {
                "name": "Castorama Nation",
                "distance": "3.61 KM",
                "geoCoordinates": {"postalCode": "75020", "coordinates": {}},
            },
            "stock": {"products": [{"stockLevel": "OutOfStock", "quantity": 0}]},
            "clickAndCollect": {"summary": {"availability": "AllNotAvailable"}},
        },
    },
    {
        "type": "store",
        "id": "2753",
        "attributes": {
            "store": {
                "name": "Casto Les Lilas",
                "distance": "5.49 KM",
                "geoCoordinates": {"postalCode": "93260", "coordinates": {}},
            },
            "stock": {
                "products": [{"stockLevel": "NotStockedInStore", "quantity": None}]
            },
            "clickAndCollect": {"summary": {"availability": "AllNotAvailable"}},
        },
    },
    {
        "type": "store",
        "id": "1440",
        "attributes": {
            "store": {
                "name": "Castorama Creteil",
                "distance": "10.58 KM",
                "geoCoordinates": {"postalCode": "94000", "coordinates": {}},
            },
            "stock": {"products": [{"stockLevel": "OutOfStock", "quantity": 0}]},
            "clickAndCollect": {
                "summary": {
                    "availability": "SomeAvailable",
                    "primaryMessage": "Disponible en Drive 2h",
                }
            },
        },
    },
]


def test_parse_store_normalizes_kingfisher_api_shape():
    stores = {s["id"]: _parse_store(s) for s in SAMPLE_DATA}

    assert len(stores) == 4
    assert stores["1486"]["state"] == "IN"
    assert stores["1486"]["restock"] is True
    assert stores["1486"]["quantity"] == 4
    assert stores["1486"]["url"] == (
        "https://www.google.com/maps/search/?api=1&query=48.88,2.32"
    )
    assert stores["1486"]["dept"] == "75"
    assert stores["1486"]["distance_km"] == 3.56
    assert stores["1487"]["state"] == "OUT"
    assert stores["1487"]["restock"] is False
    assert stores["2753"]["state"] == "NOT_CARRIED"
    assert stores["1440"]["state"] == "IN"
    assert stores["1440"]["restock"] is True


@pytest.mark.parametrize(
    ("stock_level", "quantity", "cc_availability", "expected"),
    [
        ("InStock", 4, "AllNotAvailable", ("IN", True)),
        ("LimitedStock", None, "AllNotAvailable", ("IN", True)),
        ("OutOfStock", 0, "AllNotAvailable", ("OUT", False)),
        ("OutOfStock", 0, "SomeAvailable", ("IN", True)),
        ("NotStockedInStore", None, "AllNotAvailable", ("NOT_CARRIED", False)),
        ("", None, "", ("UNKNOWN", False)),
        (None, 7, None, ("IN", True)),
    ],
)
def test_classify_stock_variants(stock_level, quantity, cc_availability, expected):
    assert _classify(stock_level, quantity, cc_availability) == expected


def test_parse_store_returns_none_without_store_id():
    assert _parse_store({"attributes": {"store": {"name": "No id"}}}) is None


def test_filter_store_for_radius_replaces_api_distance_from_user_center():
    store = _parse_store(SAMPLE_DATA[0])

    filtered = _filter_store_for_radius(store, (48.88, 2.32), 15)

    assert filtered["api_distance_km"] == 3.56
    assert filtered["distance_km"] == 0


def test_filter_store_for_radius_excludes_far_or_unlocatable_stores():
    far = {
        "id": "far",
        "name": "Castorama La Seyne sur Mer",
        "lat": 43.117745,
        "lon": 5.865068,
        "distance_km": 3.2,
        "api_distance_km": 3.2,
    }
    no_coords = {"id": "no-coords", "name": "Castorama No Coords"}

    assert _filter_store_for_radius(far, (48.8566, 2.3522), 15) is None
    assert _filter_store_for_radius(no_coords, (48.8566, 2.3522), 15) is None


def test_extract_token_prefers_stores_api_authorization_header():
    html = (
        '...{"url":"https://api.kingfisher.com/v1/mobile/basket/CAFR",'
        '"headers":{"Authorization":"WRONGTOKEN_basket"}}...'
        '{"url":"https://api.kingfisher.com/v1/mobile/stores/CAFR",'
        '"headers":{"Authorization":"Scheme1234 right_store_token_value_here"}}...'
    )

    assert extract_token(html) == "Scheme1234 right_store_token_value_here"


def test_extract_token_handles_escaped_react_router_payload():
    html = (
        'stores/CAFR\\",\\"headers\\":'
        '{\\"Authorization\\":\\"Scheme1234 escaped_token_42\\"}'
    )

    assert extract_token(html) == "Scheme1234 escaped_token_42"


def test_default_ean_url_pattern_matches_castorama_product_urls():
    assert (
        ean_from_url("https://www.castorama.fr/x/8431312260509_CAFR.prd")
        == "8431312260509"
    )


def _raw_store(store_id, name, *, lat=None, lon=None, distance="999 KM", postcode="75001"):
    coords = {}
    if lat is not None and lon is not None:
        coords = {"latitude": lat, "longitude": lon}
    return {
        "type": "store",
        "id": store_id,
        "attributes": {
            "store": {
                "name": name,
                "distance": distance,
                "externalId": store_id,
                "geoCoordinates": {
                    "postalCode": postcode,
                    "coordinates": coords,
                },
            },
            "stock": {"products": [{"stockLevel": "InStock", "quantity": 1}]},
            "clickAndCollect": {"summary": {"availability": "AllAvailable"}},
        },
    }


def _scan_args(**overrides):
    args = SimpleNamespace(
        data_dir="data",
        token_ttl=21600,
        product_url=castomod.DEFAULT_PRODUCT_URL,
        product_ref=None,
        postcode="75001",
        radius_km=0,
        area_center=None,
        zone_label=None,
        page_size=50,
        max_seeds=0,
        min_delay=0,
        max_delay=0,
        stable_rounds=0,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _scanner_without_sleep():
    scanner = CastoScanner()
    scanner._pause = lambda args, long=False: None
    return scanner


def test_casto_scan_keeps_national_behavior_without_radius(monkeypatch):
    scanner = _scanner_without_sleep()
    events = []
    scanner.set_event_handler(lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(castomod, "SEEDS_CASTO_FRANCE", [("Seed", 48.0, 2.0)])
    monkeypatch.setattr(castomod, "_get_token", lambda session, args, force=False: "token")
    monkeypatch.setattr(castomod, "_fetch_online", lambda session, ean, postcode: {})
    monkeypatch.setattr(castomod, "_fetch_stores_near", lambda *args: SAMPLE_DATA)

    result = scanner.scan(object(), _scan_args(radius_km=0))

    assert len(result["stores"]) == 4
    assert result["stores"]["1487"]["distance_km"] == 3.61
    assert result["stores"]["1487"]["lat"] is None
    assert next(payload for event, payload in events if event == "scan_start")["zone"] == "France"


def test_casto_scan_filters_local_radius_and_recomputes_distances(monkeypatch):
    scanner = _scanner_without_sleep()
    events = []
    scanner.set_event_handler(lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(castomod, "SEEDS_CASTO_FRANCE", [("Seed", 48.0, 2.0)])
    monkeypatch.setattr(castomod, "_get_token", lambda session, args, force=False: "token")
    monkeypatch.setattr(castomod, "_fetch_online", lambda session, ean, postcode: {})
    monkeypatch.setattr(
        castomod,
        "_fetch_stores_near",
        lambda *args: [
            _raw_store("near", "Castorama Paris", lat=48.8566, lon=2.3522),
            _raw_store("far", "Castorama Marseille", lat=43.2824, lon=5.4263),
            _raw_store("unknown", "Castorama Sans Coordonnees"),
        ],
    )

    result = scanner.scan(
        object(),
        _scan_args(
            radius_km=15,
            area_center=(48.8566, 2.3522),
            zone_label="75001 · 15 km",
        ),
    )

    assert list(result["stores"]) == ["near"]
    assert result["stores"]["near"]["api_distance_km"] == 999
    assert result["stores"]["near"]["distance_km"] == 0
    assert next(payload for event, payload in events if event == "scan_start")["zone"] == (
        "75001 · 15 km"
    )
