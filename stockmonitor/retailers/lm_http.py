"""Leroy Merlin — transport HTTP pur (zéro navigateur pour le scan).

leroymerlin.fr est protégé par DataDome. La stratégie éprouvée :

  1. curl_cffi (impersonate firefox135) émet tout le HTTP avec un JA3 Firefox.
  2. Warmup : 2x GET homepage + GET fiche produit. Le cookie datadome posé
     par ces GET document est trusté par DataDome (le JA3 curl_cffi firefox135
     est cohérent avec le parcours navigateur). PAS besoin de solve Camoufox
     en warmup : le solve du challenge interstitiel renvoie systematiquement
     `view:"captcha"` (= refusé) et nuit au score IP sans gain de trust.
  3. Avant chaque XHR stock, on re-GET la fiche produit (comportement humain).
     En cas de 403, on re-GET et on retente : le trust se construit
     progressivement (DataDome renforce le cookie à chaque interaction document).
  4. L'endpoint stock répond 200 avec le fragment HTML habituel, parsé par
     le même _parse_stores() que le chemin Camoufox.

Un seul mint sert ensuite plusieurs seeds (mint-once -> scan-many) ; on ne
re-résout jamais un challenge (le solve nuit au score IP).
"""
from __future__ import annotations

import json
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Cooldown après IP burned : on arrête complètement de solliciter le site
# (même le warmup) pendant ce délai, pour laisser le score DataDome se
# refroidir au lieu de le réescalader à chaque relance du script.
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
# Accept réel d'un XHR axios vers l'endpoint stock (cohérent avec le chemin
# Camoufox — était "*/*" avant, ce qui dénotait avec le navigateur réel).
XHR_ACCEPT = "application/json, text/plain, */*"


def _require_runtime() -> None:
    """Vérifie curl_cffi, sinon message clair."""
    try:
        from curl_cffi import requests as creq  # noqa: F401
    except ImportError:
        sys.exit(
            "curl_cffi requis pour le mode HTTP (empreinte TLS Firefox).\n"
            "Installe : pip install curl_cffi\n"
            "ou lance avec --use-camoufox."
        )


class LmHttpSession:
    """Session DataDome-aware : warmup + fetch stock, sans navigateur."""

    def __init__(self, args):
        from curl_cffi import requests as creq  # import tardif (dépendance optionnelle)
        self.args = args
        self.product_url = args.product_url
        self.product_ref = args.product_ref
        self.impersonate = getattr(args, "impersonate", "firefox135")
        self.verbose = getattr(args, "verbose", False)
        self.s = creq.Session(impersonate=self.impersonate, timeout=30)
        self.burned: bool = False
        # Warmup : on ne tape l'endpoint stock qu'après avoir réellement visité
        # homepage + fiche produit (sinon DataDome challenge sur le 1er hit,
        # car sec-fetch-site: same-origin + referer sont des mensonges).
        self.warmed: bool = False
        # État disque : cookie trusted + fenêtre burned, partagés entre lancements
        # successifs du script (un process par cycle de scan). Sans ça, chaque
        # lancement refait un warmup à froid, ce qui sollicite DataDome.
        self.state_path = Path(args.data_dir) / "lm_http_state.json"
        self.burned_until: float | None = None
        self._load_state()

    # --- état disque (cookie + cooldown burned, entre lancements) -------- #
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
                print(f"  session: IP en cooldown ({remaining}s restantes), "
                      f"on ne sollicite pas le site.")
            return
        for name, value in (state.get("cookies") or {}).items():
            try:
                self.s.cookies.set(name, value, domain=".leroymerlin.fr", path="/")
            except Exception:
                pass
        if state.get("warmed") and state.get("cookies"):
            # Cookie trusted déjà en jar -> on saute le warmup réseau (homepage
            # + fiche produit) qui ne sert qu'à amorcer un cookie absent.
            self.warmed = True
            if self.verbose:
                print("  session: cookie trusted réutilisé depuis le disque, warmup sauté.")

    def _save_state(self) -> None:
        """Écrit cookies + warmed + burned_until (si fixé) sur disque.

        Toujours réémettre `self.burned_until` ici (pas juste au moment où on
        le fixe) : sinon un appel ultérieur sans cet argument écraserait le
        cooldown déjà posé et un prochain lancement re-solliciterait le site
        à froid pendant la fenêtre qu'on voulait justement éviter.
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

    # --- warmup ( warmup-once, avant mint/scan) -------------------------- #
    def _warmup(self) -> None:
        """Pré-charge la session avant tout XHR stock, en 2 phases.

        Phase 1 — Camoufox (vrai Firefox) visite homepage + fiche produit.
          Le tags.js DataDome (proxy first-party bot.cdn.adeo.cloud/tags.js)
          s'exécute dans le vrai moteur Gecko et envoie son beacon POST /js/
          au complet. DataDome valide la télémétrie (mouse/timing/events) et
          "promeut" le cookie datadome en état trusted full. C'est la
          différence clé vs curl_cffi seul (qui n'exécute pas le JS → aucun
          beacon jamais envoyé → trust partiel → 403 stochastiques).

        Phase 2 — curl_cffi (JA3 firefox135 ≈ Firefox natif) récupère les
          cookies posés par Camoufox et les réutilise pour ses XHR stock. Le
          JA3 cohérent entre Camoufox et curl_cffi firefox135 garantit que
          DataDome lié le cookie au JA3 ne rejette pas le trust.

        Anti-grillade : on ne lance Camoufox qu'UNE fois au démarrage (warmup).
        Les cycles de scan suivants (mode --loop) ne relancent pas Camoufox :
        le trust accumulé par le premier beacon suffit, et curl_cffi le
        maintient par ses GET document répétés.
        """
        if self.warmed or self.burned:
            return
        if self.verbose:
            print("  warmup : Camoufox (tags.js -> beacon /js/)…")
        try:
            self._camoufox_warmup()
        except Exception as e:
            if self.verbose:
                print(f"    [camoufox warmup] erreur: {e!r}, fallback curl_cffi seul")
            # Fallback : warmup curl_cffi seul (trust partiel, 403 probable)
            try:
                self.s.get("https://www.leroymerlin.fr/", headers=NAV_HEADERS, timeout=30)
                self.s.get(self.product_url, headers=NAV_HEADERS, timeout=30)
            except Exception:
                pass
        self.warmed = True

    def _camoufox_warmup(self) -> None:
        """Lance Camoufox pour laisser le tags.js DataDome envoyer son beacon.

        Visite homepage + fiche produit, attend 6-10 s que le tags.js déclenche
        le POST /js/ (télémétrie), puis transfère les cookies vers curl_cffi.
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
                    captured["beacons"] += 1
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
            # Attendre le beacon /js/ (max 8 s) : le tags.js l'envoie après
            # quelques secondes d'observation des events.
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
                print(f"    [camoufox warmup] beacons=/js/ x{captured['beacons']} "
                      f"cookies={list(captured['cookies'])}")

    def _refetch_document(self):
        """Re-GET la fiche produit entre deux XHR stock (comportement humain).

        DataDome consomme le trust à chaque XHR : après 1 hit XHR, le score se
        dégrade si on n'a pas rechargé une page HTML. Un GET de la fiche produit
        juste avant le prochain XHR simule un vrai parcours utilisateur et
        renouvelle le trust. À appeler avant chaque _stock().
        """
        try:
            self.s.get(self.product_url, headers=NAV_HEADERS, timeout=30)
        except Exception:
            pass

    # --- requêtes ---------------------------------------------------------- #
    def _stock(self, lat, lon):
        # On NE set pas `cookie` à la main : ça écrase la jar curl_cffi qui
        # contient les cookies de session LM (warmup) + le datadome trusted
        # (posé par le POST /interstitial/). DataDome voit un cookie datadome
        # seul = flagrant (pas de cookies de navigation) => 403.
        # curl_cffi envoie tout automatiquement.
        sh = {**NAV_HEADERS, "accept": XHR_ACCEPT, "referer": self.product_url,
              "origin": "https://www.leroymerlin.fr",
              "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin"}
        return self.s.get(STOCK_URL.format(lat=lat, lon=lon, ref=self.product_ref), headers=sh)

    # --- API publique ------------------------------------------------------ #
    def fetch_stock(self, lat, lon, max_rounds: int = 4):
        """Renvoie (status, body) pour un seed, avec retry sur 403.

        Le trust vient des GET document répétés. Avant chaque XHR stock, on
        re-GET la fiche produit 2x (au lieu d'une fois) pour renforcer le
        trust et accélérer son établissement. En cas de 403, on re-GET et
        on retente : le trust se construit progressivement.
        """
        r = None
        for attempt in range(max_rounds):
            # 1x GET document avant le XHR stock pour préserver le trust.
            # Le trust principal vient du beacon /js/ envoyé par Camoufox en
            # warmup ; le GET document suffit à le renouveler à chaque appel.
            self._refetch_document()
            time.sleep(random.uniform(0.5, 1.0))
            r = self._stock(lat, lon)
            if r.status_code == 200 and "m-store-search-result" in r.text:
                self._save_state()  # cookie trusted confirmé -> réutilisable au run suivant
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
