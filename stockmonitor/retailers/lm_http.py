"""Leroy Merlin — transport HTTP pur (sans navigateur pour le scan).

Une session HTTP (curl_cffi) interroge l'endpoint `store-search-result` pour
récupérer le stock par magasin. Un warmup initial charge la homepage + la
fiche produit pour établir une session valide, puis les requêtes stock sont
émises. La réponse (fragment HTML) est parsée par le même _parse_stores() que
le chemin Camoufox. Un seul warmup sert ensuite plusieurs seeds.
"""
from __future__ import annotations

import json
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Après une série d'échecs, on met la session en pause pendant ce délai
# plutôt que de re-solliciter le site immédiatement à chaque relance.
BURNED_COOLDOWN_S = 6 * 3600

STOCK_URL = (
    "https://www.leroymerlin.fr/store-header-module/services/contextlayer/"
    "store-search-result?latitude={lat}&longitude={lon}"
    "&productRef={ref}&storeSearchType=STOCK"
)
NAV_HEADERS = {
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# Header Accept d'un XHR axios vers l'endpoint stock.
XHR_ACCEPT = "application/json, text/plain, */*"


def _require_runtime() -> None:
    """Vérifie curl_cffi, sinon message clair."""
    try:
        from curl_cffi import requests as creq  # noqa: F401
    except ImportError:
        sys.exit(
            "curl_cffi requis pour le mode HTTP.\n"
            "Installe : pip install curl_cffi\n"
            "ou lance avec --use-camoufox."
        )


class LmHttpSession:
    """Session HTTP : warmup + fetch stock, sans navigateur."""

    def __init__(self, args):
        from curl_cffi import requests as creq  # import tardif (dépendance optionnelle)
        self.args = args
        self.product_url = args.product_url
        self.product_ref = args.product_ref
        self.impersonate = getattr(args, "impersonate", "firefox135")
        self.verbose = getattr(args, "verbose", False)
        self.s = creq.Session(impersonate=self.impersonate, timeout=30)
        self.burned: bool = False
        # Warmup : on ne tape l'endpoint stock qu'après avoir visité homepage +
        # fiche produit (l'endpoint attend une session déjà établie).
        self.warmed: bool = False
        # État disque : cookies + fenêtre de pause, partagés entre lancements
        # successifs du script (un process par cycle de scan). Sans ça, chaque
        # lancement referait un warmup à froid.
        self.state_path = Path(args.data_dir) / "lm_http_state.json"
        self.burned_until: float | None = None
        self._load_state()

    # --- état disque (cookies + pause, entre lancements) ----------------- #
    def _load_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        burned_until = state.get("burned_until")
        if burned_until and time.time() < burned_until:
            self.burned = True
            self.burned_until = burned_until
            if self.verbose:
                remaining = int(burned_until - time.time())
                print(f"  session: en pause ({remaining}s restantes), "
                      f"on ne sollicite pas le site.")
            return
        for name, value in (state.get("cookies") or {}).items():
            try:
                self.s.cookies.set(name, value, domain=".leroymerlin.fr", path="/")
            except Exception:
                pass
        if state.get("warmed") and state.get("cookies"):
            # Cookies déjà en jar -> on saute le warmup réseau (homepage
            # + fiche produit) qui ne sert qu'à amorcer une session absente.
            self.warmed = True
            if self.verbose:
                print("  session: cookies réutilisés depuis le disque, warmup sauté.")

    def _save_state(self) -> None:
        """Écrit cookies + warmed + burned_until (si fixé) sur disque.

        Toujours réémettre `self.burned_until` ici (pas juste au moment où on
        le fixe) : sinon un appel ultérieur sans cet argument écraserait la
        fenêtre de pause déjà posée et un prochain lancement re-solliciterait
        le site pendant la fenêtre qu'on voulait éviter.
        """
        cookies = {}
        try:
            cookies = {c.name: c.value for c in self.s.cookies.jar}
        except Exception:
            pass
        state = {"cookies": cookies, "warmed": self.warmed}
        if self.burned_until is not None:
            state["burned_until"] = self.burned_until
        try:
            self.state_path.write_text(json.dumps(state))
        except OSError:
            pass

    # --- warmup (une fois, avant mint/scan) ------------------------------ #
    def _warmup(self) -> None:
        """Pré-charge la session avant toute requête stock, en 2 phases.

        Phase 1 — Camoufox (navigateur) visite homepage + fiche produit et
          laisse les scripts de la page s'exécuter normalement, ce qui établit
          les cookies de session.

        Phase 2 — curl_cffi récupère les cookies posés par Camoufox et les
          réutilise pour ses requêtes stock.

        Camoufox n'est lancé qu'UNE fois au démarrage ; les cycles de scan
        suivants (mode --loop) réutilisent la session via curl_cffi seul.
        """
        if self.warmed or self.burned:
            return
        if self.verbose:
            print("  warmup : Camoufox…")
        try:
            self._camoufox_warmup()
        except Exception as e:
            if self.verbose:
                print(f"    [camoufox warmup] erreur: {e!r}, fallback curl_cffi seul")
            # Fallback : warmup curl_cffi seul (session partielle)
            try:
                self.s.get("https://www.leroymerlin.fr/", headers=NAV_HEADERS, timeout=30)
                self.s.get(self.product_url, headers=NAV_HEADERS, timeout=30)
            except Exception:
                pass
        self.warmed = True

    def _camoufox_warmup(self) -> None:
        """Lance Camoufox pour établir la session sur les pages du site.

        Visite homepage + fiche produit, laisse les scripts de la page
        s'exécuter quelques secondes, puis transfère les cookies vers curl_cffi.
        """
        from camoufox.sync_api import Camoufox
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir, \
             Camoufox(
                 headless=True, humanize=True, os=["macos"], locale="fr-FR",
                 geoip=True, persistent_context=True, user_data_dir=tmpdir,
             ) as ctx:
            page = ctx.new_page()
            captured: dict = {"beacons": 0, "cookies": {}}
            def _on_request(req):
                if "/js/" in req.url and req.method == "POST":
                    captured["beacons"] += 1  # compteur de diagnostic
            page.on("request", _on_request)
            try:
                page.goto("https://www.leroymerlin.fr/",
                          wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
            time.sleep(random.uniform(3.0, 5.0))
            try:
                page.goto(self.product_url,
                          wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
            # Laisser la page finir de charger ses scripts (max 8 s).
            deadline = time.time() + 8
            while time.time() < deadline and captured["beacons"] == 0:
                page.wait_for_timeout(200)
            # Extraire les cookies de Camoufox et les transférer à curl_cffi
            for c in ctx.cookies():
                if c.get("domain", "").endswith("leroymerlin.fr"):
                    try:
                        self.s.cookies.set(c["name"], c["value"],
                                           domain=".leroymerlin.fr", path="/")
                        captured["cookies"][c["name"]] = c["value"]
                    except Exception:
                        pass
            if self.verbose:
                print(f"    [camoufox warmup] beacons x{captured['beacons']} "
                      f"cookies={list(captured['cookies'])}")

    def _refetch_document(self):
        """Re-GET la fiche produit entre deux requêtes stock.

        On recharge la page HTML de la fiche produit juste avant la requête
        stock suivante, pour rester cohérent avec un parcours de navigation
        classique. À appeler avant chaque _stock().
        """
        try:
            self.s.get(self.product_url, headers=NAV_HEADERS, timeout=30)
        except Exception:
            pass

    # --- requêtes ---------------------------------------------------------- #
    def _stock(self, lat, lon):
        # On ne set pas `cookie` à la main : ça écraserait la jar curl_cffi qui
        # contient déjà tous les cookies de session posés au warmup. curl_cffi
        # les envoie automatiquement.
        sh = {**NAV_HEADERS, "accept": XHR_ACCEPT, "referer": self.product_url,
              "origin": "https://www.leroymerlin.fr",
              "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin"}
        return self.s.get(STOCK_URL.format(lat=lat, lon=lon, ref=self.product_ref), headers=sh)

    # --- API publique ------------------------------------------------------ #
    def fetch_stock(self, lat, lon, max_rounds: int = 4):
        """Renvoie (status, body) pour un seed, avec retry sur erreur.

        Avant chaque requête stock, on re-GET la fiche produit. En cas
        d'échec, on re-GET et on retente sur plusieurs tours.
        """
        r = None
        for attempt in range(max_rounds):
            # GET de la fiche produit avant la requête stock, pour rester
            # cohérent avec un parcours de navigation.
            self._refetch_document()
            time.sleep(random.uniform(0.5, 1.0))
            r = self._stock(lat, lon)
            if r.status_code == 200 and "m-store-search-result" in r.text:
                self._save_state()  # session confirmée -> réutilisable au run suivant
                return 200, r.text
            if self.verbose and attempt < max_rounds - 1:
                print(f"    [{lat:.4f},{lon:.4f}] attempt {attempt+1}/{max_rounds} "
                      f"status={r.status_code}, re-GET document pour retry…")
            time.sleep(random.uniform(1.0, 2.0))
        return r.status_code if r is not None else -3, r.text if r else ""

    def mint(self, lat: float = 48.8566, lon: float = 2.3522, max_rounds: int = 5) -> tuple[int, str]:
        """Amorce la session : warmup + 1 fetch stock.

        Renvoie (status, body) — `_scan_http` réutilise le body du mint comme
        1er seed (pas de double hit Paris Centre).
        """
        self._warmup()
        return self.fetch_stock(lat, lon, max_rounds=max_rounds)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


@contextmanager
def open_http_context(args):
    """Context manager yieldant une LmHttpSession prête à l'emploi."""
    _require_runtime()
    sess = LmHttpSession(args)
    try:
        yield sess
    finally:
        sess.close()
