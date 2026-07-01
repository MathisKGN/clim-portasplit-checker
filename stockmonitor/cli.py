"""CLI unifiée pour le moniteur de stock multi-enseignes.

Usage
-----
  python -m stockmonitor lm            # boucle Leroy Merlin (défaut 900 s)
  python -m stockmonitor casto         # boucle Castorama
  python -m stockmonitor all           # tous les adapteurs, en séquence

  python -m stockmonitor lm --product-ref 12345678 --product-url https://...
  python -m stockmonitor lm --loop 0   # one-shot

Tous les defaults tunables (cadence, stable-rounds, zone, délais…) vivent
dans config.toml à la racine. La CLI ne garde que l'essentiel.

Arguments
  --config <path>      config alternatif (defaut: ./config.toml)
  --data-dir <path>    dossier sorties + cache (defaut: ./data)
  --loop <sec>         auto-boucle toutes les N sec (0 = one-shot, defaut 900)
  --notify-cmd <sh>    commande shell exécutée si restock
  --product-ref <ref>  override produit (EAN / réf catalogue)
  --product-url <url>  override URL fiche produit
  -v / --verbose       affiche les statuts inconnus
"""
from __future__ import annotations

import argparse
import random
import time
from pathlib import Path

from .base import ScannerBase
from .config import load_config
from .retailers import REGISTRY


# --------------------------------------------------------------------------- #
# Résolution des alias : on ne crée un subparser que pour le nom CANONIQUE
# d'une classe (premier nom rencontré dans le REGISTRY). Les alias pointent
# vers la même classe mais ne spamment pas --help.
# --------------------------------------------------------------------------- #
def _canonical_map() -> dict[type, str]:
    """Map classe -> premier nom rencontré (canonique). Construit une fois."""
    out: dict[type, str] = {}
    for name, cls in REGISTRY.items():
        if cls not in out:
            out[cls] = name
    return out


def _canonical_names() -> list[str]:
    return list(_canonical_map().values())


def _resolve(name: str) -> str | None:
    """Renvoie le nom canonique pour un alias, ou None si inconnu."""
    cls = REGISTRY.get(name)
    if cls is None:
        return None
    return _canonical_map().get(cls)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, metavar="PATH",
                        help="Chemin vers un config.toml alternatif (defaut: ./config.toml).")
    parser.add_argument("--data-dir", default=None, metavar="PATH",
                        help="Dossier sorties + cache/token/profil (defaut: ./data).")
    parser.add_argument("--loop", type=int, default=None, metavar="SECONDES",
                        help="Auto-boucle toutes les N sec (0 = one-shot, defaut: 900).")
    parser.add_argument("--notify-cmd", default=None, metavar="SH",
                        help="Commande shell exécutée si restock "
                             "(env: <PREFIX>_MESSAGE, <PREFIX>_STORES, …).")
    parser.add_argument("--product-ref", default=None, metavar="REF",
                        help="Override réf/EAN produit (sinon config.toml).")
    parser.add_argument("--product-url", default=None, metavar="URL",
                        help="Override URL fiche produit (sinon config.toml).")
    parser.add_argument("-v", "--verbose", action="store_true", default=None,
                        help="Affiche aussi les statuts inconnus.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stockmonitor",
        description="Moniteur de stock multi-enseignes (Leroy Merlin, Castorama).",
        usage="python -m stockmonitor <retailer> [options]\n"
              "       python -m stockmonitor all [options]",
    )
    sub = p.add_subparsers(dest="retailer", required=True, metavar="<retailer>")
    sp_all = sub.add_parser("all", help="Tous les adapteurs, en séquence.")
    _add_common_args(sp_all)

    for name in _canonical_names():
        cls = REGISTRY[name]
        sp = sub.add_parser(name, help=f"{cls.RETAILER_NAME}.")
        _add_common_args(sp)
        cls().add_arguments(sp)

    return p


def _instance_for(name: str) -> ScannerBase | None:
    canonical = _resolve(name)
    if not canonical:
        return None
    inst = REGISTRY[canonical]()
    return inst


def _default_event_handler(scanner: ScannerBase, args) -> "callable | None":
    """Handler d'events qui reimprime la progression quand -v (mode CLI legacy).

    Les scanners n'émettent plus de print() directement : sans handler, ils
    sont silencieux. En mode CLI, on branche ce handler pour restaurer le
    comportement verbeux d'avant (lignes `seed X/Y : N magasins (+M)`).
    """
    verbose = getattr(args, "verbose", False)
    if not verbose:
        return None

    def handler(event_type: str, payload: dict) -> None:
        et = event_type
        if et == "scan_start":
            print(f"  scan {payload.get('total_seeds', 0)} points "
                  f"({payload.get('zone', '?')})")
        elif et == "warmup":
            print(f"  warmup : {payload.get('detail') or payload.get('phase')}")
        elif et == "seed_done":
            print(f"    {payload.get('index')}/{payload.get('total')} "
                  f"{payload.get('label')} : {payload.get('found')} magasins "
                  f"(+{payload.get('new')})")
        elif et == "seed_blocked":
            print(f"    {payload.get('index')}/{payload.get('total')} "
                  f"{payload.get('label')} bloqué (status={payload.get('status')})")
        elif et == "remint":
            print(f"    [remint] {payload.get('reason')}")
        elif et == "online":
            avail = payload.get("home_delivery")
            print(f"  🌐 en ligne : {avail}")
        elif et == "scan_done":
            pass
    return handler


def _canonical_instances() -> list[ScannerBase]:
    return [REGISTRY[n]() for n in _canonical_names()]


# --------------------------------------------------------------------------- #
# Entrée
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = load_config(getattr(args, "config", None))

    # Common defaults (quand la CLI n'a rien passé ni le config).
    _fallback(args, "data_dir", str(Path("data")), cfg.get("common", {}))
    _fallback(args, "loop", 900, cfg.get("common", {}))
    _fallback(args, "notify_cmd", "", cfg.get("common", {}))
    _fallback(args, "verbose", False, cfg.get("common", {}))
    Path(args.data_dir).mkdir(parents=True, exist_ok=True)

    if args.retailer == "all":
        return _run_all(_canonical_instances(), args, cfg)

    instance = _instance_for(args.retailer)
    if not instance:
        parser.error(f"Enseigne inconnue : {args.retailer}")
    handler = _default_event_handler(instance, args)
    if handler:
        instance.set_event_handler(handler)
    instance.run_main(args, cfg)
    return 0


def _fallback(args, key: str, hard_default, cfg_section: dict) -> None:
    """Applique la priorité : CLI > config.toml > default codé."""
    if getattr(args, key, None) is not None:
        return
    val = cfg_section.get(key)
    if val is not None:
        setattr(args, key, val)
        return
    setattr(args, key, hard_default)


def _namespace_for_scanner(scanner: ScannerBase, args, cfg: dict) -> argparse.Namespace:
    """Construit un Namespace pour `scanner` en mode `all`.

    On repart d'un Namespace vide (juste les overrides CLI communs), puis on
    laisse apply_config() remplir le reste (defaults codés + config.toml).
    """
    ns = argparse.Namespace()
    # On propage uniquement les champs communs réellement passés en CLI
    # (les autres viendront de config via apply_config).
    for k in ("config", "data_dir", "loop", "notify_cmd", "product_ref",
              "product_url", "verbose"):
        if hasattr(args, k):
            setattr(ns, k, getattr(args, k))
    scanner.apply_config(ns, cfg)
    return ns


def _run_all(instances: list[ScannerBase], args, cfg) -> int:
    """Lance toutes les enseignes en séquence ; boucle si --loop > 0."""
    names = ", ".join(s.RETAILER_NAME for s in instances)
    print(f"[{_ts()}] stockmonitor · {len(instances)} enseignes : {names}")

    def _one_pass() -> int:
        rc = 0
        for i, s in enumerate(instances):
            if i:
                print()
            try:
                ns = _namespace_for_scanner(s, args, cfg)
                handler = _default_event_handler(s, ns)
                if handler:
                    s.set_event_handler(handler)
                s.run_once(ns)
            except Exception as e:
                rc = 1
                print(f"[{_ts()}] {s.RETAILER_NAME} ✗ {e!r}")
        return rc

    if not (args.loop and args.loop > 0):
        print()
        return _one_pass()

    print(f"\nMode boucle toutes les {args.loop}s. Ctrl-C pour arrêter.")
    try:
        while True:
            _one_pass()
            time.sleep(args.loop + random.uniform(0, args.loop * 0.15))
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
        return 0


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
