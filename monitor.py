"""Point d'entrée racine — wrapper mince autour de `python -m stockmonitor`.

  python monitor.py <retailer> [options]
  python monitor.py all [options]
  python monitor.py --help
"""
from stockmonitor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
