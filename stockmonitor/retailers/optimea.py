"""Optimea — scan fiche produit en ligne.

Vérification du 2026-07-08 : les fiches produits exposent un marqueur
WooCommerce `product:availability` (`in stock` / `out of stock`) dans le HTML.
"""
from __future__ import annotations

from .web_product import WebProductScanner


class OptimeaScanner(WebProductScanner):
    RETAILER_NAME = "Optimea"
    FILE_PREFIX = "optimea"
    ENV_PREFIX = "OPTIMEA"
    CONFIG_KEY = "optimea"
    DEFAULT_PRODUCT_REF = "MMCS-12HRN8-QRD0"
    DEFAULT_PRODUCT_URL = "https://www.optimea.fr/product/climatiseur-split-mobile-midea/"
