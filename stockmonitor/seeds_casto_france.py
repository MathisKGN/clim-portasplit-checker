"""
Seeds Castorama France — couverture complète des magasins français
en un minimum d'appels à l'API Kingfisher.

Calculés par map_casto_stores.py (greedy set-cover, page[size]=50)
à partir des coordonnées réelles de 90 magasins.

Chaque seed est la position d'un magasin réel : l'API renvoie les
~50 magasins les plus proches. Greedy set-cover ⇒ 3
seeds suffisent à couvrir TOUS les magasins Casto FR.
"""

# (label, latitude, longitude)
SEEDS_CASTO_FRANCE = [
    ("La Seyne sur Mer", 43.089220, 5.870863),
    ("Barentin", 49.544034, 0.945745),
    ("Antibes", 43.588397, 7.118832),
]
