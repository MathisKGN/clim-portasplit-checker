"""Leroy Merlin — adapteur Camoufox (anti-DataDome).

Le site leroymerlin.fr est protégé par DataDome. Les requêtes nues sont bloquées
(503 / challenge). On pilote un navigateur réel via Camoufox (Firefox
anti-détection, fingerprint cohérent), qui émet la XHR de stock depuis le
contexte de la page (same-origin) sans intervention humaine.

Endpoint stock (fragment HTML, pas JSON) :
  GET /store-header-module/services/contextlayer/store-search-result
      ?latitude=<lat>&longitude=<lon>&productRef=<ref>&storeSearchType=STOCK
Réponse : ~10-11 magasins les plus proches du point. On sème des points couvrant
la zone (cf. seeds_idf.py / seeds_france.py), on parse le fragment, on
déduplique par slug magasin.

Le scan se fait en rafale (un seul page.evaluate -> Promise.all par batch de N),
avec retry/backoff sur blocage et bascule auto en mode lent si la rafale est
jetée en masse.
"""
from __future__ import annotations

import random
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

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
ENDPOINT_PATH = "/store-header-module/services/contextlayer/store-search-result"

XHR_JS = r"""
async ([lat, lon, ref]) => {
  const u = '/store-header-module/services/contextlayer/store-search-result'
          + '?latitude=' + lat + '&longitude=' + lon
          + '&productRef=' + ref + '&storeSearchType=STOCK';
  return await new Promise((resolve) => {
    try {
      const x = new XMLHttpRequest();
      x.open('GET', u, true);
      x.setRequestHeader('accept', 'application/json, text/plain, */*');
      x.timeout = 25000;
      x.onreadystatechange = () => {
        if (x.readyState === 4) resolve({ status: x.status, body: x.responseText || '' });
      };
      x.ontimeout = () => resolve({ status: -2, body: '' });
      x.onerror   = () => resolve({ status: -1, body: '' });
      x.send();
    } catch (e) { resolve({ status: -3, body: String(e) }); }
  });
}
"""

BATCH_XHR_JS = r"""
async ([coords, ref, batch]) => {
  const base = '/store-header-module/services/contextlayer/store-search-result';
  const out = new Array(coords.length);
  for (let i = 0; i < coords.length; i += batch) {
    const slice = coords.slice(i, i + batch);
    const res = await Promise.all(slice.map(async (c, j) => {
      const lat = c[0], lon = c[1];
      const u = base + '?latitude=' + lat + '&longitude=' + lon
              + '&productRef=' + ref + '&storeSearchType=STOCK';
      try {
        const r = await fetch(u, { headers: { 'accept': 'application/json, text/plain, */*' } });
        const body = await r.text();
        return { idx: i + j, status: r.status, body: body || '' };
      } catch (e) {
        return { idx: i + j, status: -1, body: '' };
      }
    }));
    for (const r of res) out[r.idx] = { status: r.status, body: r.body };
    if (i + batch < coords.length) await new Promise(r => setTimeout(r, 250));
  }
  return out;
}
"""

OUT_PATTERNS = ("indispo", "rupture", "epuis", "non disponible")
UNKNOWN_PATTERNS = (
    "bientot", "prochainement", "temporairement", "sur commande",
    "reappro", "alerte", "prevenez-moi",
)
IN_PATTERNS = ("disponible", "en stock", "plus que", "retrait")
BLOCKED_RESOURCES = {"image", "media", "font"}


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

    has_signal = bool(s.strip()) or "stock-status" in b
    if not has_signal:
        return "UNKNOWN", False
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
    # 200 + signature DataDome/captcha = bloqué
    if "datadome" in low or "captcha" in low:
        return True
    # 200 + page HTML générique (login, redirect…) = pas le bon endpoint
    if "<html" in low:
        return True
    # 200 + body vide / non-HTML : on ne considère PAS comme bloqué
    # (réponse légitime mais sans magasin à <= 30 km). Évite de déclencher
    # un challenge-resolve inutile.
    return False


# --------------------------------------------------------------------------- #
# Navigateur (Camoufox — Firefox anti-détection)
# --------------------------------------------------------------------------- #
@contextmanager
def _open_browser(args):
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        sys.exit(
            "Manque Camoufox. Installe :\n"
            "  pip install -U camoufox[geoip] beautifulsoup4 lxml\n"
            "  python -m camoufox fetch"
        )

    profile_dir = Path(args.data_dir) / "camoufox_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    with Camoufox(
        headless=True,
        humanize=True,
        os=["macos"],
        locale="fr-FR",
        geoip=True,
        persistent_context=True,
        user_data_dir=str(profile_dir),
    ) as ctx:
        yield ctx


def _setup_page(page, args):
    if not getattr(args, "block_images", True):
        return

    def _router(route):
        try:
            if route.request.resource_type in BLOCKED_RESOURCES:
                route.abort()
            else:
                route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    try:
        page.route("**/*", _router)
    except Exception:
        pass


def _fetch_seed(page, lat, lon, ref):
    res = page.evaluate(XHR_JS, [lat, lon, ref])
    return int(res.get("status", -99)), res.get("body", "") or ""


def _batch_fetch(page, coords, ref, batch_size=8):
    payload = [[lat, lon] for (_, lat, lon) in coords]
    res = page.evaluate(BATCH_XHR_JS, [payload, ref, batch_size])
    return [(int(it.get("status", -99)), it.get("body", "") or "") for it in res]


# --------------------------------------------------------------------------- #
# Adapteur
# --------------------------------------------------------------------------- #
class LmScanner(ScannerBase):
    RETAILER_NAME = "Leroy Merlin"
    FILE_PREFIX = ""
    ENV_PREFIX = "LM"
    DEFAULT_PRODUCT_REF = DEFAULT_PRODUCT_REF
    DEFAULT_PRODUCT_URL = DEFAULT_PRODUCT_URL

    def store_url(self, store: dict) -> str:
        return f"https://www.leroymerlin.fr/magasins/{store['slug']}.html"

    def sort_stores(self, stores):
        return sorted(stores, key=lambda x: x.get("name", ""))

    def csv_header(self):
        return ["slug", "magasin", "etat", "statut_texte", "badge", "distance_km", "url"]

    def csv_row(self, store):
        return [
            store["slug"], store["name"], store["state"],
            store["status_text"], store["badge"], store["distance_km"],
            self.store_url(store),
        ]

    # --- CLI --------------------------------------------------------------- #
    def add_arguments(self, parser):
        parser.add_argument("--product-ref", default=DEFAULT_PRODUCT_REF,
                            help="Référence produit LM.")
        parser.add_argument("--product-url", default=DEFAULT_PRODUCT_URL,
                            help="URL fiche produit (chargée au démarrage).")
        parser.add_argument("--zone", choices=["idf", "paris200", "france"], default="idf",
                            help="'idf' (défaut) ou 'paris200' (7 seeds couvrant "
                                 "les 55 magasins à <= 200 km de Paris).")
        parser.add_argument("--min-delay", type=float, default=2.0, help="Délai mini (s).")
        parser.add_argument("--max-delay", type=float, default=5.0, help="Délai maxi (s).")
        parser.add_argument("--max-blocks", type=int, default=3, help="Blocages avant arrêt (anti-grillade).")
        parser.add_argument("--slow", dest="slow", action="store_true", default=False,
                            help="Mode lent point-par-point (anti-blocage). Défaut: rafale.")
        parser.add_argument("--batch-size", type=int, default=8, metavar="N",
                            help="Taille des batches en rafale (defaut 8).")
        parser.add_argument("--tries-per-seed", type=int, default=3, metavar="N",
                            help="Tentatives par point bloqué (re-validation + backoff).")
        parser.add_argument("--max-seeds", type=int, default=0, metavar="N",
                            help="Limite aux N premiers seeds (0 = tous).")
        parser.add_argument("--wide", dest="wide", action="store_true", default=False,
                            help="Ajoute la couronne élargie (Reims/Troyes/Orléans/Auxerre…).")
        parser.add_argument("--stable-rounds", type=int, default=0, metavar="N",
                            help="Arrêt après N points sans nouveau magasin (mode lent).")
        parser.add_argument("--block-images", dest="block_images", action="store_true", default=True)
        parser.add_argument("--no-block-images", dest="block_images", action="store_false")
        # --- Transport : défaut = HTTP pur (curl_cffi + device-check DataDome
        #     résolu via Camoufox), zéro navigateur pour le scan lui-même.
        #     --use-camoufox rebascule sur l'ancien chemin Firefox pour tout.
        parser.add_argument("--use-camoufox", dest="use_camoufox", action="store_true",
                            default=False,
                            help="Forcer le navigateur Camoufox (fallback). "
                                 "Défaut: HTTP pur sans navigateur.")
        parser.add_argument("--impersonate", default="firefox135",
                            help="Empreinte TLS curl_cffi pour le mode HTTP (défaut "
                                 "firefox135 ; doit rester une cible Firefox récente).")

    # --- Contexte (HTTP par défaut, Camoufox en fallback) ------------------ #
    @contextmanager
    def open_context(self, args):
        if getattr(args, "use_camoufox", False):
            with _open_browser(args) as browser:
                yield browser
        else:
            from .lm_http import open_http_context
            with open_http_context(args) as sess:
                yield sess

    def prepare_context(self, ctx, args):
        pass

    def _new_page(self, ctx, args):
        page = ctx.new_page()
        _setup_page(page, args)
        return page

    # --- Sélection des seeds (partagée HTTP / Camoufox) -------------------- #
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
            # Beaucoup moins de trafic que SEEDS_IDF (24 seeds) tout en couvrant
            # la même zone. Suffit avec la cadence 15-30 s/seed.
            seeds = list(CORE_IDF)
            zone = "IDF core (5 seeds)"
        seeds = order_core_first(seeds, CENTER)
        if args.max_seeds and args.max_seeds > 0:
            seeds = seeds[: args.max_seeds]
        return seeds, zone

    # --- Scan -------------------------------------------------------------- #
    def scan(self, ctx, args) -> dict:
        from .lm_http import LmHttpSession
        if isinstance(ctx, LmHttpSession):
            return self._scan_http(ctx, args)
        page = self._new_page(ctx, args)
        # On charge la fiche produit une fois pour stabiliser le contexte
        # (cookies de session, fingerprint). Pas de clearance manuelle.
        try:
            page.goto(args.product_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        time.sleep(random.uniform(0.4, 1.0))
        return self._scan_on_page(page, args)

    # --- Scan HTTP pur (sans navigateur) ----------------------------------- #
    def _scan_http(self, sess, args) -> dict:
        seeds, zone = self._select_seeds(args)
        verbose = getattr(args, "verbose", False)
        if verbose:
            print(f"  scan HTTP {len(seeds)} points sans navigateur ({zone})")
        all_stores: dict = {}
        blocked = 0
        max_blocks = max(1, getattr(args, "max_blocks", 6))

        # Mint = warmup (homepage + fiche produit) + 1 fetch stock au 1er seed.
        # On réutilise le body du mint comme résultat du seed 0 (pas de double
        # hit Paris Centre). Si le mint échoue -> session burned, on arrête.
        first_label, first_lat, first_lon = seeds[0]
        status, body = sess.mint(first_lat, first_lon)
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
            # mint failed = burned probablement. Si IP connue burned, les
            # fetch_stock suivants retourneront -3 directement.

        # Boucle à partir du seed 1 (seed 0 déjà couvert par le mint).
        for i, (label, lat, lon) in enumerate(seeds[1:], 2):
            status, body = sess.fetch_stock(lat, lon)
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
            # Cadence courte : le _refetch_document dans fetch_stock fait déjà
            # le travail de trust (2x GET document + pauses), pas besoin
            # d'attente supplémentaire longue entre seeds.
            if i < len(seeds):
                time.sleep(random.uniform(1.0, 2.0))
        return {"stores": all_stores, "blocked": blocked, "seeds": len(seeds),
                "completed": blocked == 0,
                "extra": {"zone": zone, "engine": "http"}}

    def _scan_on_page(self, page, args) -> dict:
        seeds, zone = self._select_seeds(args)

        if getattr(args, "slow", False):
            return self._run_sequential(page, args, seeds, zone)

        batch_size = max(1, args.batch_size)
        tries = max(1, args.tries_per_seed)
        verbose = getattr(args, "verbose", False)
        if verbose:
            print(f"  scan {len(seeds)} points en rafale (batch={batch_size}, {zone})")
        all_stores: dict = {}
        results = _batch_fetch(page, seeds, args.product_ref, batch_size)
        pending = []
        for (label, lat, lon), (status, body) in zip(seeds, results):
            if looks_blocked(status, body):
                pending.append((label, lat, lon))
            else:
                aggregate(_parse_stores(body), all_stores)

        blocked = 0
        for attempt in range(1, tries + 1):
            if not pending:
                break
            if verbose:
                print(f"  ⚠ {len(pending)} bloqués — retry (essai {attempt}/{tries})")
            sleep_between(args, long=True)
            retry_results = _batch_fetch(page, pending, args.product_ref, batch_size)
            new_pending = []
            for (label, lat, lon), (status, body) in zip(pending, retry_results):
                if looks_blocked(status, body):
                    new_pending.append((label, lat, lon))
                else:
                    aggregate(_parse_stores(body), all_stores)
            if len(new_pending) == len(pending):
                blocked = len(new_pending)
                break
            pending = new_pending
        else:
            blocked = len(pending)

        cov = len(all_stores)
        if cov == 0:
            if verbose:
                print("  couverture nulle, bascule en mode lent…")
            return self._run_sequential(page, args, seeds, zone)

        return {"stores": all_stores, "blocked": blocked, "seeds": len(seeds),
                "completed": blocked == 0,
                "extra": {"zone": zone}}

    def _run_sequential(self, page, args, seeds, zone) -> dict:
        ref = args.product_ref
        all_stores: dict = {}
        blocked = 0
        completed = True
        stable_rounds = getattr(args, "stable_rounds", 0)
        stable = 0
        verbose = getattr(args, "verbose", False)

        tries_per_seed = max(1, getattr(args, "tries_per_seed", 3))
        for i, (label, lat, lon) in enumerate(seeds, 1):
            body = None
            for attempt in range(1, tries_per_seed + 1):
                status, b = _fetch_seed(page, lat, lon, ref)
                if not looks_blocked(status, b):
                    body = b
                    if verbose and attempt > 1:
                        print(f"    {i}/{len(seeds)} {label} récupéré (essai {attempt})")
                    break
                if verbose:
                    print(f"    {i}/{len(seeds)} {label} bloqué (status={status}, "
                          f"essai {attempt}/{tries_per_seed})")
                if attempt < tries_per_seed:
                    sleep_between(args, long=True)
            if body is None:
                blocked += 1
                completed = False
                if blocked >= args.max_blocks:
                    break
                sleep_between(args, long=True)
                continue
            found = _parse_stores(body)
            new = aggregate(found, all_stores)
            if verbose:
                print(f"    {i}/{len(seeds)} {label} : {len(found)} magasins (+{new})")
            stable = stable + 1 if new == 0 else 0
            if stable_rounds and all_stores and stable >= stable_rounds:
                break
            if i < len(seeds):
                sleep_between(args)

        return {"stores": all_stores, "blocked": blocked, "seeds": len(seeds),
                "completed": completed,
                "extra": {"zone": zone}}
