"""Darty — scan fiche produit en ligne.

Vérification anti-bot du 2026-07-04 : une requête curl directe renvoie 403 avec
redirection `queue.fnacdarty.com` et header `x-queueit-connector: akamai`, sans
marqueur DataDome. On utilise donc un scan navigateur de fiche produit.
"""
from __future__ import annotations

from .web_product import WebProductScanner


class DartyScanner(WebProductScanner):
    RETAILER_NAME = "Darty"
    FILE_PREFIX = "darty"
    ENV_PREFIX = "DARTY"
    CONFIG_KEY = "darty"
    DEFAULT_PRODUCT_REF = "7970579"
    DEFAULT_PRODUCT_URL = (
        "https://www.darty.com/nav/achat/gros_electromenager/"
        "chauffage_climatisation/climatiseur/midea_mmcs-12hrn8-qrd0.html"
    )
