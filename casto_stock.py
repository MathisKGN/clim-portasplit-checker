#!/usr/bin/env python3
"""Shim de compatibilité : expose l'ancien CLI `python casto_stock.py …`.

Le code vit désormais dans stockmonitor/ (cf. stockmonitor/retailers/casto.py).
Ce fichier ne fait que déléguer à la CLI unifiée pour ne pas casser les cron /
scripts existants. Préférer `python -m stockmonitor casto` ou `python monitor.py casto`.
"""
from __future__ import annotations
import sys

sys.argv = [sys.argv[0]] + ["casto"] + sys.argv[1:]

from stockmonitor.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
