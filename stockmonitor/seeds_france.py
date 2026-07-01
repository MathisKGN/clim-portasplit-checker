"""
Seeds pour le scan 200 km autour de Paris.

Généré par set-cover greedy (tools/gen_seeds_france.py) sur les 50 magasins
uniques de data/stores_200km.json (dédup par coordonnée).

L'endpoint stock LM renvoie les ~11 magasins les plus proches d'un point ; on
place le minimum de seeds pour que chaque magasin tombe dans le top-11 d'au moins
un seed — 8 seeds au lieu d'un par magasin. Moins de requêtes = scan
plus rapide et moins de 403 DataDome.

Régénération :
  python3 tools/gen_seeds_france.py --margin 11 --input data/stores_200km.json --out stockmonitor/seeds_france.py --var SEEDS_FRANCE_200KM --label "200 km autour de Paris" --center 48.8566,2.3522 --zone paris200

Usage : python -m stockmonitor lm --zone paris200
"""

# 8 seeds set-cover couvrant les 50 magasins de la zone.
SEEDS_FRANCE_200KM = [
    ("Paris", 48.8535, 2.3484),
    ("Longueau", 49.8703, 2.3574),
    ("Reims", 49.2578, 4.0319),
    ("Mulsanne", 47.9069, 0.2461),
    ("Tourville-La-Rivière", 49.3301, 1.1058),
    ("Ingré", 47.9193, 1.8225),
    ("St Denis-La-Plaine", 48.9106, 2.3586),
    ("Arras", 50.2910, 2.7772),
]
