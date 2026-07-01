#!/usr/bin/env python3
"""Shim de compatibilité : expose l'ancien CLI `python lm_stock.py …`.

Le code vit désormais dans stockmonitor/ (cf. stockmonitor/retailers/lm.py).
Ce fichier ne fait que déléguer à la CLI unifiée pour ne pas casser les cron /
scripts existants. Préférer `python -m stockmonitor lm` ou `python monitor.py lm`.
"""
from __future__ import annotations
import sys

# Préfixe : on injecte "lm" comme premier positional, puis on transmet le reste
# tel quel pour conserver toutes les options (--loop, --zone, …).
sys.argv = [sys.argv[0]] + ["lm"] + sys.argv[1:]

from stockmonitor.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
