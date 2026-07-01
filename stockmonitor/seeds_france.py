"""
Seeds pour le scan 200 km autour de Paris.

Combine les 24 seeds IDF existants (déjà testés, couvrent les ~36 magasins IDF)
avec ~31 seeds "anneau" placés sur les villes réelles où se trouve un magasin LM
dans la couronne 50-200 km.

Chaque seed est positionné SUR la ville réelle (pas sur une grille abstraite),
ce qui garantit que le magasin de cette ville tombe dans le top-11 de l'endpoint.

Usage : python -m stockmonitor lm --zone paris200
"""
from .seeds_idf import SEEDS_IDF, CENTER

# Seeds anneau 50-200 km : villes moyennes avec magasin LM.
# Chaque seed "voit" 11 magasins les plus proches depuis cette ville.
RING_SEEDS = [
    ("Beauvais (60)", 49.4300, 2.0800),
    ("Compiègne (60)", 49.4200, 2.8300),
    ("Évreux (27)", 49.0200, 1.1500),
    ("Dreux (28)", 48.7400, 1.3700),
    ("Chartres (28)", 48.4400, 1.4900),
    ("Étampes (91)", 48.4300, 2.1600),
    ("Château-Thierry (02)", 49.0500, 3.4000),
    ("Rouen/Le Havre (76)", 49.4400, 1.0900),
    ("Le Havre (76)", 49.4900, 0.1100),
    ("Amiens (80)", 49.8900, 2.2900),
    ("Soissons (02)", 49.3800, 3.3200),
    ("Laon (02)", 49.5600, 3.6200),
    ("Reims (51)", 49.2600, 4.0300),
    ("Troyes (10)", 48.3000, 4.0800),
    ("Orléans (45)", 47.9000, 1.9000),
    ("Montargis (45)", 48.0000, 2.7300),
    ("Sens (89)", 48.2000, 3.2800),
    ("Auxerre (89)", 47.8000, 3.5700),
    ("Saint-Quentin (02)", 49.8500, 3.2900),
    ("Le Mans (72)", 48.0000, 0.2000),
    ("Blois (41)", 47.5800, 1.3300),
    ("Bourges (18)", 47.0800, 2.4000),
    ("Cambrai (59)", 50.1700, 3.2400),
    ("Arras (62)", 50.2900, 2.7800),
    ("Douai/Lens (59)", 50.3700, 3.0800),
    ("Valenciennes (59)", 50.3500, 3.5200),
    ("Maubeuge/Hautmont (59)", 50.2800, 4.0000),
    ("Béthune/Verquin (62)", 50.5300, 2.6400),
    ("Lille (59)", 50.6300, 3.0600),
    ("Caen (14)", 49.1800, -0.3600),
]

# Combinaison : IDF (cœur dense) + anneau (couronne 50-200km).
SEEDS_FRANCE_200KM = list(SEEDS_IDF) + list(RING_SEEDS)
