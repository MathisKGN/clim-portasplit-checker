"""Seeds pour un scan Leroy Merlin France ENTIÈRE.

Généré par set-cover greedy sur les 120 magasins géocodés
(data/geocoded_stores.json). L'endpoint stock renvoie les ~11 magasins les plus
proches d'un point ; on place le minimum de seeds pour que chaque magasin tombe
dans le top-11 d'au moins un seed. La couverture est calculée avec une marge de
sécurité (top-8) pour rester robuste si le catalogue réel a plus de magasins que
notre liste (nouveaux magasins non éjectés du top-11).

Régénération : voir tools/gen_seeds_france.py (set-cover greedy, N=8).

Usage : python -m stockmonitor lm --zone france
"""

# 21 seeds couvrant les 120 magasins LM France (marge top-8).
SEEDS_FRANCE_FULL = [
    ("La Sentinelle (59)",       50.3497, 3.4761),
    ("Grande-Synthe (59)",       51.0135, 2.3030),
    ("Le Havre (76)",            49.4939, 0.1080),
    ("Évreux (27)",              49.0269, 1.1510),
    ("Beauvais (60)",            49.4301, 2.0823),
    ("Reims (51)",               49.2578, 4.0319),
    ("Champigneulles (54)",      48.7342, 6.1651),
    ("Sarcelles (95)",           48.9961, 2.3796),
    ("Gennevilliers (92)",       48.9254, 2.2940),
    ("Melun (77)",               48.5399, 2.6608),
    ("Auxerre (89)",             47.7961, 3.5706),
    ("Betton (35)",              48.1817, -1.6415),
    ("Tours (37)",               47.3894, 0.6939),
    ("Épagny (21)",              47.4475, 5.0601),
    ("Andelnans (90)",           47.6030, 6.8683),
    ("Mâcon (71)",               46.3037, 4.8322),
    ("Saint-Georges-des-Coteaux (17)", 45.7634, -0.7111),
    ("Le Pontet / Savoie (73)",  45.4935, 6.2283),
    ("Aubagne (13)",             43.2924, 5.5703),
    ("Balma / Toulouse (31)",    43.6097, 1.4980),
    ("Albi (81)",                43.9278, 2.1479),
]

# Centre géographique approximatif de la France (pour l'ordre core-first).
CENTER_FR = (46.6, 2.4)
