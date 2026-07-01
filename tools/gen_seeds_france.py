#!/usr/bin/env python3
"""
Générateur set-cover greedy des seeds LM (remplace le placement 1-seed-par-ville).

Principe : l'endpoint stock LM renvoie les ~11 magasins les plus PROCHES d'un
point (lat/lon). Couvrir une zone ne demande donc pas un seed par magasin, mais
un jeu minimal de points tel que chaque magasin tombe dans le top-N d'au moins
un seed. On résout ça par un greedy set-cover (à chaque étape, on prend le
candidat qui couvre le plus de magasins encore non couverts).

Le paramètre de MARGE `N` = combien de magasins on suppose « vus » par seed :
  - N=11 : colle au comportement réel de l'endpoint. Minimal, mais fragile si LM
           ouvre de nouveaux magasins (un magasin ciblé peut sortir du top-11).
  - N=8  : marge de sécurité.

Candidats = positions des magasins eux-mêmes (place un seed sur chaque magasin,
puis élague). Chaque seed retenu est nommé d'après le magasin sur lequel il est.

Entrée : une liste JSON de magasins {name, city, cp, lat, lon} (cf.
data/stores_200km.json, produit par tools/map_stores.py).

Usage :
  python3 tools/gen_seeds_france.py            # paris200, marge N=11 -> seeds_france.py
  python3 tools/gen_seeds_france.py --margin 8 # marge plus prudente
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # racine du projet
PARIS = (48.8566, 2.3522)


def haversine_km(a, b, c, d) -> float:
    r = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dphi = math.radians(c - a)
    dl = math.radians(d - b)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def load_stores(path: Path, center) -> list[dict]:
    """Magasins uniques (dédup par coord arrondie), triés cœur-d'abord."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    uniq: dict = {}
    for s in raw:
        key = (round(s["lat"], 3), round(s["lon"], 3))
        uniq.setdefault(key, s)
    pts = list(uniq.values())
    # core-first : traite le centre en premier pour un ordre de sortie lisible
    # (n'influe pas sur la couverture, seulement sur l'ordre des seeds).
    pts.sort(key=lambda s: haversine_km(center[0], center[1], s["lat"], s["lon"]))
    return pts


def coverage(seed, pts, n) -> set[int]:
    """Indices des N magasins les plus proches de `seed` (= ce que voit le seed)."""
    order = sorted(range(len(pts)),
                   key=lambda i: haversine_km(seed[0], seed[1], pts[i]["lat"], pts[i]["lon"]))
    return set(order[:n])


def set_cover(pts, n) -> list[int]:
    """Greedy : renvoie les indices des magasins choisis comme seeds."""
    # La couverture d'un candidat ne dépend que de sa position, pas de l'état
    # courant : on la calcule une fois, la boucle ne fait plus que des diffs.
    covs = [coverage((p["lat"], p["lon"]), pts, n) for p in pts]
    covered: set = set()
    chosen: list = []
    target = set(range(len(pts)))
    while covered != target:
        best = max((i for i in range(len(pts)) if i not in chosen),
                   key=lambda i: len(covs[i] - covered), default=None)
        if best is None or not (covs[best] - covered):
            break  # plus aucun candidat n'apporte de couverture
        chosen.append(best)
        covered |= covs[best]
    return chosen


def seed_name(store: dict) -> str:
    # Nommé par commune : les CP de la page produit LM sont peu fiables
    # (homonymes/erreurs), on ne s'en sert pas pour l'étiquette.
    return store["city"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--margin", type=int, default=11,
                    help="N magasins supposés vus par seed (11=réel, 8=marge)")
    ap.add_argument("--input", default="data/stores_200km.json",
                    help="liste JSON de magasins {city,cp,lat,lon}")
    ap.add_argument("--out", default="stockmonitor/seeds_france.py",
                    help="fichier seeds à générer")
    ap.add_argument("--var", default="SEEDS_FRANCE_200KM",
                    help="nom de la variable exportée")
    ap.add_argument("--label", default="200 km autour de Paris",
                    help="libellé de la zone (docstring du fichier généré)")
    ap.add_argument("--center", default="48.8566,2.3522",
                    help="'lat,lon' du centre (ordre core-first)")
    ap.add_argument("--zone", default="paris200",
                    help="slug de zone pour la ligne Usage du fichier généré")
    args = ap.parse_args()

    center = tuple(float(x) for x in args.center.split(","))
    pts = load_stores(HERE / args.input, center)

    chosen = set_cover(pts, args.margin)
    seeds = [(seed_name(pts[i]), round(pts[i]["lat"], 4), round(pts[i]["lon"], 4))
             for i in chosen]

    # Vérif couverture stricte au top-11 réel (indépendamment de la marge).
    covered: set = set()
    for _, lat, lon in seeds:
        covered |= coverage((lat, lon), pts, 11)
    assert covered == set(range(len(pts))), \
        f"couverture incomplète: {len(covered)}/{len(pts)}"

    input_name = Path(args.input).name
    regen = (f"python3 tools/gen_seeds_france.py --margin {args.margin} "
             f"--input {args.input} --out {args.out} --var {args.var} "
             f'--label "{args.label}" --center {args.center} --zone {args.zone}')
    body = f'''"""
Seeds pour le scan {args.label}.

Généré par set-cover greedy (tools/gen_seeds_france.py) sur les {len(pts)} magasins
uniques de data/{input_name} (dédup par coordonnée).

L'endpoint stock LM renvoie les ~11 magasins les plus proches d'un point ; on
place le minimum de seeds pour que chaque magasin tombe dans le top-11 d'au moins
un seed — {len(seeds)} seeds au lieu d'un par magasin. Moins de requêtes = scan
plus rapide et moins de 403 DataDome.

Régénération :
  {regen}

Usage : python -m stockmonitor lm --zone {args.zone}
"""

# {len(seeds)} seeds set-cover couvrant les {len(pts)} magasins de la zone.
{args.var} = [
'''
    for name, lat, lon in seeds:
        body += f'    ("{name}", {lat:.4f}, {lon:.4f}),\n'
    body += "]\n"

    (HERE / args.out).write_text(body, encoding="utf-8")
    print(f"[+] {args.out} : {len(seeds)} seeds (marge top-{args.margin}) "
          f"couvrent {len(pts)} magasins")
    for name, lat, lon in seeds:
        print(f"    {name:<28} {lat:.4f}, {lon:.4f}")


if __name__ == "__main__":
    main()
