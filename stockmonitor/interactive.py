"""Mode interactif — `python -m stockmonitor` sans args.

Prompts flèches (questionary) + dashboard temps réel (Rich Live) qui se met
à jour à chaque seed scanné. Aucun argument à retenir : on demande.

Flow
----
1. Bannière de bienvenue.
2. Choix enseigne.
3. Pour LM : code postal + rayon de scan.
4. Produit par défaut.
5. Mode : one-shot ou boucle (intervalle).
6. Alerte Telegram : garder / configurer / désactiver.
7. Lancement : dashboard Rich Live qui consomme les events émis par les
   scanners et rend les magasins au fur et à mesure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import stat
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import ScannerBase
from .config import find_config_path, load_config
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
            questionary.Choice("ManoMano", value="manomano"),
            questionary.Choice("Darty", value="darty"),
            questionary.Choice("Toutes (en séquence)", value="all"),
        ],
        use_arrow_keys=True,
    ).ask()


def _prefs_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "interactive_prefs.json"


def _load_last_postcode(data_dir: str | Path) -> str | None:
    path = _prefs_path(data_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    cp = str(data.get("postcode", "")).strip()
    if cp.isdigit() and len(cp) == 5:
        return cp
    return None


def _save_last_postcode(data_dir: str | Path, postcode: str) -> None:
    path = _prefs_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"postcode": postcode.strip()}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _pick_lm_area(data_dir: str | Path) -> tuple[list, str] | None:
    """Demande un code postal + un rayon, calcule les seeds à la volée.

    Renvoie (seeds, zone_label) où seeds est une liste de (label, lat, lon).
    Renvoie None si l'utilisateur annule.
    """
    import questionary
    from rich.console import Console
    from .seeds_dynamic import geocode_cp, compute_seeds

    console = Console()
    default_cp = _load_last_postcode(data_dir) or ""

    while True:
        cp = questionary.text(
            "Ton code postal (autour duquel scanner) ?",
            default=default_cp,
            validate=lambda s: (s.strip().isdigit() and len(s.strip()) == 5)
            or "Code postal invalide (5 chiffres, ex. 59000)",
        ).ask()
        if cp is None:
            return None
        cp = cp.strip()

        radius = questionary.text(
            "Rayon de scan en km (entre 5 et 700) ?",
            default="",
            validate=lambda s: (s.strip().isdigit() and 5 <= int(s.strip()) <= 700)
            or "Entre un nombre entre 5 et 700",
        ).ask()
        if radius is None:
            return None
        radius_km = int(radius.strip())

        console.print(f"  [dim]Géolocalisation du {cp}…[/]")
        center = geocode_cp(cp)
        if center is None:
            console.print("  [red]Code postal introuvable (ou pas de réseau).[/] "
                          "Réessaie.")
            default_cp = cp
            continue
        _save_last_postcode(data_dir, cp)
        default_cp = cp

        console.print("  [dim]Chargement des magasins Leroy Merlin…[/]")
        try:
            seeds, n_stores = compute_seeds(center, radius_km)
        except Exception as e:
            console.print(
                "  [red]Impossible de charger la liste des magasins Leroy Merlin.[/] "
                f"[dim]{e}[/]\n"
                "  Vérifie ta connexion puis relance le programme."
            )
            return None
        if not seeds:
            console.print(
                f"  [yellow]Aucun magasin Leroy Merlin dans un rayon de "
                f"{radius_km} km.[/] Élargis le rayon.")
            continue

        label = f"{cp} · {radius_km} km ({n_stores} magasins)"
        console.print(
            f"  [green]✓[/] {n_stores} magasins couverts par "
            f"[bold]{len(seeds)} point(s)[/] de scan.")
        return seeds, label


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


def _quote_sh(value: str) -> str:
    """Quote POSIX simple pour écrire des secrets dans le hook local."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _telegram_script_path(data_dir: str) -> Path:
    base = Path(data_dir)
    if not base.is_absolute():
        base = Path.cwd() / base
    return base.resolve() / "telegram_notify.sh"


def _telegram_notify_cmd(data_dir: str) -> str | None:
    script = _telegram_script_path(data_dir)
    if script.exists():
        return str(script)
    return None


def _write_telegram_hook(data_dir: str, token: str, chat_id: str) -> Path:
    """Écrit un hook Telegram local, privé, consommé par ScannerBase.notify()."""
    script = _telegram_script_path(data_dir)
    script.parent.mkdir(parents=True, exist_ok=True)
    content = f"""#!/usr/bin/env bash
set -u

TELEGRAM_BOT_TOKEN={_quote_sh(token)}
TELEGRAM_CHAT_ID={_quote_sh(chat_id)}

MESSAGE="${{LM_MESSAGE:-${{CASTO_MESSAGE:-${{MANOMANO_MESSAGE:-${{DARTY_MESSAGE:-${{WEB_MESSAGE:-}}}}}}}}}}"

if [ -z "${{MESSAGE}}" ]; then
  exit 0
fi

curl -sS -X POST "https://api.telegram.org/bot${{TELEGRAM_BOT_TOKEN}}/sendMessage" \\
  --data-urlencode "chat_id=${{TELEGRAM_CHAT_ID}}" \\
  --data-urlencode "text=${{MESSAGE}}" >/dev/null
"""
    script.write_text(content, encoding="utf-8")
    script.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return script


def _send_telegram_test(token: str, chat_id: str) -> tuple[bool, str]:
    data = urlencode({
        "chat_id": chat_id,
        "text": "Test stockmonitor : l'alerte Telegram est configurée.",
    }).encode("utf-8")
    req = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    try:
        with urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return False, str(e)
    if payload.get("ok"):
        return True, "Message de test envoyé."
    return False, payload.get("description", "Réponse Telegram invalide.")


def _save_notify_cmd_to_config(notify_cmd: str) -> bool:
    """Persiste common.notify_cmd dans config.toml sans dépendance d'écriture TOML."""
    path = find_config_path()
    if not path:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False

    toml_notify_cmd = notify_cmd.replace("\\", "\\\\").replace('"', '\\"')
    lines = text.splitlines()
    out: list[str] = []
    in_common = False
    common_seen = False
    written = False

    for line in lines:
        section = re.match(r"\s*\[([^\]]+)\]\s*$", line)
        if section:
            if in_common and not written:
                out.append(f'notify_cmd  = "{toml_notify_cmd}"')
                written = True
            in_common = section.group(1).strip() == "common"
            common_seen = common_seen or in_common
            out.append(line)
            continue

        if in_common and re.match(r"\s*notify_cmd\s*=", line):
            out.append(f'notify_cmd  = "{toml_notify_cmd}"')
            written = True
            continue
        out.append(line)

    if in_common and not written:
        out.append(f'notify_cmd  = "{toml_notify_cmd}"')
        written = True
    if not common_seen:
        if out and out[-1].strip():
            out.append("")
        out.extend(["[common]", f'notify_cmd  = "{toml_notify_cmd}"'])
        written = True

    if not written:
        return False
    try:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        return False
    return True


def _pick_telegram_alert(data_dir: str, cfg: dict) -> str | None:
    """Configure l'alerte Telegram depuis le TUI et renvoie notify_cmd."""
    import questionary
    from rich.console import Console

    console = Console()
    existing = _telegram_notify_cmd(data_dir)
    configured = existing or (cfg.get("common", {}) or {}).get("notify_cmd")
    choices = []
    if configured:
        choices.append(questionary.Choice("Garder l'alerte déjà configurée",
                                          value="keep"))
    choices.extend([
        questionary.Choice("Configurer Telegram maintenant", value="setup"),
        questionary.Choice("Pas d'alerte Telegram", value="none"),
    ])
    mode = questionary.select(
        "Alerte quand un nouveau stock apparaît ?",
        choices=choices,
        use_arrow_keys=True,
    ).ask()
    if mode is None:
        return None
    if mode == "none":
        return ""
    if mode == "keep":
        return str(configured)

    console.print("  [dim]Crée un bot avec @BotFather, puis récupère ton chat id "
                  "avec @userinfobot.[/]")
    token = questionary.password(
        "Token du bot Telegram :",
        validate=lambda s: bool(s.strip()) or "Token requis",
    ).ask()
    if token is None:
        return None
    chat_id = questionary.text(
        "Chat ID Telegram :",
        validate=lambda s: bool(s.strip()) or "Chat ID requis",
    ).ask()
    if chat_id is None:
        return None

    script = _write_telegram_hook(data_dir, token.strip(), chat_id.strip())
    console.print(f"  [green]✓[/] Hook Telegram créé : [bold]{script}[/]")

    test = questionary.confirm("Envoyer un message de test ?", default=True).ask()
    if test:
        ok, detail = _send_telegram_test(token.strip(), chat_id.strip())
        style = "green" if ok else "yellow"
        console.print(f"  [{style}]{detail}[/]")

    save = questionary.confirm(
        "Sauvegarder cette alerte pour les prochains lancements ?",
        default=True,
    ).ask()
    if save:
        if _save_notify_cmd_to_config(str(script)):
            console.print("  [green]✓[/] config.toml mis à jour.")
        else:
            console.print("  [yellow]Impossible de mettre à jour config.toml ; "
                          "l'alerte reste active pour ce lancement.[/]")
    return str(script)


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
            detail = (st.get("status_text") or st.get("stock_level")
                      or st.get("cc_message") or "")
            qty = st.get("quantity")
            if qty is not None:
                detail = f"{qty} pc · {detail}".strip(" ·")
            table.add_row(
                name,
                Text(icon, style=style),
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
        current_idx = s.get("current_index", idx)
        total = s.get("total", 0)
        label = s.get("label", "")
        action = s.get("action", "")
        t = Text()
        t.append(f"  {action} " if action else "  Scan ")
        if total:
            t.append(f"{current_idx}/{total}", style="bold cyan")
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
            state["current_index"] = 0
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
            state["current_index"] = payload.get(
                "index", state.get("current_index", state.get("index", 0)))
            state["total"] = payload.get("total", state.get("total", 0))
            state["label"] = payload.get("label", "")
            state["action"] = "Point"
            state["seed_started_at"] = dt.datetime.now()
            state["pause_until"] = None
        elif event_type == "seed_done":
            state["phase"] = "scanning"
            state["index"] = payload.get("index", state.get("index", 0))
            state["current_index"] = state["index"]
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
            state["index"] = payload.get("index", state.get("index", 0))
            state["current_index"] = state["index"]
            state["total"] = payload.get("total", state.get("total", 0))
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
            "product_url", "verbose", "zone", "wide",
            "custom_seeds", "zone_label")
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
    state["current_index"] = 0
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

    # 3. Zone (LM uniquement)
    for sc in scanners:
        if sc.CONFIG_KEY == "lm":
            area = _pick_lm_area(data_dir)
            if area is None:
                return 1
            overrides["custom_seeds"], overrides["zone_label"] = area
            overrides["zone"] = area[1]
            break

    # 4. Mode boucle
    loop_pick = _pick_loop()
    if loop_pick is None:
        return 1
    loop_sec, _ = loop_pick
    overrides["loop"] = loop_sec

    # 5. Alerte Telegram
    notify_cmd = _pick_telegram_alert(data_dir, cfg)
    if notify_cmd is None:
        return 1
    overrides["notify_cmd"] = notify_cmd

    # 6. Exécution
    state: dict = {
        "phase": "idle", "retailer": ", ".join(s.RETAILER_NAME for s in scanners),
        "zone": overrides.get("zone", ""), "product_ref": "",
        "index": 0, "current_index": 0, "total": 0, "label": "", "action": "",
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
