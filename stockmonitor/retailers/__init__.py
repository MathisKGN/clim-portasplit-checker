"""Registre des adapteurs d'enseignes.

Pour ajouter une enseigne :
  1. Créer <name>.py ici avec une classe héritant de ScannerBase.
  2. L'inscrire dans REGISTRY ci-dessous.
"""
from __future__ import annotations

from ..base import ScannerBase
from .lm import LmScanner
from .casto import CastoScanner

REGISTRY: dict[str, type[ScannerBase]] = {
    "lm":      LmScanner,
    "casto":   CastoScanner,
    "leroymerlin": LmScanner,
    "castorama":  CastoScanner,
}

__all__ = ["REGISTRY", "ScannerBase"]
