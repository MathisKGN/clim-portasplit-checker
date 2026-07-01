"""Leroy Merlin — adapteur HTTP (curl_cffi + warmup Camoufox).

Endpoint stock (fragment HTML, pas JSON) :
  GET /store-header-module/services/contextlayer/store-search-result
      ?latitude=<lat>&longitude=<lon>&productRef=<ref>&storeSearchType=STOCK
Réponse : ~10-11 magasins les plus proches du point. On sème des points couvrant
la zone (cf. seeds_idf.py / seeds_france.py), on parse le fragment, on
déduplique par slug magasin.

Le scan est séquentiel (un seed à la fois, jamais de rafale Promise.all) :
plus lent mais discret. La session HTTP est établie par un warmup Camoufox
qui pose le cookie DataDome, puis curl_cffi le réutilise. Sur 403/datadome,
`remint()` re-minte un cookie neuf une fois (cf. lm_http.py).

Tous les defaults tunables vivent dans config.toml ; la CLI ne garde que
--product-ref / --product-url (override par produit traqué).
"""
from __future__ import annotations

import re
import sys
from contextlib import contextmanager

from ..base import ScannerBase
from ..common import (
    aggregate,
    normalize_text,
    order_core_first,
    sleep_between,
    ts,
)

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Manque BeautifulSoup. Installe : pip install beautifulsoup4 lxml")

from ..seeds_idf import SEEDS_IDF, SEEDS_WIDE, CENTER, CORE_IDF
try:
    from ..seeds_france import SEEDS_FRANCE_200KM
except ImportError:
    SEEDS_FRANCE_200KM = None
try:
    from ..seeds_france_full import SEEDS_FRANCE_FULL
except ImportError:
    SEEDS_FRANCE_FULL = None

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #
DEFAULT_PRODUCT_REF = "93857579"
DEFAULT_PRODUCT_URL = (
    "https://www.leroymerlin.fr/produits/"
    "climatiseur-split-mobile-reversible-portasplit-midea-par-optimea-93857579.html"
)

OUT_PATTERNS = ("indispo", "rupture", "epuis", "non disponible")
UNKNOWN_PATTERNS = (
    "bientot", "prochainement", "temporairement", "sur commande",
    "reappro", "alerte", "prevenez-moi",
)
IN_PATTERNS = ("disponible", "en stock", "plus que", "retrait")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _classify(status_text: str, badge_classes: str):
    """Renvoie ('OUT'|'IN'|'UNKNOWN', is_restock)."""
    s = normalize_text(status_text)
    b = (badge_classes or "").lower()

    if ("--red" in b) or any(p in s for p in OUT_PATTERNS):
        return "OUT", False
    if any(p in s for p in UNKNOWN_PATTERNS):
        return "UNKNOWN", False
    if ("--green" in b) or ("--orange" in b) or any(p in s for p in IN_PATTERNS):
        return "IN", True
    return "UNKNOWN", False


def _parse_stores(html: str) -> dict:
    """Parse le fragment HTML -> { slug: {slug,name,status_text,badge,distance_km,state,restock} }."""
    soup = BeautifulSoup(html, "lxml")
    stores: dict = {}
    for a in soup.select('a[href*="/magasins/"]'):
        href = a.get("href", "")
        m = re.search(r"/magasins/([^./]+)\.html", href)
        if not m:
            continue
        slug = m.group(1)

        container = None
        node = a
        for _ in range(8):
            node = node.parent
            if node is None:
                break
            if node.select_one('[class*="stock-status"]'):
                container = node
                break
        if container is None:
            container = a.parent
        if container is None:
            continue

        name_el = container.select_one(
            '[class*="store-info-header--title"], [class*="store-info-header__title"], '
            '[class*="main-store--title"], [class*="store-name"]'
        ) or container.select_one("h2, h3, h4")
        name = name_el.get_text(strip=True) if name_el else slug

        badge = container.select_one(
            '[class*="stock-status__badge"], [class*="stock-status_badge"]'
        )
        badge_classes = " ".join(badge.get("class", [])) if badge else ""

        text_el = container.select_one(
            '[class*="stock-status__text"], [class*="stock-status_text"]'
        )
        status_text = text_el.get_text(strip=True) if text_el else ""

        mdist = re.search(r"([\d.,]+)\s*km", container.get_text(" ", strip=True))
        distance_km = mdist.group(1).replace(",", ".") if mdist else None

        state, restock = _classify(status_text, badge_classes)

        if slug not in stores:
            stores[slug] = dict(
                slug=slug,
                id=slug,
                name=name,
                status_text=status_text,
                badge=badge_classes,
                distance_km=distance_km,
                state=state,
                restock=restock,
            )
    return stores


def looks_blocked(status: int, body: str) -> bool:
    if status != 200:
        return True
    # 200 avec le wrapper endpoint = OK
    if "m-store-search-result" in body:
        return False
    low = body.lower()
    # 200 mais réponse d'interstitiel au lieu du fragment attendu = bloqué
    if "datadome" in low or "captcha" in low:
        return True
    # 200 + page HTML générique (login, redirect…) = pas le bon endpoint
    if "<html" in low:
        return True
    # 200 + body vide / non-HTML : on ne considère PAS comme bloqué
    # (réponse légitime mais sans magasin à <= 30 km).
    return False


# --------------------------------------------------------------------------- #
# Adapteur
# --------------------------------------------------------------------------- #
class LmScanner(ScannerBase):
    RETAILER_NAME = "Leroy Merlin"
    FILE_PREFIX = ""
    ENV_PREFIX = "LM"
    DEFAULT_PRODUCT_REF = DEFAULT_PRODUCT_REF
    DEFAULT_PRODUCT_URL = DEFAULT_PRODUCT_URL
    CONFIG_KEY = "lm"

    @classmethod
    def get_defaults(cls) -> dict:
        return {
            "zone": "idf",
            "wide": False,
            "max_seeds": 0,
            "min_delay": 2.0,
            "max_delay": 5.0,
            "max_blocks": 3,
            "stable_rounds": 3,
            "impersonate": "firefox135",
            "product_ref": cls.DEFAULT_PRODUCT_REF,
            "product_url": cls.DEFAULT_PRODUCT_URL,
        }

    def store_url(self, store: dict) -> str:
        return f"https://www.leroymerlin.fr/magasins/{store['slug']}.html"

    def csv_header(self):
        return ["slug", "magasin", "etat", "statut_texte", "badge", "distance_km", "url"]

    def csv_row(self, store):
        return [
            store["slug"], store["name"], store["state"],
            store["status_text"], store["badge"], store["distance_km"],
            self.store_url(store),
        ]

    # --- CLI (minimal : juste les overrides produit) --------------------- #
    def add_arguments(self, parser):
        # --product-ref / --product-url déjà ajoutés par les args communs.
        pass

    # --- Contexte (HTTP pur) ---------------------------------------------- #
    @contextmanager
    def open_context(self, args):
        from .lm_http import open_http_context
        with open_http_context(args) as sess:
            yield sess

    # --- Sélection des seeds --------------------------------------------- #
    def _select_seeds(self, args):
        zone_name = args.zone
        if zone_name == "france" and SEEDS_FRANCE_FULL:
            seeds = list(SEEDS_FRANCE_FULL)
            zone = f"France entière ({len(seeds)} seeds, 120 magasins)"
        elif zone_name == "paris200" and SEEDS_FRANCE_200KM:
            seeds = list(SEEDS_FRANCE_200KM)
            zone = "Paris 200 km (55 magasins ciblés)"
        elif getattr(args, "wide", False):
            seeds = list(SEEDS_IDF) + list(SEEDS_WIDE)
            zone = "IDF + couronne élargie"
        else:
            # Défaut : 5 seeds stratégiques couvrant tout IDF (~36 magasins).
            seeds = list(CORE_IDF)
            zone = "IDF core (5 seeds)"
        seeds = order_core_first(seeds, CENTER)
        if args.max_seeds and args.max_seeds > 0:
            seeds = seeds[: args.max_seeds]
        return seeds, zone

    # --- Scan -------------------------------------------------------------- #
    def scan(self, ctx, args) -> dict:
        return self._scan_http(ctx, args)

    # --- Scan HTTP pur (sans navigateur) ----------------------------------- #
    def _scan_http(self, sess, args) -> dict:
        seeds, zone = self._select_seeds(args)
        verbose = getattr(args, "verbose", False)
        if verbose:
            print(f"  scan HTTP {len(seeds)} points sans navigateur ({zone})")
        all_stores: dict = {}
        blocked = 0
        max_blocks = max(1, getattr(args, "max_blocks", 6))
        stable_rounds = max(0, getattr(args, "stable_rounds", 0))
        stable = 0
        # Re-mint du cookie DataDome au plus une fois par scan (cf. chemin
        # Casto `refreshed` sur 401). On évite ainsi de marteler l'endpoint
        # avec un cookie mort.
        refreshed = False

        def _fetch(lat, lon):
            """Fetch un seed, avec re-mint unique sur cookie mort (403).

            Renvoie (status, body). Sur 403/datadome au 1er essai, on re-minte
            la session Camoufox une fois puis on retente — pas de bouclage.
            """
            nonlocal refreshed
            status, body = sess.fetch_stock(lat, lon)
            if sess._is_cookie_dead(status, body) and not refreshed:
                refreshed = True
                sess.remint()
                status, body = sess.fetch_stock(lat, lon)
            return status, body

        # Mint = warmup (homepage + fiche produit) + 1 fetch stock au 1er seed.
        # On réutilise le body du mint comme résultat du seed 0 (pas de double
        # hit Paris Centre). Si le mint échoue -> session burned, on arrête.
        first_label, first_lat, first_lon = seeds[0]
        status, body = sess.mint(first_lat, first_lon)
        if sess._is_cookie_dead(status, body) and not refreshed:
            refreshed = True
            sess.remint()
            status, body = sess.fetch_stock(first_lat, first_lon)
        if status == 200 and "m-store-search-result" in body:
            found = _parse_stores(body)
            new = aggregate(found, all_stores)
            if verbose:
                print(f"    mint/{first_label} : {len(found)} magasins (+{new})")
        else:
            if looks_blocked(status, body):
                blocked += 1
                if verbose:
                    print(f"    mint/{first_label} bloqué (status={status})")

        # Boucle à partir du seed 1 (seed 0 déjà couvert par le mint).
        for i, (label, lat, lon) in enumerate(seeds[1:], 2):
            status, body = _fetch(lat, lon)
            if looks_blocked(status, body):
                blocked += 1
                if verbose:
                    print(f"    {i}/{len(seeds)} {label} bloqué (status={status})")
                if blocked >= max_blocks:
                    if verbose:
                        print(f"  ✗ stop à {blocked} blocages (max_blocks={max_blocks})")
                    break
            else:
                found = _parse_stores(body)
                new = aggregate(found, all_stores)
                if verbose:
                    print(f"    {i}/{len(seeds)} {label} : {len(found)} magasins (+{new})")
                # stable-rounds : arrêt dès qu'on enchaîne N seeds sans nouveau
                # magasin (couverture déjà assurée, inutile de taper tous les
                # points et de risquer des 403).
                stable = stable + 1 if new == 0 else 0
                if stable_rounds and all_stores and stable >= stable_rounds:
                    if verbose:
                        print(f"  ◇ stop après {stable_rounds} seeds sans nouveauté "
                              f"(stable-rounds={stable_rounds})")
                    break
            # Cadence large (2-5 s par défaut) : un humain ne scanne pas 36
            # magasins en 3 min. sleep_between respecte --min/max-delay.
            if i < len(seeds):
                sleep_between(args)
        return {"stores": all_stores, "blocked": blocked, "seeds": len(seeds),
                "completed": blocked == 0,
                "extra": {"zone": zone, "engine": "http"}}

