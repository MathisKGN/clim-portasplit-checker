"""Utilitaires partagés par les adapteurs de stock.

Rien de spécifique à une enseigne ici : timestamp, I/O JSON/CSV, HTTP retry,
small helpers. On garde les fonctions SMALL et sans état.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
import time
import unicodedata
from pathlib import Path


# --------------------------------------------------------------------------- #
# Temps / hasard
# --------------------------------------------------------------------------- #
def ts() -> str:
    """Horodatage local compact."""
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def short_loop_warning(seconds: int) -> str:
    """Message d'avertissement pour les boucles trop rapprochées."""
    label = f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds} s"
    return (
        f"Attention : intervalle de {label}. "
        "Plus l'intervalle est court, plus tu augmentes les chances d'être "
        "bloqué par les protections anti-bot des sites."
    )


# --------------------------------------------------------------------------- #
# I/O JSON / CSV / state
# --------------------------------------------------------------------------- #
def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state(path: Path) -> dict:
    """Charge un state.json (anti-spam d'alerte). Tolérant aux corruptions."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def append_history(path: Path, record: dict):
    """Append-only JSONL — une ligne par run (historique léger)."""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# --------------------------------------------------------------------------- #
# HTTP (requests) — utilisé par les adapteurs sans navigateur.
# --------------------------------------------------------------------------- #
def http_get(session, url: str, *, headers=None, tries: int = 4, timeout: int = 30):
    """GET avec petits retries sur 5xx / erreurs réseau.

    `session` doit être une `requests.Session`. Renvoie une `Response` ou lève
    la dernière exception.
    """
    import requests  # local : seulement les adapteurs qui en ont besoin
    last = None
    for i in range(tries):
        try:
            r = session.get(url, headers=headers or {}, timeout=timeout)
            if r.status_code >= 500:
                last = requests.HTTPError(f"{r.status_code}", response=r)
                time.sleep(1.5 + i * 1.5)
                continue
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 + i * 1.5)
    if last:
        raise last
    raise RuntimeError("http_get: échec inattendu")


# --------------------------------------------------------------------------- #
# Texte
# --------------------------------------------------------------------------- #
def normalize_text(value: str) -> str:
    """Lowercase + retire les accents (comparaison tolérante aux diacritiques)."""
    text = (value or "").lower()
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def ean_from_url(url: str, pattern: str = r"/(\d{8,14})_[A-Z]{2,4}\.prd") -> str:
    """Extrait un code produit (EAN/réf) d'une URL de fiche produit.

    Par défaut : pattern Castorama (`.prd`). Passer un pattern custom pour
    d'autres enseignes. Lève ValueError si non trouvé.
    """
    m = re.search(pattern, url)
    if not m:
        raise ValueError(f"Impossible d'extraire l'identifiant produit de l'URL : {url}")
    return m.group(1)


# --------------------------------------------------------------------------- #
# Run / accumulation des magasins
# --------------------------------------------------------------------------- #
def aggregate(found: dict, all_stores: dict) -> int:
    """Fusionne les magasins d'un fragment/lot dans l'accumulateur global.

    Renvoie le nb de nouveaux magasins. Préserve l'info la plus « positive » :
    un restock écrase un non-restock. L'id du magasin = clé du dict `found`.
    """
    new = 0
    for sid, st in found.items():
        if sid not in all_stores:
            all_stores[sid] = st
            new += 1
        elif st.get("restock") and not all_stores[sid].get("restock"):
            all_stores[sid] = st
    return new


# --------------------------------------------------------------------------- #
# Géographie (distance approchée — set-cover / ordonnement cœur-d'abord)
# --------------------------------------------------------------------------- #
def seed_distance(a, b) -> float:
    """Distance approx (équirectangulaire, en 'degrés') entre 2 points.

    Pas besoin de km exacts : sert seulement à comparer/ordonner des seeds.
    Chaque point : (label, lat, lon).
    """
    (_, la, lo), (_, lb, lob) = a, b
    mlat = (la + lb) * math.pi / 360.0
    dx = (lo - lob) * math.cos(mlat)
    dy = la - lb
    return (dx * dx + dy * dy) ** 0.5


def order_core_first(seeds, center):
    """Ordonne du plus proche au plus loin de `center` (cœur d'abord).

    Si le scan s'arrête/bloque en cours, on garde d'abord les magasins du cœur.
    """
    c = ("center", center[0], center[1])
    return sorted(seeds, key=lambda s: seed_distance(s, c))
