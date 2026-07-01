"""
Seeds pour le scan France entière.

Généré par set-cover greedy (tools/gen_seeds_france.py) sur les 146 magasins
uniques de data/lm_stores.json (dédup par coordonnée).

L'endpoint stock LM renvoie les ~11 magasins les plus proches d'un point ; on
place le minimum de seeds pour que chaque magasin tombe dans le top-11 d'au moins
un seed — 26 seeds au lieu d'un par magasin. Moins de requêtes = scan
plus rapide et moins de 403 DataDome.

Régénération :
  python3 tools/gen_seeds_france.py --margin 8 --input data/lm_stores.json --out stockmonitor/seeds_france_full.py --var SEEDS_FRANCE_FULL --label "France entière" --center 46.6,2.4 --zone france

Usage : python -m stockmonitor lm --zone france
"""

# 26 seeds set-cover couvrant les 146 magasins de la zone.
SEEDS_FRANCE_FULL = [
    ("Le Poinçonnet", 46.7944, 1.7384),
    ("Clermont-Ferrand", 45.8041, 3.1369),
    ("Cesson", 48.5800, 2.6072),
    ("Paris", 48.8470, 2.2945),
    ("Saint-Georges-des-Coteaux", 45.7557, -0.6773),
    ("Saint-Berthevin", 48.0617, -0.8145),
    ("Albi", 43.9379, 2.1774),
    ("Jaux", 49.4041, 2.7840),
    ("Andelnans", 47.6066, 6.8607),
    ("Charleville Mézières", 49.7413, 4.7016),
    ("Martigues", 43.4255, 5.0513),
    ("Saint-Martin-Boulogne", 50.7327, 1.6746),
    ("Buchelay", 48.9881, 1.6679),
    ("Queven", 47.7785, -3.4224),
    ("Furiani", 42.6575, 9.4371),
    ("Mondeville", 49.1567, -0.2934),
    ("Quetigny", 47.3080, 5.0989),
    ("Hautmont", 50.2548, 3.9337),
    ("Saint-Egreve", 45.2419, 5.6665),
    ("Villeneuve-lès-Béziers", 43.3378, 3.2860),
    ("Pau", 43.3068, -0.3296),
    ("Niort", 46.3177, -0.4165),
    ("Rosny-sous-bois", 48.8794, 2.4738),
    ("Metz", 49.1055, 6.2324),
    ("Limoges", 45.8930, 1.2843),
    ("Blois", 47.6152, 1.3207),
]
