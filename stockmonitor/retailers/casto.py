"""Castorama — adapteur requests (API JSON Kingfisher + BFF livraison).

Contrairement à Leroy Merlin, castorama.fr sert sa fiche produit à une simple
requête serveur **et** son stock magasin vient d'une API mobile JSON propre.
Aucun navigateur requis — un `requests` suffit.

Mécanique :
  1. Token d'API (clé statique ~80 car.) extraite du HTML SSR de la fiche produit,
     ancrée sur `stores/CAFR`.
  2. Stock par magasin :
        GET https://api.kingfisher.com/v1/mobile/stores/CAFR
            ?nearLatLong=<lat>,<lon>&page[size]=<N>
            &include=clickAndCollect,stock&filter[ean]=<ean>
        Header: Authorization: <token>
     L'API n'a pas de plafond de distance : un seul point ramène jusqu'à N
     magasins. On sème 3 coords France (greedy set-cover, cf. seeds_casto_france)
     pour couvrir les ~90 magasins Casto FR en 3 appels, puis on déduplique.
  3. Disponibilité en ligne (livraison à domicile) — BFF same-origin, sans token :
        GET https://www.castorama.fr/casto-browse-mfe/api/fulfilment-options
            ?compositeOfferId=<ean>&delivery=true&postalCode=<cp>
"""
from __future__ import annotations

import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus, urlencode

from ..base import ScannerBase
from ..common import (
    ean_from_url,
    http_get,
    sleep_between,
    ts,
)
from ..seeds_casto_france import SEEDS_CASTO_FRANCE

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #
DEFAULT_PRODUCT_URL = (
    "https://www.castorama.fr/climatiseur-portasplit-midea-reversible-3500w/"
    "8431312260509_CAFR.prd"
)
STORE_API = "https://api.kingfisher.com/v1/mobile/stores/CAFR"
FULFIL_BFF = "https://www.castorama.fr/casto-browse-mfe/api/fulfilment-options"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

STOCK_IN = {"instock", "limitedstock", "lowstock", "instockonline"}
STOCK_OUT = {"outofstock"}
STOCK_NOT_CARRIED = {"notstockedinstore", "notranged", "notsold"}
CC_AVAILABLE = {"allavailable", "someavailable", "available"}

TOKEN_TTL_S = 6 * 3600


# --------------------------------------------------------------------------- #
# Token
# --------------------------------------------------------------------------- #
def extract_token(html: str) -> str | None:
    """Récupère le header Authorization ancré sur l'API `stores/CAFR`.

    Le HTML contient plusieurs tokens (storeApi, basketApi, …) : on ancre sur
    `stores/CAFR` pour prendre le bon.
    """
    i = html.find("stores/CAFR")
    window = html[i:i + 800] if i != -1 else html
    m = re.search(r'[Aa]uthorization\\?"\s*:\s*\\?"([^"\\]{20,200})', window)
    if not m and i != -1:
        m = re.search(r'[Aa]uthorization\\?"\s*:\s*\\?"([^"\\]{20,200})', html)
    return m.group(1).strip() if m else None


def _load_cached_token(path: Path, ttl: int) -> str | None:
    if not path.exists():
        return None
    if (time.time() - path.stat().st_mtime) > ttl:
        return None
    tok = path.read_text(encoding="utf-8").strip()
    return tok or None


def _fetch_token(session, product_url: str, cache: Path) -> str:
    r = http_get(session, product_url,
                 headers={"User-Agent": UA, "Accept": "text/html",
                          "Accept-Language": "fr-FR,fr;q=0.9"})
    token = extract_token(r.text)
    if not token:
        raise RuntimeError("Token d'API introuvable dans la fiche produit "
                           "(structure de page modifiée ?).")
    cache.write_text(token, encoding="utf-8")
    return token


def _get_token(session, args, force=False) -> str:
    cache = Path(args.data_dir) / "casto_token.txt"
    if not force:
        tok = _load_cached_token(cache, args.token_ttl)
        if tok:
            return tok
    return _fetch_token(session, args.product_url, cache)


# --------------------------------------------------------------------------- #
# Dispo en ligne / par magasin
# --------------------------------------------------------------------------- #
def _fetch_online(session, ean: str, postcode: str) -> dict:
    q = urlencode({"compositeOfferId": ean, "delivery": "true", "postalCode": postcode})
    try:
        r = http_get(session, f"{FULFIL_BFF}?{q}",
                     headers={"User-Agent": UA, "Accept": "application/json",
                              "Accept-Language": "fr-FR,fr;q=0.9"})
        data = (r.json().get("data") or [{}])[0].get("attributes", {})
    except Exception as e:
        return {"error": str(e)}
    hd = data.get("homeDelivery") or {}
    cc = data.get("clickAndCollectStorePick") or {}
    avail = (hd.get("availability") or "").lower()
    return {
        "home_delivery": hd.get("availability"),
        "home_delivery_msg": hd.get("shortMessage") or hd.get("longMessage"),
        "home_delivery_qty": hd.get("quantity"),
        "click_collect": cc.get("availability"),
        "available": avail in {"available", "instock", "lowstock"},
    }


def _classify(stock_level: str, quantity, cc_availability: str):
    """Renvoie ('IN'|'OUT'|'NOT_CARRIED'|'UNKNOWN', is_restock)."""
    lvl = (stock_level or "").lower()
    cc = (cc_availability or "").lower()
    qty = quantity if isinstance(quantity, (int, float)) else None

    cc_ok = cc in CC_AVAILABLE
    if lvl in STOCK_IN or (qty is not None and qty > 0):
        return "IN", True
    if cc_ok:
        return "IN", True
    if lvl in STOCK_OUT or qty == 0:
        return "OUT", False
    if lvl in STOCK_NOT_CARRIED:
        return "NOT_CARRIED", False
    return "UNKNOWN", False


def _parse_store(raw: dict) -> dict | None:
    """Normalise un magasin de la réponse API Kingfisher."""
    attr = raw.get("attributes") or {}
    store = attr.get("store") or {}
    geo = store.get("geoCoordinates") or {}
    coords = geo.get("coordinates") or {}

    sid = str(raw.get("id") or store.get("externalId") or "")
    if not sid:
        return None

    products = (attr.get("stock") or {}).get("products") or []
    p0 = products[0] if products else {}
    stock_level = p0.get("stockLevel")
    quantity = p0.get("quantity")

    cc_summary = (attr.get("clickAndCollect") or {}).get("summary") or {}
    cc_avail = cc_summary.get("availability")

    postcode = geo.get("postalCode") or ""
    dist = store.get("distance") or ""
    mdist = re.search(r"([\d.]+)", dist)

    state, restock = _classify(stock_level, quantity, cc_avail)

    lat, lon = coords.get("latitude"), coords.get("longitude")
    if lat and lon:
        url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    else:
        url = ("https://www.google.com/maps/search/?api=1&query="
               + quote_plus(f"{store.get('name','')} {postcode}"))

    return dict(
        id=sid,
        name=store.get("name") or sid,
        postcode=postcode,
        dept=postcode[:2],
        distance_km=float(mdist.group(1)) if mdist else None,
        lat=coords.get("latitude"),
        lon=coords.get("longitude"),
        stock_level=stock_level,
        quantity=quantity,
        cc_availability=cc_avail,
        cc_message=cc_summary.get("primaryMessage"),
        state=state,
        restock=restock,
        url=url,
    )


def _fetch_stores_near(session, token, ean, lat, lon, size):
    q = urlencode({
        "nearLatLong": f"{lat},{lon}",
        "page[size]": str(size),
        "include": "clickAndCollect,stock",
        "filter[ean]": ean,
    }, safe=",")
    r = http_get(session, f"{STORE_API}?{q}",
                 headers={"User-Agent": UA, "Authorization": token,
                          "Accept": "application/json"})
    if r.status_code == 401:
        raise PermissionError("401")
    r.raise_for_status()
    return r.json().get("data") or []


# --------------------------------------------------------------------------- #
# Adapteur
# --------------------------------------------------------------------------- #
class CastoScanner(ScannerBase):
    RETAILER_NAME = "Castorama"
    FILE_PREFIX = "casto"
    ENV_PREFIX = "CASTO"
    DEFAULT_PRODUCT_REF = "8431312260509"
    DEFAULT_PRODUCT_URL = DEFAULT_PRODUCT_URL
    HAS_ONLINE_AVAILABILITY = True

    def store_url(self, store: dict) -> str:
        return store.get("url", "")

    def sort_stores(self, stores):
        return sorted(stores, key=lambda x: (x.get("distance_km") or 1e9))

    def csv_header(self):
        return ["id", "magasin", "cp", "etat", "stock_level", "quantite",
                "click_collect", "distance_km", "url"]

    def csv_row(self, store):
        return [store["id"], store["name"], store["postcode"], store["state"],
                store["stock_level"], store["quantity"], store["cc_availability"],
                store["distance_km"], store["url"]]

    def extra_history_fields(self, result):
        online = result.get("extra", {}).get("online", {})
        return {
            "online": online.get("home_delivery"),
            "online_available": online.get("available"),
        }

    # --- CLI --------------------------------------------------------------- #
    def add_arguments(self, parser):
        parser.add_argument("--product-url", default=DEFAULT_PRODUCT_URL,
                            help="URL fiche produit Castorama (.prd). L'EAN est déduit.")
        parser.add_argument("--postcode", default="75011",
                            help="Code postal pour la dispo livraison à domicile.")
        parser.add_argument("--page-size", type=int, default=50,
                            help="Magasins demandés par seed (defaut 50).")
        parser.add_argument("--max-seeds", type=int, default=0, metavar="N",
                            help="Limite aux N premiers seeds France (0 = tous).")
        parser.add_argument("--stable-rounds", type=int, default=3,
                            help="Arrêt après N seeds sans nouveau magasin.")
        parser.add_argument("--token-ttl", type=int, default=TOKEN_TTL_S,
                            help="Durée (s) de réutilisation du token caché (defaut 6h).")
        parser.add_argument("--min-delay", type=float, default=0.8)
        parser.add_argument("--max-delay", type=float, default=2.0)

    def enrich_args(self, args):
        """Args n'a pas de --product-ref pour Casto (c'est un EAN déduit de l'URL).
        On l'expose quand même pour le notify-cmd (env CASTO_PRODUCT_REF)."""
        if not getattr(args, "product_ref", None):
            args.product_ref = ean_from_url(args.product_url)
        return args

    # --- Contexte requests ------------------------------------------------- #
    @contextmanager
    def open_context(self, args):
        try:
            import requests
        except ImportError:
            sys.exit("Manque requests. Installe : pip install requests")
        with requests.Session() as session:
            yield session

    # --- Scan -------------------------------------------------------------- #
    def scan(self, session, args) -> dict:
        args = self.enrich_args(args)
        ean = args.product_ref
        token = _get_token(session, args)

        online = _fetch_online(session, ean, args.postcode)

        seeds = list(SEEDS_CASTO_FRANCE)
        if args.max_seeds and args.max_seeds > 0:
            seeds = seeds[: args.max_seeds]

        verbose = getattr(args, "verbose", False)
        if verbose:
            print(f"  EAN {ean} · en ligne: "
                  f"{online.get('home_delivery') or online.get('error')} · "
                  f"scan {len(seeds)} points France")

        all_stores: dict = {}
        errors = 0
        refreshed = False
        stable = 0
        used = 0
        for i, (label, lat, lon) in enumerate(seeds, 1):
            try:
                raw = _fetch_stores_near(session, token, ean, lat, lon, args.page_size)
            except PermissionError:
                if not refreshed:
                    token = _get_token(session, args, force=True)
                    refreshed = True
                    raw = _fetch_stores_near(session, token, ean, lat, lon, args.page_size)
                else:
                    raise
            except Exception as e:
                errors += 1
                if verbose:
                    print(f"    {i}/{len(seeds)} {label} ⚠ {e!r}")
                sleep_between(args, long=True)
                continue

            used += 1
            new = 0
            for rs in raw:
                st = _parse_store(rs)
                if not st:
                    continue
                sid = st["id"]
                if sid not in all_stores:
                    all_stores[sid] = st
                    new += 1
                elif st["restock"] and not all_stores[sid]["restock"]:
                    all_stores[sid] = st
            if verbose:
                print(f"    {i}/{len(seeds)} {label} : {len(raw)} reçus (+{new})")
            stable = stable + 1 if new == 0 else 0
            if all_stores and stable >= args.stable_rounds:
                break
            if i < len(seeds):
                sleep_between(args)

        return {"ean": ean, "online": online,
                "stores": all_stores, "blocked": errors, "seeds": used,
                "completed": errors == 0,
                "extra": {"online": online}}
