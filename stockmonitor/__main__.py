"""Permet `python -m stockmonitor`.

Sans argument : lance le mode interactif (prompts flèches + dashboard Rich).
Avec arguments : bascule sur la CLI legacy (`python -m stockmonitor lm …`).
"""
import sys


def main() -> int:
    # Si on a des args (au-delà du nom du module), garde la CLI classique.
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        return cli_main()
    # Sinon : mode interactif.
    from .interactive import main as interactive_main
    return interactive_main()


if __name__ == "__main__":
    raise SystemExit(main())
