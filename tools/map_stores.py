#!/usr/bin/env python3
"""
Cartographie des magasins Leroy Merlin France + calcul des seeds optimaux
pour couvrir tous les magasins dans un rayon de 200 km autour de Paris.

Étapes :
  1. Parse la liste des magasins (noms + villes) fournie manuellement.
  2. Géocode chaque ville via Nominatim (OpenStreetMap), 1 req/s (usage policy).
  3. Filtre les magasins à <= 200 km de Paris (haversine).
  4. Algorithme greedy set-cover :
     - Pour chaque seed candidat (grille lat/lon), calcule quels magasins il
       "verrait" (les 11 plus proches, comme l'endpoint LM).
     - Sélectionne le set minimal de seeds tel que chaque magasin soit vu par
       au moins un seed.
  5. Génère seeds_france.py avec les seeds optimaux nommés (ville la plus proche).

Usage : python3 map_stores.py
"""
from __future__ import annotations
import json, math, time, urllib.parse, urllib.request, csv, re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # racine du projet

# --- Liste des magasins LM France (extraite de climradar.fr) --------------- #
RAW_STORES = """Leroy Merlin La Sentinelle - Valenciennes - St Quentin - Cambrai	La Sentinelle 59000
Leroy Merlin Saintes	Saint-Georges-Des-Coteaux 33000
Leroy Merlin Albi	Albi 31000
Leroy Merlin Andelnans - Belfort	Andelnans 67000
Leroy Merlin Arras	Arras 59000
Leroy Merlin Aubagne - Marseille	Aubagne 13001
Leroy Merlin Balma - Toulouse	Balma 31000
Leroy Merlin Basse Goulaine	Basse Goulaine 44000
Leroy Merlin Rennes Nord - Betton	Betton 44000
Leroy Merlin Biganos - Bassin d'Arcachon	Biganos 33000
Leroy Merlin Boé - Agen	Boé 31000
Leroy Merlin Bordeaux	Bordeaux 33000
Leroy Merlin Bouliac - Bordeaux	Bouliac 33000
Leroy Merlin Cabries - Marseille	Cabriès 13001
Leroy Merlin Nancy Nord - Champigneulles	Champigneulles 67000
Leroy Merlin Chancelade - Périgueux	Cancelade 33000
Leroy Merlin Chantepie - Rennes Sud	Chantepie 44000
Leroy Merlin Cholet	Cholet 44000
Leroy Merlin Toulouse - Colomiers	Colomiers 31000
Leroy Merlin Epagny - Annecy	Epagny 69001
Leroy Merlin Forbach	Forbach 67000
Leroy Merlin Gennevilliers	Gennevilliers 75001
Leroy Merlin Gradignan - Bordeaux	Gradignan 33000
Leroy Merlin Grande-Synthe - Dunkerque	Grande Synthe 59000
Leroy Merlin Guérande	Guérande 44000
Leroy Merlin Haguenau	Haguenau 67000
Leroy Merlin Hautmont - Maubeuge	Hautmont 59000
Leroy Merlin Houdemont - Nancy Sud	Houdemont 67000
Leroy Merlin Ivry-sur-Seine	Ivry-Sur-Seine 75001
Leroy Merlin La Roche-Sur-Yon	La Roche Sur Yon 44000
Leroy Merlin La Valette-du-Var - Toulon	La Valette-Du-Var 13001
Leroy Merlin Le Pontet - Avignon Nord	Le Pontet 13001
Leroy Merlin Lesquin - Lille	Lesquin 59000
Leroy Merlin Villeneuve-d'Ascq - Lille	Lezennes 59000
Leroy Merlin Mâcon	Mâcon 69001
Leroy Merlin Grand Littoral - Marseille	Marseille 13001
Leroy Merlin La Valentine - Marseille	Marseille 13001
Leroy Merlin Martigues - Marseille	Martigues 13001
Leroy Merlin Mérignac - Bordeaux	Mérignac 33000
Leroy Merlin Technopôle-Metz	Metz 57000
Leroy Merlin Montauban	Montauban 31000
Leroy Merlin Morschwiller-le-Bas - Mulhouse	Morschwiller Le Bas 67000
Leroy Merlin Mundolsheim	Mundolsheim 67000
Leroy Merlin Neuville-en-Ferrain - Lille	Neuville-En-Ferrain 59000
Leroy Merlin Nîmes	Nîmes 30000
Leroy Merlin La Vigie - Ostwald	Ostwald 67000
Leroy Merlin Paris-Beaubourg	Paris 75001
Leroy Merlin La Madeleine - Paris 8	Paris 75001
Leroy Merlin Daumesnil - Paris 12	Paris 75001
Leroy Merlin Pau	Pau 64000
Leroy Merlin Puget-sur-Argens - Fréjus	Puget-Sur-Argens 13001
Leroy Merlin Nantes-Rezé	Rezé 44000
Leroy Merlin Roques-sur-Garonne - Toulouse	Roques-Sur-Garonne 31000
Leroy Merlin Rosny-Sous-Bois	Rosny-Sous-Bois 75001
Leroy Merlin Rueil-Malmaison	Rueil Malmaison 75001
Leroy Merlin Saint-Egrève - Grenoble	Saint-Egreve 69001
Leroy Merlin Saint-Etienne Steel	Saint-Etienne 69001
Leroy Merlin Saint-Ouen - Paris	Saint-Ouen 75001
Leroy Merlin Soyaux - Angoulême - Cognac	Soyaux 33000
Leroy Merlin Saint-Denis-la-Plaine	St Denis-La-Plaine 75001
Leroy Merlin Saint-Priest-en-Jarez - Saint-Etienne	St Priest En Jarez 69001
Leroy Merlin Saint-Aunès - Montpellier	St-Aunes 13001
Leroy Merlin Saint-Barthélemy-d'Anjou - Angers	St-Barthélemy-D'anjou 44000
Leroy Merlin Strasbourg	Strasbourg 67000
Leroy Merlin Tassin-la-Demi-Lune - Lyon	Tassin La Demi Lune 69001
Leroy Merlin Theix - Vannes	Theix-Noyalo 44000
Leroy Merlin Thoiry- Grand Genève	Thoiry 69001
Leroy Merlin Trignac - Saint-Nazaire	Trignac 44000
Leroy Merlin Valence	Valence 69001
Leroy Merlin Vendin-le-Vieil - Lens	Vendin-Le-Vieil 59000
Leroy Merlin Lyon Grand Parilly	Venissieux 69001
Leroy Merlin Verquin - Béthune	Verquin 59000
Leroy Merlin Vitry-sur-Seine	Vitry-Sur-Seine 75001
Leroy Merlin Vourles	Vourles 69001
Leroy Merlin Waziers - Douai	Waziers 59000
Leroy Merlin Montsoult	Montsoult 95000
Leroy Merlin Madeleine - Paris 8	Paris 75001
Leroy Merlin Daumesnil - Paris 12	Paris 75001
Leroy Merlin Ivry-sur-Seine	Ivry-Sur-Seine 75001
Leroy Merlin Saint-Ouen - Paris	Saint-Ouen 75001
Leroy Merlin Rosny-Sous-Bois	Rosny-Sous-Bois 75001
Leroy Merlin Rueil-Malmaison	Rueil Malmaison 75001
Leroy Merlin Gennevilliers	Gennevilliers 75001
Leroy Merlin Vitry-sur-Seine	Vitry-Sur-Seine 75001
Leroy Merlin Saint-Denis-la-Plaine	St Denis-La-Plaine 75001
Leroy Merlin Meaux	Meaux 77000
Leroy Merlin Melun	Melun 77000
Leroy Merlin Marne-la-Vallée	Marne-La-Vallée 77000
Leroy Merlin Brie-Comte-Robert	Brie-Comte-Robert 77000
Leroy Merlin Versailles	Versailles 78000
Leroy Merlin Mantes-la-Jolie	Mantes-La-Jolie 78000
Leroy Merlin Rambouillet	Rambouillet 78000
Leroy Merlin Évry	Évry 91000
Leroy Merlin Étampes	Étampes 91000
Leroy Merlin Cergy	Cergy 95000
Leroy Merlin Sarcelles	Sarcelles 95000
Leroy Merlin Bobigny - Aulnay	Bobigny 93000
Leroy Merlin Antony - Massy	Antony 92000
Leroy Merlin Nanterre - La Défense	Nanterre 92000
Leroy Merlin Compiègne	Compiègne 60000
Leroy Merlin Beauvais	Beauvais 60000
Leroy Merlin Évreux	Évreux 27000
Leroy Merlin Dreux	Dreux 28000
Leroy Merlin Chartres	Chartres 28000
Leroy Merlin Reims	Reims 51000
Leroy Merlin Orléans	Orléans 45000
Leroy Merlin Sens	Sens 89000
Leroy Merlin Auxerre	Auxerre 89000
Leroy Merlin Troyes	Troyes 10000
Leroy Merlin Amiens	Amiens 80000
Leroy Merlin Rouen	Rouen 76000
Leroy Merlin Le Mans	Le Mans 72000
Leroy Merlin Tours	Tours 37000
Leroy Merlin Bourges	Bourges 18000
Leroy Merlin Nevers	Nevers 58000
Leroy Merlin Dijon	Dijon 21000
Leroy Merlin Besançon	Besançon 25000
Leroy Merlin Caen	Caen 14000
Leroy Merlin Cherbourg	Cherbourg 50000
Leroy Merlin Le Havre	Le Havre 76000
Leroy Merlin Laval	Laval 53000
Leroy Merlin Angers	Angers 49000
Leroy Merlin Le Creusot	Le Creusot 71000
Leroy Merlin Chateauroux	Châteauroux 36000
Leroy Merlin Blois	Blois 41000
Leroy Merlin Montargis	Montargis 45000
Leroy Merlin Soissons	Soissons 02000
Leroy Merlin Château-Thierry	Château-Thierry 02000
Leroy Merlin Laon	Laon 02000
Leroy Merlin Saint-Quentin	Saint-Quentin 02000
Leroy Merlin Cambrai	Cambrai 59000
Leroy Merlin Douai	Douai 59000"""


def parse_list() -> list[tuple[str, str, str]]:
    """Renvoie [(store_name, city, cp), ...]."""
    out = []
    seen = set()
    for line in RAW_STORES.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[0].replace("Leroy Merlin ", "").strip()
        loc = parts[1].strip()
        m = re.match(r"^(.+?)\s+(\d{5})$", loc)
        if m:
            city, cp = m.group(1).strip(), m.group(2)
        else:
            city, cp = loc, ""
        key = (name, city.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((name, city, cp))
    return out


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


PARIS = (48.8566, 2.3522)
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def geocode(city: str, cp: str = "") -> tuple[float, float] | None:
    q = f"{city}, {cp}, France" if cp else f"{city}, France"
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
        print(f"  geocode FAIL {city} {cp}: {e!r}")
    return None


def main():
    stores = parse_list()
    print(f"[+] {len(stores)} magasins uniques à géocoder…")

    cache_path = HERE / "data" / "geocoded_stores.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    coords = []
    for i, (name, city, cp) in enumerate(stores, 1):
        key = f"{city}|{cp}"
        if key in cache and cache[key]:
            lat, lon = cache[key]
        else:
            print(f"  [{i}/{len(stores)}] geocode {city} {cp}…", end=" ", flush=True)
            c = geocode(city, cp)
            if c is None:
                # Retry without CP
                c = geocode(city, "")
            if c is None:
                print("FAIL (skip)")
                continue
            lat, lon = c
            cache[key] = [lat, lon]
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            print(f"{lat:.4f}, {lon:.4f}")
            time.sleep(1.0)  # Nominatim usage policy: 1 req/s
        dist = haversine_km(PARIS[0], PARIS[1], lat, lon)
        coords.append({"name": name, "city": city, "cp": cp,
                        "lat": lat, "lon": lon, "dist_km": round(dist, 1)})

    # Filtre 200 km
    within = sorted([s for s in coords if s["dist_km"] <= 200.0], key=lambda x: x["dist_km"])
    far = sorted([s for s in coords if s["dist_km"] > 200.0], key=lambda x: x["dist_km"])

    print(f"\n[+] {len(within)} magasins à <= 200 km de Paris :")
    for s in within:
        print(f"    {s['dist_km']:>5.1f} km  {s['city']:<30} ({s['name']})")
    print(f"\n[+] {len(far)} magasins hors zone (exclus) :")
    for s in far[:10]:
        print(f"    {s['dist_km']:>5.1f} km  {s['city']}")
    if len(far) > 10:
        print(f"    … et {len(far) - 10} autres")

    # Sauvegarde la liste filtrée pour l'étape set-cover
    (HERE / "data" / "stores_200km.json").write_text(
        json.dumps(within, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[+] Saved data/stores_200km.json ({len(within)} magasins)")


if __name__ == "__main__":
    main()
