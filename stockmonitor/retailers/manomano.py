"""ManoMano — scan fiche produit en ligne.

Vérification anti-bot du 2026-07-04 : la home/recherche répond avec Cloudflare
(`server: cloudflare`, cookie `__cf_bm`, challenge `challenges.cloudflare.com`),
pas avec les headers/cookies DataDome observés chez Leroy Merlin.
"""
from __future__ import annotations

from .web_product import WebProductScanner


class ManoManoScanner(WebProductScanner):
    RETAILER_NAME = "ManoMano"
    FILE_PREFIX = "manomano"
    ENV_PREFIX = "MANOMANO"
    CONFIG_KEY = "manomano"
    DEFAULT_PRODUCT_REF = "83810402"
    DEFAULT_PRODUCT_URL = (
        "https://www.manomano.fr/p/"
        "midea-climatiseur-split-mobile-reversible-froid-chaud-3500w12000btu-wifi-"
        "deshumidificateur-ventilateur-jusqua-40m2-kit-fenetre-inclus-83810402"
    )
