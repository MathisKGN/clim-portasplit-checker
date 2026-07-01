"""CLI unifiée pour le moniteur de stock multi-enseignes.

Usage
-----
  python -m stockmonitor lm           # un run Leroy Merlin (IDF)
  python -m stockmonitor casto        # un run Castorama (France entière)
  python -m stockmonitor all          # tous les adapteurs, en séquence

  python -m stockmonitor lm --loop 1800
  python -m stockmonitor casto --notify-cmd ./notify.sh -v

Arguments communs :
  --data-dir <path>   dossier sorties + cache (defaut: ./data)
  --loop <sec>        auto-boucle toutes les N secondes
  --notify-cmd <sh>   commande shell exécutée si restock (env: <PREFIX>_*)
  -v / --verbose      affiche les statuts inconnus

Arguments spécifiques : voir `python -m stockmonitor <retailer> --help`.
"""
from __future__ import annotations

import argparse
import random
import time
from pathlib import Path

from .base import ScannerBase
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
    parser.add_argument("--data-dir",
                        default=str(Path(__file__).resolve().parent.parent / "data"),
                        help="Dossier sorties + cache/token/profil.")
    parser.add_argument("--loop", type=int, default=0, metavar="SECONDES",
                        help="Auto-boucle toutes les N secondes (0 = un seul run).")
    parser.add_argument("--notify-cmd", default=None,
                        help="Commande shell exécutée si restock "
                             "(env: <PREFIX>_MESSAGE, <PREFIX>_STORES, …).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Affiche aussi les statuts inconnus.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stockmonitor",
        description="Moniteur de stock multi-enseignes (Leroy Merlin, Castorama, …).",
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
    return REGISTRY[canonical]()


def _canonical_instances() -> list[ScannerBase]:
    out: list[ScannerBase] = []
    for name in _canonical_names():
        out.append(REGISTRY[name]())
    return out


# --------------------------------------------------------------------------- #
# Entrée
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    Path(args.data_dir).mkdir(parents=True, exist_ok=True)

    if args.retailer == "all":
        return _run_all(_canonical_instances(), args)

    instance = _instance_for(args.retailer)
    if not instance:
        parser.error(f"Enseigne inconnue : {args.retailer}")
    instance.run_main(args)
    return 0


def _namespace_for_scanner(scanner: ScannerBase, args) -> argparse.Namespace:
    """Construit un Namespace complet pour `scanner` en mode `all`.

    Le parser `all` ne contient que les args communs ; on complète avec les
    defaults spécifiques au scanner. Les valeurs communes fournies par
    l'utilisateur (--data-dir, --loop, --notify-cmd, --verbose) sont propagées.
    """
    p = argparse.ArgumentParser(add_help=False)
    _add_common_args(p)
    scanner.add_arguments(p)
    ns = p.parse_args([])  # defaults spécifiques + communs
    # Override avec les valeurs communes réellement passées par l'utilisateur.
    for k, v in vars(args).items():
        setattr(ns, k, v)
    return ns


def _run_all(instances: list[ScannerBase], args) -> int:
    """Lance toutes les enseignes en séquence ; boucle si --loop > 0."""
    names = ", ".join(s.RETAILER_NAME for s in instances)
    print(f"[{_ts()}] stockmonitor · {len(instances)} enseignes : {names}")

    def _one_pass() -> int:
        rc = 0
        for i, s in enumerate(instances):
            if i:
                print()  # séparateur entre enseignes
            try:
                ns = _namespace_for_scanner(s, args)
                s.run_once(ns)
            except Exception as e:
                rc = 1
                print(f"[{_ts()}] {s.RETAILER_NAME} ✗ {e!r}")
        return rc

    if not (args.loop and args.loop > 0):
        print()
        rc = _one_pass()
        return rc

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
