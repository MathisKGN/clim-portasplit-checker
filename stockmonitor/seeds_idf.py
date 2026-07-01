"""
Points de recherche (seeds) pour le scan de stock Leroy Merlin.

L'endpoint LM renvoie les ~10-11 magasins les plus proches d'un couple
(latitude, longitude), jusqu'à ~30 km. Pour couvrir une zone, on sème assez de
points : chaque magasin tombe dans le top-N d'au moins un seed, puis on
déduplique par slug magasin.

Format : (libellé, latitude, longitude)

Deux jeux de points :
  - SEEDS_IDF  : Île-de-France (75/77/78/91/92/93/94/95) + proche couronne
                 immédiate (27/28/60). C'est le scan PAR DÉFAUT.
  - SEEDS_WIDE : couronne élargie (Champagne/Bourgogne/Picardie nord…),
                 AJOUTÉE uniquement avec --wide. Ces points lointains ramènent
                 des magasins à 100-270 km (Reims, Troyes, Orléans, Dijon,
                 Bourges, Maubeuge…) et sont aussi plus sensibles aux blocages.

CENTER sert à ordonner le scan "cœur d'abord" (Paris -> périphérie) : un arrêt
ou un blocage en cours de route garde ainsi les magasins du cœur IDF.
"""

# Centre de référence pour l'ordonnancement cœur-d'abord (Paris Notre-Dame).
CENTER = (48.8566, 2.3522)

# --- Core IDF : 5 seeds stratégiques couvrant les ~25 magasins IDF ------------ #
# 1 seed = ~10-11 magasins les + proches. 5 seeds bien placés (un par
# "pôle" géographique IDF) couvrent tout l'IDF sans trou.
# Cadence 15-30 s/seed, soit ~2 min pour un scan complet.
CORE_IDF = [
    ("Paris Centre",            48.8566, 2.3522),   # Paris + proche couronne
    ("Cergy (95)",              49.0400, 2.0600),   # Val-d'Oise
    ("Versailles (78)",         48.8040, 2.1300),   # Yvelines + 92S
    ("Évry (91)",               48.6300, 2.4400),   # Essonne + 77 Sud
    ("Marne-la-Vallée (77)",    48.8400, 2.6600),   # Seine-et-Marne + 94E
]

# --- Scan par défaut : IDF + proche couronne immédiate ---------------------- #
SEEDS_IDF = [
    # --- Paris intra-muros (75) ---
    ("Paris Centre",            48.8566, 2.3522),
    ("Paris Est / Daumesnil",   48.8400, 2.4100),
    ("Paris Ouest / Boulogne",  48.8330, 2.2500),
    # --- Hauts-de-Seine (92) ---
    ("Nanterre / La Défense",   48.8900, 2.2100),
    ("Antony / Massy (92S/91N)",48.7300, 2.2900),
    # --- Seine-Saint-Denis (93) ---
    ("Bobigny / Aulnay",        48.9300, 2.4900),
    ("Rosny / Montreuil",       48.8700, 2.4900),
    # --- Val-de-Marne (94) ---
    ("Créteil",                 48.7900, 2.4500),
    # --- Val-d'Oise (95) ---
    ("Cergy",                   49.0400, 2.0600),
    ("Sarcelles / Gonesse",     48.9900, 2.4200),
    # --- Yvelines (78) ---
    ("Versailles",              48.8040, 2.1300),
    ("Mantes-la-Jolie",         48.9900, 1.7100),
    ("Rambouillet",             48.6400, 1.8300),
    # --- Essonne (91) ---
    ("Évry",                    48.6300, 2.4400),
    ("Étampes",                 48.4300, 2.1600),
    # --- Seine-et-Marne (77) ---
    ("Marne-la-Vallée/Collégien",48.8400, 2.6600),
    ("Meaux",                   48.9600, 2.8800),
    ("Melun",                   48.5400, 2.6600),
    ("Brie-Comte-Robert",       48.6900, 2.6100),
    # --- Proche couronne immédiate (départements limitrophes 60/27/28) ---
    ("Beauvais (60)",           49.4300, 2.0800),
    ("Compiègne (60)",          49.4200, 2.8300),
    ("Évreux (27)",             49.0200, 1.1500),
    ("Dreux (28)",              48.7400, 1.3700),
    ("Chartres (28)",           48.4400, 1.4900),
]

# --- Couronne élargie : AJOUTÉE seulement avec --wide ----------------------- #
SEEDS_WIDE = [
    ("Soissons (02)",           49.3800, 3.3200),
    ("Château-Thierry (02)",    49.0500, 3.4000),
    ("Reims (51)",              49.2600, 4.0300),
    ("Orléans (45)",            47.9000, 1.9000),
    ("Montargis (45)",          48.0000, 2.7300),
    ("Sens (89)",               48.2000, 3.2800),
    ("Auxerre (89)",            47.8000, 3.5700),
    ("Troyes (10)",             48.3000, 4.0800),
]
