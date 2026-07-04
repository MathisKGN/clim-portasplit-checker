from __future__ import annotations

import pytest

from stockmonitor.common import ean_from_url
from stockmonitor.retailers.casto import (
    _classify,
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
