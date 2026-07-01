"""
Seeds pour le scan 200 km autour de Paris.

Généré par set-cover greedy (tools/gen_seeds_france.py --margin 11)
sur les 52 magasins uniques de data/stores_200km.json (dédup par coordonnée).

L'endpoint stock LM renvoie les ~11 magasins les plus proches d'un point ; on
place le minimum de seeds pour que chaque magasin tombe dans le top-11 d'au moins
un seed — 8 seeds au lieu d'un par magasin. Moins de requêtes = scan
plus rapide et moins de 403 DataDome.

Régénération : python3 tools/gen_seeds_france.py --margin 11

Usage : python -m stockmonitor lm --zone paris200
"""

# 8 seeds set-cover couvrant les 52 magasins de la zone.
SEEDS_FRANCE_200KM = [
    ("Paris (75)", 48.8535, 2.3484),
    ("Amiens (80)", 49.8942, 2.2957),
    ("Troyes (10)", 48.2972, 4.0746),
    ("Le Mans (72)", 47.9952, 0.1921),
    ("Laon (02)", 49.5647, 3.6207),
    ("Montsoult (95)", 49.0704, 2.3120),
    ("Évreux (27)", 49.0269, 1.1510),
    ("Orléans (45)", 47.9027, 1.9086),
]
