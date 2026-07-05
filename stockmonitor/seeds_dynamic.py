"""Seeds LM calculés à la volée depuis un code postal + un rayon.

Le mode interactif demande un code postal et un rayon (5-700 km). On en dérive :
  1. le centre (lat/lon) via géocodage du code postal (APIs publiques, sans clé) ;
  2. la liste des magasins LM à <= rayon du centre (data/lm_stores.json) ;
  3. le jeu minimal de seeds (set-cover greedy) couvrant ces magasins.

Même algo que tools/gen_seeds_france.py, mais exécuté au runtime pour ne pas
figer des zones prédéfinies : l'utilisateur choisit son périmètre, on calcule
les bons points automatiquement.
"""
from __future__ import annotations

import json
import math
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# data/lm_stores.json est un cache local. Il n'est pas forcément présent chez
# les utilisateurs qui téléchargent le ZIP GitHub, donc on sait le recréer.
_STORES_PATH = Path(__file__).resolve().parent.parent / "data" / "lm_stores.json"

WOOSMAP_KEY = "woos-47262215-fc76-3bd2-8e0d-d8fda2544349"
WOOSMAP_URL = (
    "https://api.woosmap.com/stores/search/"
    "?key={key}&lat=46.6&lng=2.4&max_distance=3000000&stores_by_page=300&page={page}"
)
WOOSMAP_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.leroymerlin.fr/",
    "Origin": "https://www.leroymerlin.fr",
}

# Nb de magasins supposés « vus » par seed. L'endpoint stock LM en renvoie ~11 ;
# on prend une marge (8) pour rester couvrant si un magasin ouvre à côté.
DEFAULT_MARGIN = 8


def _ssl_context() -> ssl.SSLContext | None:
    """Contexte SSL basé sur le bundle certifi si disponible.

    Le Python de python.org sur macOS ne valide pas les certificats tant que
    « Install Certificates.command » n'a pas été lancé : `urllib` échoue alors
    avec CERTIFICATE_VERIFY_FAILED sur tout appel HTTPS. certifi est déjà
    présent (dépendance de requests) ; on s'appuie dessus pour que ça marche
    sans intervention. En cas d'absence, on retombe sur le contexte par défaut.
    """
    try:
        import certifi
    except ImportError:
        return None
    try:
        return ssl.create_default_context(cafile=certifi.where())
    except (OSError, ssl.SSLError):
        return None


_SSL_CONTEXT = _ssl_context()


class GeocodeError(RuntimeError):
    """Erreur utilisateur pendant la conversion code postal -> coordonnées."""

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class PostcodeNotFound(GeocodeError):
    """Le code postal est valide syntaxiquement, mais inconnu des APIs."""


class GeocodeServiceError(GeocodeError):
    """Erreur technique pendant l'appel aux APIs de géocodage."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _mac_certificate_hint() -> str | None:
    if sys.platform != "darwin":
        return None
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
    return (
        "Sur Mac avec Python depuis python.org, lance cette commande puis "
        f"réessaie : open \"/Applications/Python {pyver}/Install Certificates.command\""
    )


def _has_certificate_error(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    text = str(exc)
    return (
        "CERTIFICATE_VERIFY_FAILED" in text
        or "certificate verify failed" in text.lower()
    )


def _request_json(url: str, service: str):
    req = urllib.request.Request(url, headers={"User-Agent": "stockmonitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CONTEXT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        reason = f" {e.reason}" if e.reason else ""
        raise GeocodeServiceError(
            f"{service} a répondu HTTP {e.code}{reason}."
        ) from e
    except urllib.error.URLError as e:
        reason = e.reason
        if _has_certificate_error(e) or _has_certificate_error(reason):
            raise GeocodeServiceError(
                f"Erreur SSL en appelant {service}: certificat HTTPS non validé.",
                hint=_mac_certificate_hint(),
            ) from e
        if isinstance(reason, socket.gaierror):
            detail = getattr(reason, "strerror", None) or str(reason)
            raise GeocodeServiceError(
                f"DNS impossible pour {service}: {detail}."
            ) from e
        if isinstance(reason, TimeoutError):
            raise GeocodeServiceError(
                f"Timeout en appelant {service} après 10 secondes."
            ) from e
        raise GeocodeServiceError(
            f"Connexion impossible à {service}: {reason!r}."
        ) from e
    except TimeoutError as e:
        raise GeocodeServiceError(
            f"Timeout en appelant {service} après 10 secondes."
        ) from e
    except json.JSONDecodeError as e:
        raise GeocodeServiceError(
            f"{service} a répondu, mais pas avec du JSON valide."
        ) from e


def _coordinates_from_geo_api(cp: str) -> tuple[float, float]:
    cp = cp.strip()
    url = ("https://geo.api.gouv.fr/communes?"
           + urllib.parse.urlencode({"codePostal": cp,
                                     "fields": "nom,centre,population",
                                     "format": "json"}))
    data = _request_json(url, "geo.api.gouv.fr")
    if not isinstance(data, list):
        raise GeocodeServiceError(
            "Réponse geo.api.gouv.fr inattendue: JSON racine non-liste."
        )
    if not data:
        raise PostcodeNotFound(
            f"Code postal {cp} introuvable dans geo.api.gouv.fr."
        )
    data = [item for item in data if isinstance(item, dict)]
    if not data:
        raise GeocodeServiceError(
            "Réponse geo.api.gouv.fr inattendue: aucune commune exploitable."
        )
    # Plusieurs communes peuvent partager un CP : on prend la plus peuplée
    # (centre le plus représentatif de la zone).
    data.sort(key=lambda c: c.get("population", 0) or 0, reverse=True)
    coords = data[0].get("centre", {}).get("coordinates")
    if not coords or len(coords) != 2:
        raise GeocodeServiceError(
            "Réponse geo.api.gouv.fr inattendue: champ centre.coordinates absent."
        )
    try:
        lon, lat = coords  # GeoJSON = [lon, lat]
        return float(lat), float(lon)
    except (TypeError, ValueError) as e:
        raise GeocodeServiceError(
            "Réponse geo.api.gouv.fr inattendue: coordonnées non numériques."
        ) from e


def _coordinates_from_adresse_api(cp: str) -> tuple[float, float]:
    url = ("https://api-adresse.data.gouv.fr/search/?"
           + urllib.parse.urlencode({"q": cp,
                                     "type": "municipality",
                                     "limit": 5}))
    data = _request_json(url, "api-adresse.data.gouv.fr")
    features = data.get("features", []) if isinstance(data, dict) else []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties", {}) or {}
        if props.get("postcode") != cp:
            continue
        coords = (feature.get("geometry", {}) or {}).get("coordinates")
        if coords and len(coords) == 2:
            try:
                lon, lat = coords
                return float(lat), float(lon)
            except (TypeError, ValueError) as e:
                raise GeocodeServiceError(
                    "Réponse api-adresse.data.gouv.fr inattendue: "
                    "coordonnées non numériques."
                ) from e
    raise PostcodeNotFound(
        f"Code postal {cp} introuvable dans api-adresse.data.gouv.fr."
    )


def geocode_cp_or_raise(cp: str) -> tuple[float, float]:
    """Code postal -> (lat, lon), avec une erreur exploitable si ça échoue.

    Source principale : geo.api.gouv.fr. Fallback : api-adresse.data.gouv.fr.
    Les deux APIs sont publiques, gratuites et sans clé.
    """
    cp = cp.strip()
    if not re.fullmatch(r"\d{5}", cp):
        raise PostcodeNotFound(f"Code postal invalide: {cp!r}.")

    primary_error: GeocodeServiceError | None = None
    try:
        return _coordinates_from_geo_api(cp)
    except GeocodeServiceError as e:
        primary_error = e
    except PostcodeNotFound:
        pass

    try:
        return _coordinates_from_adresse_api(cp)
    except PostcodeNotFound as e:
        if primary_error:
            raise GeocodeServiceError(
                f"{primary_error} Géocodage de secours: {e}",
                hint=primary_error.hint,
            ) from e
        raise PostcodeNotFound(f"Code postal {cp} introuvable.") from e
    except GeocodeServiceError as e:
        if primary_error:
            raise GeocodeServiceError(
                f"{primary_error} Géocodage de secours: {e}",
                hint=primary_error.hint or e.hint,
            ) from e
        raise


def geocode_cp(cp: str) -> tuple[float, float] | None:
    """Compatibilité historique : renvoie None au lieu de lever."""
    try:
        return geocode_cp_or_raise(cp)
    except GeocodeError:
        return None


def _fetch_lm_stores() -> list[dict]:
    """Récupère les magasins LM officiels depuis le store-locator Woosmap."""
    features: list[dict] = []
    page = 1
    while True:
        url = WOOSMAP_URL.format(key=WOOSMAP_KEY, page=page)
        req = urllib.request.Request(url, headers=WOOSMAP_HEADERS)
        with urllib.request.urlopen(req, timeout=25, context=_SSL_CONTEXT) as resp:
            data = json.load(resp)
        features.extend(data.get("features", []))
        pagination = data.get("pagination", {})
        if page >= pagination.get("pageCount", 1):
            break
        page += 1

    stores: list[dict] = []
    for feature in features:
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates") or []
        if len(coords) != 2:
            continue
        web = (props.get("contact") or {}).get("website", "") or ""
        match = re.search(r"/magasins/([^./]+)\.html", web)
        if not match:
            continue
        lon, lat = coords
        city = (props.get("address") or {}).get("city", "") or ""
        stores.append({
            "store_id": props.get("store_id"),
            "name": props.get("name", ""),
            "slug": match.group(1),
            "city": city.title() if city.isupper() else city,
            "cp": (props.get("address") or {}).get("zipcode", "") or "",
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
        })
    if not stores:
        raise RuntimeError("liste des magasins Leroy Merlin vide")
    return stores


def _load_stores() -> list[dict]:
    """Magasins uniques (dédup par coordonnée arrondie)."""
    if not _STORES_PATH.exists():
        stores = _fetch_lm_stores()
        _STORES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STORES_PATH.write_text(
            json.dumps(stores, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    raw = json.loads(_STORES_PATH.read_text(encoding="utf-8"))
    uniq: dict = {}
    for s in raw:
        key = (round(s["lat"], 3), round(s["lon"], 3))
        uniq.setdefault(key, s)
    return list(uniq.values())


def _coverage(seed: tuple[float, float], pts: list[dict], n: int) -> set[int]:
    """Indices des N magasins les plus proches de `seed` (= ce que voit le seed)."""
    order = sorted(range(len(pts)),
                   key=lambda i: haversine_km(seed[0], seed[1],
                                              pts[i]["lat"], pts[i]["lon"]))
    return set(order[:n])


def _set_cover(pts: list[dict], n: int) -> list[int]:
    """Greedy set-cover : indices des magasins retenus comme seeds."""
    covs = [_coverage((p["lat"], p["lon"]), pts, n) for p in pts]
    covered: set = set()
    chosen: list = []
    target = set(range(len(pts)))
    while covered != target:
        best = max((i for i in range(len(pts)) if i not in chosen),
                   key=lambda i: len(covs[i] - covered), default=None)
        if best is None or not (covs[best] - covered):
            break
        chosen.append(best)
        covered |= covs[best]
    return chosen


def compute_seeds(center: tuple[float, float], radius_km: float,
                  margin: int = DEFAULT_MARGIN):
    """Calcule les seeds couvrant les magasins à <= radius_km du centre.

    Renvoie (seeds, n_stores) où seeds est une liste de (label, lat, lon),
    ordonnée cœur-d'abord (le point le plus proche du centre en premier).
    n_stores est le nombre de magasins couverts (0 si aucun dans le rayon).
    """
    lat0, lon0 = center
    stores = _load_stores()
    near = [s for s in stores
            if haversine_km(lat0, lon0, s["lat"], s["lon"]) <= radius_km]
    if not near:
        return [], 0
    # Cœur-d'abord : magasin le plus proche du centre en tête (lisibilité).
    near.sort(key=lambda s: haversine_km(lat0, lon0, s["lat"], s["lon"]))

    n = min(margin, len(near))
    chosen = _set_cover(near, n)
    seeds = [(near[i]["city"], round(near[i]["lat"], 4), round(near[i]["lon"], 4))
             for i in chosen]
    # Ordonne les seeds retenus du plus proche au plus loin du centre.
    seeds.sort(key=lambda t: haversine_km(lat0, lon0, t[1], t[2]))
    return seeds, len(near)
