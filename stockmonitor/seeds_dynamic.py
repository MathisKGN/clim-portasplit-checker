"""Seeds LM calculés à la volée depuis un code postal + un rayon.

Le mode interactif demande un code postal et un rayon (5-700 km). On en dérive :
  1. le centre (lat/lon) via géocodage du code postal (geo.api.gouv.fr, sans clé) ;
  2. la liste des magasins LM à <= rayon du centre (data/lm_stores.json) ;
  3. le jeu minimal de seeds (set-cover greedy) couvrant ces magasins.

Même algo que tools/gen_seeds_france.py, mais exécuté au runtime pour ne pas
figer des zones prédéfinies : l'utilisateur choisit son périmètre, on calcule
les bons points automatiquement.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

# data/lm_stores.json est committé à la racine du projet.
_STORES_PATH = Path(__file__).resolve().parent.parent / "data" / "lm_stores.json"

# Nb de magasins supposés « vus » par seed. L'endpoint stock LM en renvoie ~11 ;
# on prend une marge (8) pour rester couvrant si un magasin ouvre à côté.
DEFAULT_MARGIN = 8


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def geocode_cp(cp: str) -> tuple[float, float] | None:
    """Code postal -> (lat, lon) du centre de la commune principale.

    Utilise l'API publique geo.api.gouv.fr (gratuite, sans clé). Renvoie None
    si le code postal est inconnu ou si l'appel échoue (pas de réseau…).
    """
    cp = cp.strip()
    url = ("https://geo.api.gouv.fr/communes?"
           + urllib.parse.urlencode({"codePostal": cp,
                                     "fields": "nom,centre,population",
                                     "format": "json"}))
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
    except Exception:
        return None
    if not data:
        return None
    # Plusieurs communes peuvent partager un CP : on prend la plus peuplée
    # (centre le plus représentatif de la zone).
    data.sort(key=lambda c: c.get("population", 0) or 0, reverse=True)
    coords = data[0].get("centre", {}).get("coordinates")
    if not coords or len(coords) != 2:
        return None
    lon, lat = coords  # GeoJSON = [lon, lat]
    return float(lat), float(lon)


def _load_stores() -> list[dict]:
    """Magasins uniques (dédup par coordonnée arrondie)."""
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
