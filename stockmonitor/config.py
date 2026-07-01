"""Chargement de la configuration (config.toml à la racine du projet).

Tous les defaults tunables vivent dans config.toml ; la CLI ne garde que
l'essentiel (retailer, produit, loop, notify-cmd, -v). Modifier config.toml
plutôt qu'empiler des --flags.

Priorité : CLI explicite > config.toml > defaults codés dans chaque scanner
(via ScannerBase.get_defaults).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

# Recherche du config.toml : CWD, puis dossier du paquet, puis racine repo.
_SEARCH_PATHS = (
    Path.cwd() / "config.toml",
    Path(__file__).resolve().parent.parent / "config.toml",
)


def find_config_path() -> Path | None:
    for p in _SEARCH_PATHS:
        if p.exists():
            return p
    return None


def load_config(path: Path | str | None = None) -> dict:
    """Charge config.toml. Renvoie {} si absent/illisible (silencieux)."""
    p = Path(path) if path else find_config_path()
    if not p:
        return {}
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def merge_config_into_args(args, cfg: dict, retailer_key: str) -> None:
    """Injecte les valeurs de config dans `args` pour les attributs non fixés
    par la CLI (valeur None).

    Priorité : common < retailer < defaults scanner < CLI (déjà posée).
    """
    common = cfg.get("common", {}) or {}
    retailer = cfg.get(retailer_key, {}) or {}
    merged = {**common, **retailer}
    for key, val in merged.items():
        if val is None:
            continue
        cur = getattr(args, key, None)
        if cur is None:
            setattr(args, key, val)
