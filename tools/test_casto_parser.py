"""Test offline du parseur/classifieur Castorama sur un échantillon JSON
reproduisant la structure réelle de l'API Kingfisher (/v1/mobile/stores/CAFR).

Cible le nouveau package stockmonitor/ (cf. stockmonitor/retailers/casto.py).
Pour exécuter : `python tools/test_casto_parser.py` (depuis la racine).
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stockmonitor.retailers.casto import _parse_store as parse_store, _classify as classify, extract_token
from stockmonitor.common import ean_from_url

# Échantillon : 1 magasin dispo, 1 en rupture, 1 non référencé, 1 dispo via Drive 2h.
SAMPLE_DATA = [
    {
        "type": "store", "id": "1486",
        "attributes": {
            "store": {
                "name": "Castorama Place de Clichy", "distance": "3.56 KM",
                "externalId": "1486", "seoPath": "/magasins/paris-clichy",
                "geoCoordinates": {"postalCode": "75018",
                                   "coordinates": {"latitude": 48.88, "longitude": 2.32}},
            },
            "stock": {"products": [{"ean": "X", "stockLevel": "InStock", "quantity": 4}]},
            "clickAndCollect": {"summary": {"availability": "AllAvailable",
                                            "primaryMessage": "Disponible"}},
        },
    },
    {
        "type": "store", "id": "1487",
        "attributes": {
            "store": {"name": "Castorama Nation", "distance": "3.61 KM",
                      "geoCoordinates": {"postalCode": "75020", "coordinates": {}}},
            "stock": {"products": [{"stockLevel": "OutOfStock", "quantity": 0}]},
            "clickAndCollect": {"summary": {"availability": "AllNotAvailable"}},
        },
    },
    {
        "type": "store", "id": "2753",
        "attributes": {
            "store": {"name": "Casto Les Lilas", "distance": "5.49 KM",
                      "geoCoordinates": {"postalCode": "93260", "coordinates": {}}},
            "stock": {"products": [{"stockLevel": "NotStockedInStore", "quantity": None}]},
            "clickAndCollect": {"summary": {"availability": "AllNotAvailable"}},
        },
    },
    {
        "type": "store", "id": "1440",
        "attributes": {
            "store": {"name": "Castorama Créteil", "distance": "10.58 KM",
                      "geoCoordinates": {"postalCode": "94000", "coordinates": {}}},
            # rayon vide mais Drive 2h dispo -> doit compter comme restock
            "stock": {"products": [{"stockLevel": "OutOfStock", "quantity": 0}]},
            "clickAndCollect": {"summary": {"availability": "SomeAvailable",
                                            "primaryMessage": "Disponible en Drive 2h"}},
        },
    },
]

stores = {s["id"]: parse_store(s) for s in SAMPLE_DATA}
print(f"Magasins parsés : {len(stores)}\n")
for sid, s in stores.items():
    flag = ("🟢 RESTOCK" if s["restock"] else
            ("🔴 indispo" if s["state"] == "OUT" else
             ("⚪ non réf." if s["state"] == "NOT_CARRIED" else "❔")))
    print(f"  {flag:<12} {s['name']:<28} cp={s['postcode']} state={s['state']:<11} "
          f"lvl={s['stock_level']} qty={s['quantity']} cc={s['cc_availability']} "
          f"dist={s['distance_km']}")

# Vérifications parse_store
assert len(stores) == 4
assert stores["1486"]["state"] == "IN" and stores["1486"]["restock"] is True
assert stores["1486"]["quantity"] == 4
assert stores["1486"]["url"] == "https://www.google.com/maps/search/?api=1&query=48.88,2.32"
assert stores["1486"]["dept"] == "75"
assert stores["1487"]["state"] == "OUT" and stores["1487"]["restock"] is False
assert stores["2753"]["state"] == "NOT_CARRIED" and stores["2753"]["restock"] is False
assert stores["1440"]["restock"] is True, "Drive 2h dispo => candidat restock"
assert stores["1486"]["distance_km"] == 3.56

# Vérifications classify (unitaire)
assert classify("InStock", 4, "AllNotAvailable")[1] is True
assert classify("LimitedStock", None, "AllNotAvailable")[1] is True
assert classify("OutOfStock", 0, "AllNotAvailable") == ("OUT", False)
assert classify("OutOfStock", 0, "SomeAvailable")[1] is True       # Drive 2h
assert classify("NotStockedInStore", None, "AllNotAvailable") == ("NOT_CARRIED", False)
assert classify("", None, "")[0] == "UNKNOWN"
assert classify(None, 7, None) == ("IN", True)                     # quantité seule

# Extraction EAN depuis l'URL
assert ean_from_url("https://www.castorama.fr/x/8431312260509_CAFR.prd") == "8431312260509"

# Extraction du token : ancrée sur stores/CAFR (ignore les autres Authorization)
HTML = (
    '...{"url":"https://api.kingfisher.com/v1/mobile/basket/CAFR",'
    '"headers":{"Authorization":"WRONGTOKEN_basket"}}...'
    '{"url":"https://api.kingfisher.com/v1/mobile/stores/CAFR",'
    '"headers":{"Authorization":"Scheme1234 right_store_token_value_here"}}...'
)
assert extract_token(HTML) == "Scheme1234 right_store_token_value_here", extract_token(HTML)

# Variante avec JSON échappé (comme dans le flux SSR React-Router)
HTML_ESC = (
    'stores/CAFR\\",\\"headers\\":{\\"Authorization\\":\\"Scheme1234 escaped_token_42\\"}'
)
assert extract_token(HTML_ESC) == "Scheme1234 escaped_token_42", extract_token(HTML_ESC)

print("\n✅ Tous les tests passent.")
