#!/usr/bin/env python3
"""
Cartographie des magasins Castorama France + calcul des seeds optimaux pour
couvrir TOUS les magasins en un minimum d'appels à l'API Kingfisher.

Pipeline (géocodage Nominatim + set-cover greedy, adapté Castorama) :
  1. Parse la liste des magasins Casto FR (noms + villes + CP), fournie
     manuellement (liste extraite du locator castorama.fr).
  2. Géocode chaque ville via Nominatim (OpenStreetMap), 1 req/s (usage policy),
     avec cache persistant data/geocoded_casto.json.
  3. Algorithme greedy set-cover :
     - L'API Kingfisher renvoie les `page[size]` (défaut 50) magasins les plus
       proches d'un point nearLatLong, SANS plafond de distance.
     - Pour chaque magasin candidat M, son "voisinage visible" = les N magasins
       les plus proches de M (M inclus).
     - On sélectionne itérativement le magasin qui couvre le plus de magasins
       non encore couverts, jusqu'à couverture complète.
  4. Génère seeds_casto_france.py avec les seeds optimaux nommés (ville du
     magasin retenu).

Usage : python3 map_casto_stores.py            # page_size=50 (défaut Casto)
        python3 map_casto_stores.py --page-size 30
"""
from __future__ import annotations
import argparse
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # racine du projet

# --- Liste des magasins Castorama France (extraite du locator castorama.fr) -- #
# Format brût : blocs de 4 lignes (magasin / statut / prix / lien) mêlés ; on
# ne garde que les lignes "Castorama <nom>\t<VILLE CP>". On saute "en ligne".
RAW_STORES = """\
Castorama La Seyne sur Mer	LA SEYNE SUR MER 83500
Castorama Lattes	LATTES 34970
Castorama Plan de Campagne	LES PENNES MIRABEAU 13170
Castorama Cap Malo	MELESSE 35520
Castorama en ligne	—
Castorama Agen	AGEN 47000
Castorama Aix en Provence	AIX EN PROVENCE CEDEX 4 13547
Castorama Anglet	ANGLET 64600
Castorama Angoulême	ANGOULÊME 16000
Castorama Antibes	ANTIBES 06600
Castorama Clermont-Ferrand	AUBIERE 63170
Castorama Avignon	AVIGNON 84000
Castorama La Rochelle	AYTRE 17440
Castorama Barentin	BARENTIN 76360
Castorama Besançon	BESANCON 25000
Castorama Béziers	BÉZIERS 34500
Castorama Toulouse Blagnac	BLAGNAC 31700
Castorama Bondues	BONDUES 59910
Castorama Bourgoin-Jallieu	BOURGOIN JALLIEU 38300
Castorama Niort	NIORT 79000
Castorama Brest	BREST 29200
Castorama Bron	BRON 69675
Castorama Chalon-sur-Saône	CHALON SUR SAONE 71100
Castorama Chambéry	CHAMBERY 73000
Castorama Chambourcy	CHAMBOURCY 78240
Castorama Chambray-Lès-Tours	CHAMBRAY LES TOURS 37170
Castorama Ormesson	CHENNEVIERES SUR MARNE 94430
Castorama Claye-Souilly	CLAYE SOUILLY 77410
Castorama Coignières	COIGNIERES 78310
Castorama Colmar	COLMAR 68027
Castorama Cormeilles-en-Parisis	CORMEILLES-EN-PARISIS 95240
Castorama Créteil	CRÉTEIL 94034
Castorama Le Cannet	CS 20014 06110
Castorama Dardilly	DARDILLY 69570
Castorama Dunkerque	DUNKERQUE 59140
Castorama Limoges	FEYTIAT 87220
Castorama Caen Fleury-sur-Orne	FLEURY SUR ORNE 14123
Castorama Fresnes	FRESNES 94260
Castorama Givors	GIVORS 69700
Castorama Englos	HAUBOURDIN 59481
Castorama Hénin-Beaumont	HENIN BEAUMONT 62110
Castorama Caen Hérouville	HEROUVILLE ST CLAIR 14200
Castorama Metz	JOUY AUX ARCHES 57130
Castorama Kingersheim	KINGERSHEIM 68264
Castorama Toulouse L'Union	L'UNION 31240
Castorama Toulon La Garde	LA GARDE 83130
Castorama Le Mans	LE MANS 72021
Castorama Les Ulis	LES ULIS 91940
Castorama Les-Clayes-Sous-Bois	LES-CLAYES-SOUS-BOIS 78340
Castorama Pau - Lescar	LESCAR 64232
Castorama Bordeaux Lormont	LORMONT 33310
Castorama Roanne	MABLY 42300
Castorama Mandelieu	MANDELIEU 06210
Castorama Dijon	MARSANNAY-LA-COTE 21160
Castorama Marseille St - Loup	MARSEILLE 13010
Castorama Melun	MELUN 77000
Castorama Mérignac	MERIGNAC 33700
Castorama Metz Tessy	METZ-TESSY (ANNECY) 74370
Castorama Strasbourg	MUNDOLSHEIM 67452
Castorama Nantes La Beaujoire	NANTES 44300
Castorama Nîmes	NIMES 30900
Castorama Olivet	OLIVET 45160
Castorama Nantes Orvault	ORVAULT 44700
Castorama Bir Hakeim	PARIS 75015
Castorama Place de Clichy	PARIS 75018
Castorama Nation	PARIS 75020
Castorama Perpignan	PERPIGNAN 66100
Castorama Pierrelaye	PIERRELAYE 95480
Castorama Poitiers	POITIERS 86000
Castorama Portet sur Garonne	PORTET SUR GARONNE 31128
Castorama Quimper	QUIMPER 29000
Castorama Rillieux-La-Pape	RILLIEUX LA PAPE 69140
Castorama Gonesse	ROISSY CHARLES DE GAULLE 95700
Castorama Toulouse St Orens	SAINT-ORENS 31650
Castorama St Clément	ST CLEMENT DE RIVIERE 34980
Castorama Rennes-St Jacques	ST JACQUES DE LA LANDE 35136
Castorama St Marcel Les Valence	ST MARCEL LES VALENCE 26320
Castorama Grenoble	ST MARTIN D'HERES 38400
Castorama Creil St Maximin	ST MAXIMIN 60740
Castorama St Nazaire	ST NAZAIRE 44600
Castorama Terville	TERVILLE 57180
Castorama Reims Thillois	THILLOIS 51370
Castorama Vandoeuvre	VANDOEUVRE LES NANCY 54504
Castorama Vannes	VANNES 56000
Castorama Villabé	VILLABÉ 91100
Castorama Villemomble	VILLEMOMBLE 93250
Castorama Villenave d'Ornon	VILLENAVE D'ORNON 33140
Castorama Bourg-en-Bresse	VIRIAT 01440
Castorama Vitrolles	VITROLLES 13127
Castorama Vélizy	ZA VELIZY-VILLACOUBLAY 78140
Castorama Fréjus	ZONE D ACTIVITE GRAND ESTEREL 83600
"""


def parse_list() -> list[tuple[str, str, str]]:
    """Renvoie [(store_name, city, cp), ...] en filtrant les entrées non
    localisables (ex. "Castorama en ligne" sans CP)."""
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in RAW_STORES.splitlines():
        line = line.strip()
        if not line or not line.startswith("Castorama "):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[0].replace("Castorama ", "").strip()
        loc = parts[1].strip()
        if loc in {"—", "-", ""}:
            continue
        # Le champ "ville" contient le CP en suffixe (5 chiffres). Pour les BP/CS
        # (ex. "BP 98302 79043", "CS 20014 06110"), on garde juste le CP final.
        m = re.search(r"(\d{5})\s*$", loc)
        cp = m.group(1) if m else ""
        city = (loc[: m.start()] if m else loc).strip().strip(",").strip()
        # Cas tordus : "BP 98302 79043" → city devient "BP 98302", pas utile.
        # On remplace alors la ville par le décodage CP → on laisse tel quel
        # (sera géocodé via le CP seul si la ville ne match pas).
        if city.lower().startswith(("bp ", "cs ", "za ", "zone d")):
            city = ""
        key = (name.lower(), cp)
        if key in seen:
            continue
        seen.add(key)
        out.append((name, city, cp))
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


NOMINATIM = "https://nominatim.openstreetmap.org/search"


def geocode(city: str, cp: str = "") -> tuple[float, float] | None:
    # D'abord par CP seul (souvent le plus précis pour une commune française),
    # puis par "ville, CP, France" si besoin.
    for q in (f"{cp}, France" if cp else None,
              f"{city}, {cp}, France" if city and cp else None,
              f"{city}, France" if city else None):
        if not q:
            continue
        url = NOMINATIM + "?" + urllib.parse.urlencode({
            "q": q, "format": "json", "limit": 1, "countrycodes": "fr",
        })
        req = urllib.request.Request(url, headers={
            "User-Agent": "clim-portasplit-checker/1.0 (https://github.com/MathisKGN/clim-portasplit-checker)",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.load(r)
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            print(f"  geocode FAIL {q!r}: {e!r}")
        time.sleep(1.0)
    return None


def geocode_all(stores: list[tuple[str, str, str]]) -> list[dict]:
    cache_path = HERE / "data" / "geocoded_casto.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, list[float]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    out: list[dict] = []
    for i, (name, city, cp) in enumerate(stores, 1):
        key = f"{city or ''}|{cp}"
        c = cache.get(key)
        if not c:
            print(f"  [{i:>3}/{len(stores)}] geocode {city or '(cp)'} {cp}…",
                  end=" ", flush=True)
            c = geocode(city, cp)
            if c is None:
                print("FAIL (skip)")
                continue
            cache[key] = [c[0], c[1]]
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            print(f"{c[0]:.4f}, {c[1]:.4f}")
            time.sleep(1.0)  # Nominatim usage policy
        out.append({"name": name, "city": city, "cp": cp,
                    "lat": c[0], "lon": c[1]})
    return out


def greedy_set_cover(stores: list[dict], n: int) -> list[dict]:
    """Sélectionne un ensemble minimal de seeds (= positions de magasins)
    tel que chaque magasin tombe dans le top-N d'au moins un seed.

    Modèle : un seed placé sur le magasin S "voit" les N magasins les plus
    proches de S (S inclus). L'API Kingfisher renvoie exactement ce top-N pour
    un nearLatLong donné.
    """
    n = max(1, min(n, len(stores)))
    # Précalcule du voisinage top-N de chaque magasin (tri par distance).
    ids = list(range(len(stores)))
    neighborhoods: list[list[int]] = []
    for i in ids:
        dists = [(haversine_km(stores[i]["lat"], stores[i]["lon"],
                               stores[j]["lat"], stores[j]["lon"]), j)
                 for j in ids]
        dists.sort(key=lambda d: d[0])
        neighborhoods.append([j for _, j in dists[:n]])

    covered: set[int] = set()
    seeds: list[int] = []
    while len(covered) < len(stores):
        # Greedy : magasin qui couvre le plus de NON couverts.
        best_i, best_gain = max(
            ((i, len(set(neighborhoods[i]) - covered))
             for i in ids if i not in seeds),
            key=lambda kv: kv[1], default=(None, 0))
        if best_i is None or best_gain == 0:
            break
        seeds.append(best_i)
        covered.update(neighborhoods[best_i])
    return [stores[i] for i in seeds]


def emit_seeds_module(seeds: list[dict], total: int, path: Path, page_size: int):
    lines = [
        '"""',
        "Seeds Castorama France — couverture complète des magasins français",
        "en un minimum d'appels à l'API Kingfisher.",
        "",
        f"Calculés par map_casto_stores.py (greedy set-cover, page[size]={page_size})",
        f"à partir des coordonnées réelles de {total} magasins.",
        "",
        "Chaque seed est la position d'un magasin réel : l'API renvoie les",
        f"~{page_size} magasins les plus proches ; greedy set-cover ⇒ {len(seeds)}",
        "seeds suffisent à couvrir TOUS les magasins Casto FR.",
        '"""',
        "",
        "# (label, latitude, longitude)",
        "SEEDS_CASTO_FRANCE = [",
    ]
    for s in seeds:
        label = (s["name"] or s["city"] or s["cp"]).replace('"', "'")
        lines.append(f'    ("{label}", {s["lat"]:.6f}, {s["lon"]:.6f}),')
    lines += ["]", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--page-size", type=int, default=50,
                   help="Nombre de magasins renvoyés par appel API (défaut 50).")
    p.add_argument("--no-emit", action="store_true",
                   help="Ne pas écrire seeds_casto_france.py (juste afficher).")
    args = p.parse_args()

    stores = parse_list()
    print(f"[+] {len(stores)} magasins uniques à géocoder…")
    coords = geocode_all(stores)
    print(f"[+] {len(coords)}/{len(stores)} magasins géocodés.")

    seeds = greedy_set_cover(coords, args.page_size)
    print(f"\n[+] Set-cover (page_size={args.page_size}) : {len(seeds)} seeds "
          f"pour couvrir {len(coords)} magasins.")
    for s in seeds:
        print(f"    • {s['name']:<32} {s['cp']}  ({s['lat']:.4f}, {s['lon']:.4f})")

    # Sauvegarde pour réutilisation / debug.
    out_json = HERE / "data" / "casto_stores_geocoded.json"
    out_json.write_text(json.dumps(coords, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\n[+] Saved {out_json}")

    if not args.no_emit:
        out_py = HERE / "stockmonitor" / "seeds_casto_france.py"
        emit_seeds_module(seeds, len(coords), out_py, args.page_size)
        print(f"[+] Wrote {out_py} ({len(seeds)} seeds)")


if __name__ == "__main__":
    main()
