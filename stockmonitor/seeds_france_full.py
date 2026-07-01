"""
Seeds pour le scan France entière.

Généré par set-cover greedy (tools/gen_seeds_france.py) sur les 137 magasins
uniques de data/stores_all.json (dédup par coordonnée).

L'endpoint stock LM renvoie les ~11 magasins les plus proches d'un point ; on
place le minimum de seeds pour que chaque magasin tombe dans le top-11 d'au moins
un seed — 27 seeds au lieu d'un par magasin. Moins de requêtes = scan
plus rapide et moins de 403 DataDome.

Régénération :
  python3 tools/gen_seeds_france.py --margin 8 --input data/stores_all.json --out stockmonitor/seeds_france_full.py --var SEEDS_FRANCE_FULL --label "France entière" --center 46.6,2.4 --zone france

Usage : python -m stockmonitor lm --zone france
"""

# 27 seeds set-cover couvrant les 137 magasins de la zone.
SEEDS_FRANCE_FULL = [
    ("Le Poinçonnet", 46.7642, 1.7178),
    ("Mâcon", 46.3037, 4.8322),
    ("Cesson", 48.5624, 2.6021),
    ("Rueil Malmaison", 48.8778, 2.1803),
    ("Cholet", 47.0617, -0.8801),
    ("Albi", 43.9278, 2.1479),
    ("Bouliac", 44.8140, -0.5037),
    ("Isneauville", 49.4988, 1.1416),
    ("Andelnans", 47.6030, 6.8683),
    ("Charleville Mézières", 49.7736, 4.7207),
    ("Pleurtuit", 48.5815, -2.0591),
    ("Cabriès", 43.4412, 5.3799),
    ("Grande Synthe", 51.0135, 2.3030),
    ("Jaux", 49.3881, 2.7765),
    ("Furiani", 42.6585, 9.4151),
    ("Valence", 44.9332, 4.8921),
    ("Metz", 49.1090, 6.1773),
    ("Queven", 47.7888, -3.4161),
    ("Clermont-Ferrand", 45.7775, 3.0819),
    ("Blois", 47.5877, 1.3338),
    ("Quetigny", 47.3126, 5.1163),
    ("Bonneuil-Sur-Marne", 48.7737, 2.4869),
    ("Colomiers", 43.6112, 1.3367),
    ("Beauvais", 49.4301, 2.0823),
    ("Biganos", 44.6420, -0.9766),
    ("Mondeville", 49.1771, -0.3201),
    ("St-Jean-De-Védas", 43.5752, 3.8264),
]
