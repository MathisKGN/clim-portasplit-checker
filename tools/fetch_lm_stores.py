#!/usr/bin/env python3
"""
Récupère la liste OFFICIELLE des magasins Leroy Merlin depuis leur store-locator.

Le store-locator leroymerlin.fr/magasins/ est propulsé par Woosmap. Son API
publique (clé embarquée dans la page) renvoie tous les magasins en une requête,
avec pour chacun : id, nom, slug (/magasins/<slug>.html — celui que renvoie
l'endpoint stock), ville, code postal ET coordonnées réelles.

C'est la source de vérité : plus de liste collée à la main, plus de géocodage
Nominatim (CP corrompus, homonymes). On sauve data/lm_stores.json, que
tools/gen_seeds_france.py consomme pour le set-cover.

L'API Woosmap n'est pas derrière DataDome (domaine api.woosmap.com), donc ce
fetch marche en direct, sans navigateur.

Usage : python3 tools/fetch_lm_stores.py
"""
from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

# Clé publique Woosmap embarquée dans leroymerlin.fr/magasins/ (store-locator).
WOOSMAP_KEY = "woos-47262215-fc76-3bd2-8e0d-d8fda2544349"
WOOSMAP_URL = (
    "https://api.woosmap.com/stores/search/"
    "?key={key}&lat=46.6&lng=2.4&max_distance=3000000&stores_by_page=300&page={page}"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.leroymerlin.fr/",
    "Origin": "https://www.leroymerlin.fr",
}


def fetch_page(page: int) -> dict:
    url = WOOSMAP_URL.format(key=WOOSMAP_KEY, page=page)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def main() -> None:
    features: list = []
    page = 1
    while True:
        data = fetch_page(page)
        features.extend(data.get("features", []))
        pg = data.get("pagination", {})
        if page >= pg.get("pageCount", 1):
            break
        page += 1

    stores, skipped = [], []
    for f in features:
        p = f.get("properties", {})
        lon, lat = f["geometry"]["coordinates"]
        web = (p.get("contact") or {}).get("website", "") or ""
        m = re.search(r"/magasins/([^./]+)\.html", web)
        if not m:
            # Pas de fiche magasin = showroom cuisine/sdb, pas de stock scannable.
            skipped.append(p.get("name", "?"))
            continue
        city = (p.get("address") or {}).get("city", "") or ""
        stores.append({
            "store_id": p.get("store_id"),
            "name": p.get("name", ""),
            "slug": m.group(1),
            "city": city.title() if city.isupper() else city,
            "cp": (p.get("address") or {}).get("zipcode", "") or "",
            "lat": round(lat, 6),
            "lon": round(lon, 6),
        })

    out = HERE / "data" / "lm_stores.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stores, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] data/lm_stores.json : {len(stores)} magasins officiels "
          f"({len(features)} entrées Woosmap, {len(skipped)} showrooms exclus)")
    for s in skipped:
        print(f"    exclu (pas de fiche stock) : {s}")


if __name__ == "__main__":
    main()
