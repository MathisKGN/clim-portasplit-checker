"""
Seeds pour le scan 200 km autour de Paris.

Généré par set-cover greedy (tools/gen_seeds_france.py) sur les 55 magasins
uniques de data/lm_stores.json (dédup par coordonnée).

L'endpoint stock LM renvoie les ~11 magasins les plus proches d'un point ; on
place le minimum de seeds pour que chaque magasin tombe dans le top-11 d'au moins
un seed — 7 seeds au lieu d'un par magasin. Moins de requêtes = scan
plus rapide et moins de 403 DataDome.

Régénération :
  python3 tools/gen_seeds_france.py --margin 11 --input data/lm_stores.json --out stockmonitor/seeds_france.py --var SEEDS_FRANCE_200KM --label "200 km autour de Paris" --center 48.8566,2.3522 --zone paris200 --max-dist-km 200

Usage : python -m stockmonitor lm --zone paris200
"""

# 7 seeds set-cover couvrant les 55 magasins de la zone.
SEEDS_FRANCE_200KM = [
    ("Paris", 48.8616, 2.3522),
    ("Tourville-la-Rivière", 49.3303, 1.0896),
    ("Reims", 49.2887, 4.0211),
    ("Saint-Doulchard", 47.1106, 2.3761),
    ("Arras", 50.3010, 2.7278),
    ("Saint-Ouen", 48.9150, 2.3232),
    ("Montivilliers", 49.5400, 0.2060),
]
