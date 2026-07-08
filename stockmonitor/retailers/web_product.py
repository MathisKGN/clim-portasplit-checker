"""Scanner générique de fiche produit web.

Pour les enseignes sans API stock connue dans ce projet, on vérifie la fiche
produit avec Camoufox et on classe la disponibilité à partir du texte visible.
Ce chemin ne réutilise pas le cookie DataDome Leroy Merlin : il sert aux pages
protégées autrement (Cloudflare, Akamai/Queue-it, etc.).
"""
from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import ScannerBase
from ..common import normalize_text


BLOCK_PATTERNS = (
    "just a moment",
    "enable javascript and cookies",
    "challenges.cloudflare.com",
    "queue.fnacdarty.com",
    "queue-it",
    "x-queueit",
    "drop-page",
    "type=waf",
    "captcha",
    "datadome",
)

OUT_PATTERNS = (
    "produit indisponible",
    "produit epuis",
    "epuise",
    "rupture",
    "indisponible",
    "bientot de retour en stock",
    "me prevenir",
)

IN_PATTERNS = (
    "ajouter au panier",
    "en stock",
    "livre des",
    "livraison gratuite",
    "retirer en magasin",
    "retrait des",
)


def _structured_availability(html: str, url: str = "") -> tuple[str, str] | None:
    """Lit les signaux schema.org / WooCommerce quand la page les expose."""
    soup = BeautifulSoup(html or "", "lxml")
    values: list[str] = []

    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or "").strip().lower()
        if key in {"product:availability", "availability", "og:availability"}:
            content = (tag.get("content") or "").strip()
            if content:
                values.append(content)

    for tag in soup.find_all(attrs={"itemprop": "availability"}):
        content = (tag.get("content") or tag.get("href") or tag.get_text(" ", strip=True))
        if content:
            values.append(str(content).strip())

    for value in values:
        norm = normalize_text(urljoin(url, value))
        if "outofstock" in norm or "out of stock" in norm or "rupture" in norm:
            return "OUT", value
        if "instock" in norm or "in stock" in norm or "en stock" in norm:
            return "IN", value
    return None


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def _compact(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def classify_product_page(html: str, url: str = "") -> tuple[str, str, bool]:
    """Renvoie (state, status_text, blocked)."""
    raw = html or ""
    visible = _visible_text(raw)
    norm = normalize_text(f"{url} {raw[:4000]} {visible}")

    structured = _structured_availability(raw, url)
    if structured:
        state, status_text = structured
        return state, status_text, False

    if any(p in norm for p in BLOCK_PATTERNS):
        return "UNKNOWN", "Page bloquée par protection anti-bot", True

    out_hits = [p for p in OUT_PATTERNS if p in norm]
    in_hits = [p for p in IN_PATTERNS if p in norm]

    if out_hits:
        return "OUT", out_hits[0], False
    if in_hits:
        return "IN", in_hits[0], False
    return "UNKNOWN", _compact(visible) or "Statut introuvable", False


class WebProductScanner(ScannerBase):
    """Base pour un scan de disponibilité d'une fiche produit unique."""

    RETAILER_NAME = "Web"
    FILE_PREFIX = "web"
    ENV_PREFIX = "WEB"
    CONFIG_KEY = "web"
    DEFAULT_PRODUCT_REF = ""
    DEFAULT_PRODUCT_URL = ""

    @classmethod
    def get_defaults(cls) -> dict:
        return {
            "min_delay": 1.0,
            "max_delay": 2.0,
            "stable_rounds": 1,
            "product_ref": cls.DEFAULT_PRODUCT_REF,
            "product_url": cls.DEFAULT_PRODUCT_URL,
        }

    def add_arguments(self, parser):
        pass

    @contextmanager
    def open_context(self, args):
        try:
            from camoufox.sync_api import Camoufox
        except ImportError:
            sys.exit("Manque Camoufox. Installe : pip install 'camoufox[geoip]'")

        with Camoufox(
            headless=True,
            humanize=True,
            os=["macos"],
            locale="fr-FR",
            geoip=True,
        ) as ctx:
            yield ctx

    def store_url(self, store: dict) -> str:
        return store.get("url") or self.DEFAULT_PRODUCT_URL

    def csv_header(self):
        return ["id", "canal", "etat", "statut_texte", "url"]

    def csv_row(self, store):
        return [
            store.get("id", ""),
            store.get("name", ""),
            store.get("state", ""),
            store.get("status_text", ""),
            self.store_url(store),
        ]

    def scan(self, ctx, args) -> dict:
        url = args.product_url
        ref = getattr(args, "product_ref", None) or self.DEFAULT_PRODUCT_REF
        self._emit("scan_start", total_seeds=1, zone="online",
                   product_ref=ref, product_url=url)
        self._emit("seed_start", index=1, total=1, label="fiche produit")
        self._emit("warmup", phase="browser", detail="camoufox_page")

        page = ctx.new_page()
        status = 0
        html = ""
        final_url = url
        load_error = ""
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            status = resp.status if resp else 0
            self._pause(args)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            html = page.content()
            final_url = page.url
        except Exception as e:
            load_error = repr(e)
        finally:
            try:
                page.close()
            except Exception:
                pass

        if load_error:
            state, status_text, blocked = "UNKNOWN", f"Chargement échoué: {load_error}", True
        else:
            state, status_text, blocked = classify_product_page(html, final_url)
        if blocked or status in {403, 429, 503}:
            self._emit("seed_blocked", index=1, total=1,
                       label="fiche produit", status=status or "anti-bot")
            completed = False
            blocked_count = 1
        else:
            completed = True
            blocked_count = 0

        store = {
            "id": "online",
            "name": "En ligne",
            "state": state,
            "status_text": status_text,
            "restock": state == "IN",
            "url": url,
            "http_status": status,
        }
        self._emit("seed_done", index=1, total=1, label="fiche produit",
                   found=1, new=1, total_stores=1, stores_added=[store])
        self._emit("scan_done", total_stores=1, in_stock=1 if store["restock"] else 0,
                   blocked=blocked_count, completed=completed, seeds_used=1)
        return {
            "stores": {"online": store},
            "blocked": blocked_count,
            "seeds": 1,
            "completed": completed,
            "extra": {"engine": "camoufox_product_page"},
        }
