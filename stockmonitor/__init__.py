"""stockmonitor — moniteur de stock multi-enseignes.

Architecture
------------
  stockmonitor.common   : utils partagés (ts, json, http, dédup, etc.).
  stockmonitor.base     : ScannerBase — report / alerts / persist / boucle.
  stockmonitor.retailers : un adapteur par enseigne (lm, casto, darty, amazon).
  stockmonitor.cli       : point d'entrée CLI unifié (`python -m stockmonitor`).
  monitor.py            : wrapper racine (`python monitor.py <retailer>`).

Ajouter une enseigne
--------------------
  1. Créer stockmonitor/retailers/<enseigne>.py avec une classe héritant de
     ScannerBase (implémenter `scan()`, `open_context()`, `build_store_url()`
     et les constantes RETAILER_NAME / FILE_PREFIX / etc.).
  2. L'inscrire dans stockmonitor/retailers/__init__.py (REGISTRY).
  3. (optionnel) ajouter un wrapper racine <enseigne>_stock.py pour le cron
     existant.

Le reverse-engineering de chaque enseigne reste dans son adapteur ; la base
est agnostique du transport (Camoufox, requests, …).
"""
