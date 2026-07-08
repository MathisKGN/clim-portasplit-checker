"""ScannerBase — squelette partagé par tous les adapteurs de stock.

Un scan produit une `result` dict standardisée :
    {
      "stores":   {<id>: {id, name, state, restock, url, …}},   # plats
      "completed": bool,           # scan arrivé au bout ?
      "blocked":   int,            # nb erreurs/blocages (0 si non pertinent)
      "extra":     {...},          # champ libre (online Casto, zone LM, …)
    }

Convention `state` des magasins (chaîne) :
    "IN"           dispo (restock candidat)
    "OUT"          indisponible
    "NOT_CARRIED"  magasin ne reference pas le produit
    "UNKNOWN"      statut non lisible (n'alerte pas)

`restock` (bool) : True si candidat restock (= alerte). En pratique équivalent
à state=="IN", mais laisse l'adapteste décider (ex. C&C Drive 2h seul).
"""
from __future__ import annotations

import os
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path

from .common import (
    load_state,
    save_json,
    ts,
    write_csv,
    append_history,
)


class ScannerBase(ABC):
    """Classe abstraite — un adapteur par enseigne.

    Sous-classes à implémenter dans stockmonitor/retailers/*.py.
    Le cycle complet (run -> report -> persist -> alerts) est géré ici.
    """

    # --- Identité de l'enseigne (à surcharger) ----------------------------- #
    RETAILER_NAME: str = "base"            # ex. "Leroy Merlin"
    FILE_PREFIX: str = ""                 # préfixe fichiers (ex. "casto"). "" = retailer.lower()
    ENV_PREFIX: str = ""                  # préfixe env notify (ex. "LM", "CASTO")
    DEFAULT_PRODUCT_REF: str = ""         # identifiant produit par défaut
    DEFAULT_PRODUCT_URL: str = ""         # URL fiche produit (scrap / init)
    HAS_ONLINE_AVAILABILITY: bool = False  # l'enseigne expose-t-elle la dispo en ligne ?

    # Clé de section dans config.toml (ex. "lm", "casto"). Défaut : nom canonique.
    CONFIG_KEY: str = ""

    def __init__(self):
        # Callback temps réel (signature: handler(event_type: str, payload: dict)).
        # Si None, `_emit` ne fait rien (mode silencieux). Le mode interactif
        # (interactive.py) y branche un renderer Rich Live. Le mode CLI legacy
        # y branche un print() quand verbose=True.
        self._event_handler = None

    def set_event_handler(self, handler) -> None:
        """Branche un callback temps réel (cf. interactive.py pour un exemple)."""
        self._event_handler = handler

    def _emit(self, event_type: str, **payload) -> None:
        """Émet un évènement de progression du scan.

        Types émis par les adapètes :
          scan_start    total_seeds, zone, product_ref, product_url
          warmup        phase ('camoufox'|'session'|'done'), detail
          seed_start    index, total, label
          seed_done     index, total, label, found, new, total_stores, stores_added
          seed_blocked  index, total, label, status
          pause         seconds, long   (avant sleep inter-seeds)
          remint        reason
          online        available, home_delivery
          scan_done     total_stores, in_stock, blocked, completed, seeds_used
        """
        if self._event_handler is not None:
            try:
                self._event_handler(event_type, payload)
            except Exception:
                pass

    def _pause(self, args, long: bool = False) -> None:
        """Pause animée entre deux seeds — remplace sleep_between.

        Émet un évènement `pause` AVANT de bloquer, pour que le dashboard
        puisse afficher un compte à rebours pendant le sleep. Le handler
        repose sur le thread de rafraîchissement Rich Live (qui tourne en
        parallèle du sleep bloquant).
        """
        import random as _r
        lo, hi = ((args.max_delay, args.max_delay * 2) if long
                  else (args.min_delay, args.max_delay))
        secs = _r.uniform(lo, hi)
        self._emit("pause", seconds=secs, long=long)
        import time as _t
        _t.sleep(secs)

    @classmethod
    def get_defaults(cls) -> dict:
        """Defaults codés (fallback quand config.toml + CLI ne disent rien).

        Surchargé par les sous-classes pour exposer leurs attributs attendus.
        Toujours inférieur en priorité à config.toml et à la CLI.
        """
        return {}

    # ------------------------------------------------------------------ #
    # Hooks à implémenter
    # ------------------------------------------------------------------ #
    @abstractmethod
    def scan(self, ctx, args) -> dict:
        """Exécute le scan dans le contexte `ctx` (page navigateur ou session).

        Renvoie la `result` dict standardisée (voir docstring module).
        """

    @abstractmethod
    def open_context(self, args):
        """Ouvre le transport (Camoufox context, requests.Session, …).

        Doit être un context manager (supporte `with ... as ctx:`).
        """

    @abstractmethod
    def add_arguments(self, parser) -> None:
        """Ajoute les arguments CLI spécifiques à l'enseigne (--product-url, …)."""

    @abstractmethod
    def store_url(self, store: dict) -> str:
        """URL publique pour voir le stock de ce magasin (notify / report)."""

    # Pages d'output : un classement par magasin dans l'ordre voulu.
    def sort_stores(self, stores: list[dict]) -> list[dict]:
        """Ordre d'affichage des magasins dans le report/CSV. Defaut: par nom."""
        return sorted(stores, key=lambda x: x.get("name", ""))

    def csv_header(self) -> list[str]:
        return ["id", "magasin", "etat", "statut_texte", "distance_km", "url"]

    def csv_row(self, store: dict) -> list:
        return [
            store.get("id") or store.get("slug", ""),
            store.get("name", ""),
            store.get("state", ""),
            store.get("status_text", ""),
            store.get("distance_km", ""),
            self.store_url(store),
        ]

    def extra_history_fields(self, result: dict) -> dict:
        """Champs supplémentaires à inscrire dans history.jsonl (override)."""
        return {}

    # ------------------------------------------------------------------ #
    # Identité / chemins
    # ------------------------------------------------------------------ #
    @property
    def prefix(self) -> str:
        return self.FILE_PREFIX or self.RETAILER_NAME.lower().replace(" ", "_")

    def env_name(self, suffix: str) -> str:
        return f"{self.ENV_PREFIX}_{suffix}" if self.ENV_PREFIX else suffix

    def paths(self, args):
        d = Path(args.data_dir)
        return {
            "last_run_json": d / f"{self.prefix}_last_run.json",
            "last_run_csv":  d / f"{self.prefix}_last_run.csv",
            "history":       d / f"{self.prefix}_history.jsonl",
            "state":         d / f"{self.prefix}_state.json",
            "restock":       d / f"{self.prefix}_RESTOCK.json",
        }

    # ------------------------------------------------------------------ #
    # Report
    # ------------------------------------------------------------------ #
    def report(self, result: dict, args, fresh_ids: set[str] | None = None) -> list[dict]:
        stores = result["stores"]
        in_stock = [s for s in stores.values() if s.get("restock")]
        not_carried = [s for s in stores.values() if s.get("state") == "NOT_CARRIED"]
        unknown = [s for s in stores.values() if s.get("state") == "UNKNOWN"]
        completed = result.get("completed", True)
        blocked = result.get("blocked", 0)
        verbose = getattr(args, "verbose", False)
        fresh_ids = fresh_ids or set()

        # Ligne résumé : « 93 magasins · 1 en stock · 3 non réf. · ⚠ 2 blocages »
        parts = [f"{len(stores)} magasins", f"{len(in_stock)} en stock"]
        if not_carried:
            parts.append(f"{len(not_carried)} non réf.")
        if unknown:
            parts.append(f"{len(unknown)} ?")
        if blocked:
            parts.append(f"⚠ {blocked} blocage{'s' if blocked > 1 else ''}")
        if not completed and blocked == 0:
            parts.append("scan incomplet")
        print(f"  {' · '.join(parts)}")

        # Dispo en ligne (optionnelle, ex. Casto)
        online = result.get("extra", {}).get("online")
        if online:
            avail = online.get("home_delivery") or online.get("error") or "n/a"
            tag = "commandable" if online.get("available") else "rupture"
            print(f"  🌐 en ligne : {avail} ({tag})")

        # Restocks : liste compacte (★ = nouveau depuis le dernier run).
        if in_stock:
            print()
            print("  ▲ RESTOCK")
            for s in self.sort_stores(in_stock):
                sid = self._store_id(s)
                mark = " ★" if sid in fresh_ids else ""
                print(f"    {s['name']} — {self._store_qty_label(s)}{mark}")
                print(f"      {self.store_url(s)}")
        elif verbose and unknown:
            print("\n  ❔ Statuts non reconnus :")
            for s in unknown:
                print(f"    {s['name']} — state={s.get('state')} "
                      f"text={s.get('status_text','')!r}")

        return in_stock

    def _store_qty_label(self, store: dict) -> str:
        """Libellé court entre crochets pour l'affichage restock."""
        if store.get("quantity") is not None:
            return f"{store['quantity']} pc"
        return store.get("stock_level") or store.get("status_text") or "?"

    # ------------------------------------------------------------------ #
    # Persistance
    # ------------------------------------------------------------------ #
    def persist_outputs(self, result: dict, args):
        stamp = ts()
        p = self.paths(args)
        stores = list(result["stores"].values())

        save_json(p["last_run_json"], {
            "timestamp": stamp,
            "retailer": self.RETAILER_NAME,
            "product_ref": getattr(args, "product_ref", None),
            **result,
        })

        ordered = self.sort_stores(stores)
        write_csv(p["last_run_csv"], self.csv_header(),
                  [self.csv_row(s) for s in ordered])

        history_record = {
            "ts": stamp,
            "in_stock": [self._store_id(s) for s in stores if s.get("restock")],
            "total": len(stores),
            "blocked": result.get("blocked", 0),
            "completed": result.get("completed", True),
            **self.extra_history_fields(result),
        }
        append_history(p["history"], history_record)

    @staticmethod
    def _store_id(store: dict) -> str:
        return store.get("id") or store.get("slug", "")

    # ------------------------------------------------------------------ #
    # Alertes
    # ------------------------------------------------------------------ #
    def handle_alerts(self, in_stock: list[dict], result: dict, args):
        """N'alerte que pour les nouveaux restocks (anti-spam via state.json).

        Si le scan est incomplet, on NE purge PAS les anciens restocks signalés
        (on les garde en union) pour ne pas respammer au prochain scan complet.
        """
        completed = result.get("completed", True)
        p = self.paths(args)
        prev = load_state(p["state"])
        prev_in = set(prev.get("in_stock", []))

        prev_online = bool(prev.get("online_available"))
        now_in = {self._store_id(s) for s in in_stock}
        online = result.get("extra", {}).get("online", {})
        online_now = bool(online.get("available")) if online else False

        if getattr(args, "alert_always", False):
            # Mode simple : on alerte à chaque scan tant qu'il y a du stock,
            # même s'il a déjà été signalé (pas d'anti-spam).
            fresh_stores = list(in_stock)
            fresh_online = online_now
        else:
            fresh_stores = [s for s in in_stock if self._store_id(s) not in prev_in]
            fresh_online = online_now and not prev_online

        persisted_in = now_in if completed else (prev_in | now_in)
        state_record = {
            "in_stock": sorted(persisted_in),
            "updated": ts(),
            "last_scan_completed": completed,
        }
        if online:
            state_record["online_available"] = online_now

        save_json(p["state"], state_record)

        if fresh_stores or fresh_online:
            self.notify(fresh_stores, fresh_online, result, args)
        return fresh_stores, fresh_online

    def notify(self, fresh_stores: list[dict], fresh_online: bool,
               result: dict, args):
        """Hook d'alerte : RESTOCK.json + --notify-cmd.

        L'affichage console est géré par report() (liste compacte ▲ RESTOCK).
        Ici on persiste + on déclenche le hook externe (Telegram, …).
        Variables env : <ENV_PREFIX>_MESSAGE / _STORES / _PRODUCT_REF / …
        """
        lines = []
        if fresh_online:
            online = result.get("extra", {}).get("online", {})
            lines.append(f"EN LIGNE de nouveau commandable "
                         f"({online.get('home_delivery')})")
        for s in fresh_stores:
            lines.append(f"{s['name']} — {self._store_qty_label(s)}\n  {self.store_url(s)}")

        ref = getattr(args, "product_ref", "") or getattr(args, "product_url", "")
        msg = (f"RESTOCK {self.RETAILER_NAME} ({ref}) :\n" + "\n".join(lines))

        save_json(self.paths(args)["restock"], {
            "ts": ts(),
            "retailer": self.RETAILER_NAME,
            "product_ref": getattr(args, "product_ref", None),
            "online": result.get("extra", {}).get("online"),
            "fresh_online": fresh_online,
            "stores": fresh_stores,
        })

        if getattr(args, "notify_cmd", None):
            env = {**os.environ,
                   self.env_name("MESSAGE"): msg,
                   self.env_name("STORES"): _json(fresh_stores)}
            ref_val = getattr(args, "product_ref", None)
            if ref_val:
                env[self.env_name("PRODUCT_REF")] = ref_val
            try:
                subprocess.run(args.notify_cmd, shell=True, check=False, env=env)
            except Exception as e:
                print(f"  notify-cmd a échoué : {e}")

    # ------------------------------------------------------------------ #
    # Cycle / main
    # ------------------------------------------------------------------ #
    def run_cycle(self, ctx, args) -> dict:
        """Un cycle : scan -> alertes (state + external hook) -> affichage."""
        result = self.scan(ctx, args)
        print(f"[{ts()}] {self.RETAILER_NAME}")
        fresh_stores, fresh_online = self.handle_alerts(
            [s for s in result["stores"].values() if s.get("restock")],
            result, args)
        fresh_ids = {self._store_id(s) for s in fresh_stores}
        self.report(result, args, fresh_ids)
        if fresh_stores or fresh_online:
            tail = " + en ligne" if fresh_online else ""
            print(f"  → {len(fresh_stores)} nouvelle alerte{tail}")
        self.persist_outputs(result, args)
        return result

    def run_once(self, args) -> dict:
        with self.open_context(args) as ctx:
            self.prepare_context(ctx, args)
            return self.run_cycle(ctx, args)

    def prepare_context(self, ctx, args) -> None:
        """Hook optionnel : setup page navigateur, route, etc. No-op par défaut."""
        pass

    def apply_config(self, args, cfg: dict) -> None:
        """Resout tous les attributs attendus dans `args`.

        Priorité : CLI (déjà posée si non-None) > config.toml > get_defaults().
        À appeler une fois avant run_cycle / _run_loop.
        """
        from .config import merge_config_into_args
        # 1/ config.toml (surclasse les defaults codés, pas la CLI)
        merge_config_into_args(args, cfg, self.CONFIG_KEY or self.prefix)
        # 2/ defaults codés (priorité basse)
        for k, v in self.get_defaults().items():
            if getattr(args, k, None) is None:
                setattr(args, k, v)
        # 3/ substitue les placeholders produit si config/defaults n'ont rien passé
        if getattr(args, "product_ref", None) is None:
            args.product_ref = self.DEFAULT_PRODUCT_REF
        if getattr(args, "product_url", None) is None:
            args.product_url = self.DEFAULT_PRODUCT_URL

    def run_main(self, args, cfg: dict | None = None):
        """Boucle principale : un seul run ou auto-boucle (--loop).

        `cfg` est la config chargée (config.toml). Appliquée avant tout.
        """
        from .config import load_config
        cfg = cfg if cfg is not None else load_config(getattr(args, "config", None))
        self.apply_config(args, cfg)

        Path(args.data_dir).mkdir(parents=True, exist_ok=True)

        if getattr(args, "loop", 0) and args.loop > 0:
            print(f"[{ts()}] {self.RETAILER_NAME} · mode boucle toutes les {args.loop}s "
                  f"(Ctrl-C pour arrêter)")
            self._run_loop(args)
        else:
            self.run_once(args)

    def _run_loop(self, args):
        """Boucle : réutilise le transport (navigateur/session) entre les cycles
        si possible. Recrée en cas d'erreur fatale (contexte mort).

        `open_context` peut échouer au démarrage ou en cours de boucle ; on
        retente à chaque cycle plutôt que de retryer indéfiniment contre un
        contexte mort. Ctrl-C interrompt proprement à tout moment.
        """
        import random as _r
        ctx = None
        try:
            while True:
                try:
                    if ctx is None:
                        ctx_cm = self.open_context(args)
                        ctx = ctx_cm.__enter__()
                        try:
                            self.prepare_context(ctx, args)
                        except Exception:
                            ctx_cm.__exit__(None, None, None)
                            ctx = None
                            raise
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"[{ts()}] Échec open_context : {e!r}, retry au prochain cycle…")
                    ctx = None
                    time.sleep(args.loop + _r.uniform(0, args.loop * 0.15))
                    continue
                try:
                    self.run_cycle(ctx, args)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"[{ts()}] Erreur de cycle : {e!r}, contexte recréé au prochain cycle.")
                    # Le contexte est possiblement mort : on le ferme et on
                    # force la réouverture au prochain tour.
                    try:
                        ctx_cm.__exit__(None, None, None)
                    except Exception:
                        pass
                    ctx = None
                time.sleep(args.loop + _r.uniform(0, args.loop * 0.15))
        except KeyboardInterrupt:
            print("\nArrêt demandé.")
            if ctx is not None:
                try:
                    ctx_cm.__exit__(None, None, None)
                except Exception:
                    pass

def _json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
