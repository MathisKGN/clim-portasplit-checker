"""Mode interactif — `python -m stockmonitor` sans args.

Prompts flèches (questionary) + dashboard temps réel (Rich Live) qui se met
à jour à chaque seed scanné. Aucun argument à retenir : on demande.

Flow
----
1. Bannière de bienvenue.
2. Choix enseigne (LM / Casto / les deux).
3. Pour LM : choix zone (IDF / IDF élargi / Paris 200km / France).
4. Produit : défaut ou URL custom.
5. Mode : one-shot ou boucle (intervalle).
6. Lancement : dashboard Rich Live qui consomme les events émis par les
   scanners et rend les magasins au fur et à mesure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from .base import ScannerBase
from .config import load_config
from .retailers import REGISTRY


# --------------------------------------------------------------------------- #
# Dépendances optionnelles (rich / questionary)
# --------------------------------------------------------------------------- #
def _require_pkgs() -> None:
    missing = []
    try:
        import rich  # noqa: F401
    except ImportError:
        missing.append("rich")
    try:
        import questionary  # noqa: F401
    except ImportError:
        missing.append("questionary")
    if missing:
        sys.exit(
            "Le mode interactif nécessite : " + ", ".join(missing) + ".\n"
            "Installe : pip install " + " ".join(missing)
        )


def _pick_retailer() -> str | None:
    import questionary
    return questionary.select(
        "Quelle enseigne scannes-tu ?",
        choices=[
            questionary.Choice("Leroy Merlin", value="lm"),
            questionary.Choice("Castorama", value="casto"),
            questionary.Choice("Les deux (en séquence)", value="all"),
        ],
        use_arrow_keys=True,
    ).ask()


def _pick_lm_zone() -> tuple[str, bool] | None:
    """Renvoie (zone, wide)."""
    import questionary
    choice = questionary.select(
        "Quelle zone pour Leroy Merlin ?",
        choices=[
            questionary.Choice("IDF (cœur, ~36 magasins, rapide)", value="idf_core"),
            questionary.Choice("IDF élargi (Reims/Troyes/Orléans…)", value="idf_wide"),
            questionary.Choice("Paris 200 km (~55 magasins ciblés)", value="paris200"),
            questionary.Choice("France entière (~146 magasins, long)", value="france"),
        ],
        use_arrow_keys=True,
    ).ask()
    if choice is None:
        return None
    if choice == "idf_core":
        return "idf", False
    if choice == "idf_wide":
        return "idf", True
    if choice == "paris200":
        return "paris200", False
    return "france", False


def _pick_product(default_url: str) -> str | None:
    import questionary
    use_default = questionary.confirm(
        f"Garder le produit par défaut ?\n  {default_url}",
        default=True,
    ).ask()
    if use_default is None:
        return None
    if use_default:
        return default_url
    url = questionary.text(
        "Colle l'URL de la fiche produit :",
        validate=lambda s: s.startswith("http") or "URL invalide",
    ).ask()
    return url


def _pick_loop() -> tuple[int, int] | None:
    """Renvoie (loop_seconds, 0=one-shot)."""
    import questionary
    mode = questionary.select(
        "Mode d'exécution ?",
        choices=[
            questionary.Choice("One-shot (un scan puis stop)", value="one"),
            questionary.Choice("Boucle — 15 min", value="900"),
            questionary.Choice("Boucle — 30 min", value="1800"),
            questionary.Choice("Boucle — 60 min", value="3600"),
        ],
        use_arrow_keys=True,
    ).ask()
    if mode is None:
        return None
    if mode == "one":
        return 0, 0
    return int(mode), int(mode)


# --------------------------------------------------------------------------- #
# Dashboard temps réel
# --------------------------------------------------------------------------- #
_STATE_ICONS = {
    "IN": ("●", "bold green"),
    "OUT": ("○", "dim red"),
    "NOT_CARRIED": ("◌", "dim"),
    "UNKNOWN": ("?", "yellow"),
}


class Dashboard:
    """Renderable Rich qui se reconstruit à chaque refresh (auto_refresh).

    Lit l'état mutable `state` (mis à jour par le handler d'events).
    """

    def __init__(self, state: dict):
        self.state = state

    def __rich__(self):
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        from rich.spinner import Spinner
        from rich.columns import Columns

        s = self.state
        phase = s.get("phase", "idle")
        now = dt.datetime.now()

        # --- En-tête ------------------------------------------------------- #
        title = Text()
        title.append(f"  {s['retailer']}", style="bold cyan")
        if s.get("zone"):
            title.append(f"  ·  {s['zone']}", style="magenta")
        title.append(f"  ·  cycle #{s.get('cycle', 1)}", style="dim")
        # Chrono total du scan (à droite).
        scan_start = s.get("scan_started_at")
        if scan_start:
            elapsed = now - scan_start
            mm, ss = divmod(int(elapsed.total_seconds()), 60)
            title.append(f"  ·  ⏱ {mm:02d}:{ss:02d}", style="dim cyan")

        # --- Statut actuel (spinner + ligne) ------------------------------- #
        if phase == "scanning":
            spinner = Spinner("dots", text=self._status_text(s), style="cyan")
            status_line = spinner
        elif phase == "warmup":
            spinner = Spinner("dots", text=self._status_text(s), style="yellow")
            status_line = spinner
        elif phase == "pausing":
            pause_until = s.get("pause_until")
            if pause_until and pause_until > now:
                secs = max(0, int((pause_until - now).total_seconds()))
                spinner = Spinner("dots", text=Text(
                    f"  pause {secs}s avant le prochain point",
                    style="dim cyan"), style="cyan")
                status_line = spinner
            else:
                status_line = Text("  …", style="dim")
        elif phase == "done":
            status_line = Text("✓ Scan terminé", style="bold green")
        elif phase == "countdown":
            remaining = s.get("next_at")
            if remaining:
                secs = max(0, int((remaining - now).total_seconds()))
                mm, ss = divmod(secs, 60)
                spinner = Spinner("moon", text=Text(
                    f"  Prochaine vérif dans {mm:02d}:{ss:02d}", style="cyan"))
                status_line = spinner
            else:
                status_line = Text("  En attente…", style="dim")
        else:
            status_line = Text("  …", style="dim")

        # --- Barre de progression ------------------------------------------ #
        prog = self._progress(s)

        # --- Table magasins (en stock d'abord, puis derniers découverts) -- #
        table = Table(expand=True, box=None, pad_edge=False, show_header=True,
                      header_style="bold")
        table.add_column("Magasin", overflow="fold")
        table.add_column("État", width=4)
        table.add_column("Distance", width=9)
        table.add_column("Détail", overflow="fold", ratio=1)

        stores = s.get("stores", {})
        # On affiche les En stock en premier, puis les derniers découverts.
        ordered = sorted(
            stores.values(),
            key=lambda st: (0 if st.get("restock") else 1,
                            -(st.get("_ts_idx", 0))),
        )
        shown = 0
        for st in ordered:
            if shown >= 15:
                break
            icon, style = _STATE_ICONS.get(st.get("state", "UNKNOWN"),
                                           ("?", "yellow"))
            name = st.get("name", st.get("id", "?"))
            if st.get("restock"):
                name = Text(name, style="bold")
            dist = st.get("distance_km")
            dist_str = f"{dist} km" if dist is not None else "—"
            detail = (st.get("status_text") or st.get("stock_level")
                      or st.get("cc_message") or "")
            qty = st.get("quantity")
            if qty is not None:
                detail = f"{qty} pc · {detail}".strip(" ·")
            table.add_row(
                name,
                Text(icon, style=style),
                Text(dist_str, style="dim"),
                Text(detail, style=style if st.get("state") == "IN" else "dim"),
            )
            shown += 1

        # --- Résumé -------------------------------------------------------- #
        summary_parts = [
            f"{len(stores)} magasins",
            f"{s.get('in_stock', 0)} en stock",
        ]
        if s.get("blocked"):
            summary_parts.append(f"⚠ {s['blocked']} bloqué(s)")
        if s.get("online") is not None:
            on = s["online"]
            tag = "commandable" if on.get("available") else "rupture"
            summary_parts.append(f"🌐 {on.get('home_delivery','?')} ({tag})")
        if not s.get("completed", True) and not s.get("blocked"):
            summary_parts.append("scan incomplet")
        summary = Text("  " + "  ·  ".join(summary_parts),
                       style="bold" if s.get("in_stock") else "dim")

        body = Group(title, Text(""), status_line, prog, Text(""),
                     table, Text(""), summary)
        return Panel(body, border_style="cyan", padding=(1, 2),
                     title=f"[bold cyan]stockmonitor[/]")

    def _status_text(self, s) -> "Text":
        from rich.text import Text
        now = dt.datetime.now()
        phase = s.get("phase", "idle")
        if phase == "warmup":
            t = Text(f"  Préparation : {s.get('action', '…')}", style="yellow")
            ws = s.get("warmup_started_at")
            if ws:
                secs = int((now - ws).total_seconds())
                t.append(f"  ({secs}s)", style="dim")
            return t
        idx = s.get("index", 0)
        total = s.get("total", 0)
        label = s.get("label", "")
        action = s.get("action", "")
        t = Text()
        t.append(f"  {action} " if action else "  Scan ")
        if total:
            t.append(f"{idx}/{total}", style="bold cyan")
            t.append(f"  {label}", style="dim")
        # Chrono du seed en cours.
        ss = s.get("seed_started_at")
        if ss:
            secs = int((now - ss).total_seconds())
            t.append(f"  ({secs}s)", style="dim cyan")
        return t

    def _progress(self, s):
        from rich.text import Text
        idx = s.get("index", 0)
        total = s.get("total", 0) or 1
        done = max(0, min(idx, total))
        width = 28
        filled = int(width * done / total)
        bar = "█" * filled + "░" * (width - filled)
        pct = int(100 * done / total)
        return Text(f"  {bar} {pct:3d}%  ({done}/{total})", style="cyan")


# --------------------------------------------------------------------------- #
# Handler d'events -> met à jour l'état du dashboard
# --------------------------------------------------------------------------- #
def make_handler(state: dict, scanner: ScannerBase):
    def handler(event_type: str, payload: dict) -> None:
        if event_type == "scan_start":
            state["total"] = payload.get("total_seeds", 0)
            state["index"] = 0
            state["zone"] = payload.get("zone", state.get("zone", ""))
            state["phase"] = "scanning"
            state["action"] = "Scan"
            state["label"] = ""
            state["blocked"] = 0
            state["completed"] = False
            state["scan_started_at"] = dt.datetime.now()
            state["seed_started_at"] = None
            state["pause_until"] = None
            state["warmup_started_at"] = None
        elif event_type == "warmup":
            state["phase"] = "warmup"
            state["action"] = (payload.get("detail") or payload.get("phase", "")
                               ).replace("_", " ")
            state["warmup_started_at"] = dt.datetime.now()
            state["seed_started_at"] = None
            state["pause_until"] = None
        elif event_type == "seed_start":
            state["phase"] = "scanning"
            state["index"] = payload.get("index", state.get("index", 0))
            state["total"] = payload.get("total", state.get("total", 0))
            state["label"] = payload.get("label", "")
            state["action"] = "Point"
            state["seed_started_at"] = dt.datetime.now()
            state["pause_until"] = None
        elif event_type == "seed_done":
            state["phase"] = "scanning"
            state["index"] = payload.get("index", state.get("index", 0))
            state["total"] = payload.get("total", state.get("total", 0))
            state["label"] = payload.get("label", "")
            state["seed_started_at"] = None  # seed fini, chrono figé
            added = payload.get("stores_added") or []
            ts_idx = state.get("_counter", 0)
            for st in added:
                ts_idx += 1
                st["_ts_idx"] = ts_idx
                state["stores"][st.get("id") or st.get("slug")
                                or st.get("name")] = st
            state["_counter"] = ts_idx
            state["in_stock"] = sum(
                1 for s in state["stores"].values() if s.get("restock"))
        elif event_type == "seed_blocked":
            state["blocked"] = state.get("blocked", 0) + 1
            state["label"] = payload.get("label", "")
            state["seed_started_at"] = None
        elif event_type == "pause":
            # Sleep bloquant : on pose une cible temps pour le countdown.
            state["phase"] = "pausing"
            state["pause_until"] = (dt.datetime.now()
                                   + dt.timedelta(seconds=payload.get("seconds", 0)))
            state["seed_started_at"] = None
        elif event_type == "remint":
            state["phase"] = "warmup"
            state["action"] = "re-mint session"
            state["warmup_started_at"] = dt.datetime.now()
            state["pause_until"] = None
            state["seed_started_at"] = None
        elif event_type == "online":
            state["online"] = {
                "available": payload.get("available", False),
                "home_delivery": payload.get("home_delivery"),
            }
        elif event_type == "scan_done":
            state["phase"] = "done"
            state["in_stock"] = payload.get("in_stock", 0)
            state["blocked"] = payload.get("blocked", 0)
            state["completed"] = payload.get("completed", True)
            state["seed_started_at"] = None
            state["pause_until"] = None
    return handler


# --------------------------------------------------------------------------- #
# Cycle d'exécution
# --------------------------------------------------------------------------- #
def _build_namespace(overrides: dict, cfg: dict) -> argparse.Namespace:
    """Construit un Namespace vierge puis laisse apply_config remplir."""
    ns = argparse.Namespace()
    # Champs communs + overrides spécifiques (zone/wide pour LM, …).
    keys = ("config", "data_dir", "loop", "notify_cmd", "product_ref",
            "product_url", "verbose", "zone", "wide")
    for k in keys:
        if k in overrides:
            setattr(ns, k, overrides[k])
        else:
            setattr(ns, k, None)
    return ns


class _NullStdout:
    """Supprime les print() du scanner pendant le cycle (dashboard gère l'affichage).

    Rich Live écrit via son propre Console (créé AVANT la redirection, donc
    ancré sur le vrai stdout) ; seul le builtin print() est étouffé.
    """
    def write(self, _): pass
    def flush(self): pass


def _run_with_live(scanner: ScannerBase, ns: argparse.Namespace,
                   state: dict) -> dict:
    """Lance un cycle tout en rendant le dashboard Live.

    `run_once` appelle `run_cycle` qui appelle `report()` (des print). On
    redirige stdout vers _NullStdout pendant le cycle : le dashboard Rich
    (qui écrit via son propre Console) prend le relais.
    """
    from rich.live import Live
    from rich.console import Console

    # Reset état pour ce cycle (une photo fraîche).
    state["stores"] = {}
    state["in_stock"] = 0
    state["blocked"] = 0
    state["completed"] = False
    state["online"] = None
    state["phase"] = "warmup"
    state["action"] = "Ouverture session"
    state["label"] = ""
    state["index"] = 0
    state["total"] = 0
    state["_counter"] = 0
    state["scan_started_at"] = None
    state["seed_started_at"] = None
    state["pause_until"] = None
    state["warmup_started_at"] = None

    dash = Dashboard(state)
    # On épingle file=sys.stdout ICI (avant redirection) : Rich résout
    # `sys.stdout` dynamiquement à chaque write quand file=None, donc sans ça
    # la redirection vers _NullStdout étoufferait aussi le rafraîchissement
    # du Live (dashboard jamais mis à jour pendant le scan).
    console = Console(file=sys.stdout)
    scanner.set_event_handler(make_handler(state, scanner))

    with Live(dash, console=console, refresh_per_second=4, transient=False,
              screen=False) as live:
        old_stdout = sys.stdout
        sys.stdout = _NullStdout()
        try:
            result = scanner.run_once(ns)
        finally:
            sys.stdout = old_stdout

        # Laisse le dashboard final visible un instant.
        state["phase"] = "done"
        live.update(dash)
        time.sleep(0.2)

    return result


def _countdown(state: dict, seconds: int) -> None:
    """Attente avec rafraîchissement Live (compte à rebours)."""
    from rich.live import Live
    from rich.console import Console

    state["phase"] = "countdown"
    state["next_at"] = dt.datetime.now() + dt.timedelta(seconds=seconds)
    dash = Dashboard(state)
    console = Console(file=sys.stdout)
    with Live(dash, console=console, refresh_per_second=1, transient=False,
              screen=False) as live:
        end = state["next_at"]
        try:
            while dt.datetime.now() < end:
                live.update(dash)
                time.sleep(1)
        except KeyboardInterrupt:
            return


# --------------------------------------------------------------------------- #
# Entrée principale
# --------------------------------------------------------------------------- #
def main() -> int:
    _require_pkgs()
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    import questionary

    console = Console()
    console.print(Panel(
        Text("\n  stockmonitor\n  surveille ton stock, tranquillement\n",
             style="bold cyan"),
        border_style="cyan", padding=(1, 4)))

    cfg = load_config()
    data_dir = cfg.get("common", {}).get("data_dir", "data")
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    # 1. Enseigne
    retailer_key = _pick_retailer()
    if not retailer_key:
        return 1

    # 2. Choix enseigne(s) — build overrides
    overrides: dict = {
        "config": None, "data_dir": data_dir, "notify_cmd": None,
        "verbose": False, "product_ref": None, "product_url": None, "loop": None,
    }

    scanners: list[ScannerBase] = []
    if retailer_key == "all":
        from .cli import _canonical_instances
        scanners = _canonical_instances()
    else:
        cls = REGISTRY[retailer_key]
        scanners = [cls()]

    # 3. Zone (LM uniquement) + produit
    for sc in scanners:
        if sc.CONFIG_KEY == "lm":
            zone_pick = _pick_lm_zone()
            if zone_pick is None:
                return 1
            overrides["zone"], overrides["wide"] = zone_pick
            break

    # Produit : on prend l'URL par défaut du premier scanner concerné.
    target = scanners[0]
    default_url = target.DEFAULT_PRODUCT_URL
    product_url = _pick_product(default_url)
    if product_url is None:
        return 1
    if product_url != default_url:
        overrides["product_url"] = product_url

    # 4. Mode boucle
    loop_pick = _pick_loop()
    if loop_pick is None:
        return 1
    loop_sec, _ = loop_pick
    overrides["loop"] = loop_sec

    # 5. Exécution
    state: dict = {
        "phase": "idle", "retailer": ", ".join(s.RETAILER_NAME for s in scanners),
        "zone": overrides.get("zone", ""), "product_ref": "",
        "index": 0, "total": 0, "label": "", "action": "",
        "stores": {}, "in_stock": 0, "blocked": 0, "completed": True,
        "online": None, "cycle": 1, "next_at": None,
        "scan_started_at": None, "seed_started_at": None,
        "pause_until": None, "warmup_started_at": None,
    }

    cycle = 0
    try:
        while True:
            cycle += 1
            state["cycle"] = cycle
            # En mode "all", on enchaîne les enseignes ; on rebuild un state
            # par enseigne pour la lisibilité.
            for sc in scanners:
                state["retailer"] = sc.RETAILER_NAME
                ns = _build_namespace(overrides, cfg)
                sc.apply_config(ns, cfg)
                Path(ns.data_dir).mkdir(parents=True, exist_ok=True)
                _run_with_live(sc, ns, state)
            if not loop_sec:
                break
            # Petite pause avant le compte à rebours pour laisser lire le final.
            console.print()
            _countdown(state, loop_sec)
    except KeyboardInterrupt:
        console.print("\n[dim]Arrêt demandé.[/]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
