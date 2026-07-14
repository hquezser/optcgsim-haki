"""Interface en ligne de commande du tracker OPTCGSim."""

from __future__ import annotations

import argparse
import json
import sys

import pathlib

from .carddb import CardDB
from .cardnames import load_card_names
from .db.store import Store
from .ingest import ingest_all
from .sources import Sources

DEFAULT_DB = "optcg.db"


def cmd_backfill(args) -> int:
    sources = Sources()
    print("Lecture des sources et parsing…")
    recs = ingest_all(sources)
    with Store(args.db) as st:
        for r in recs:
            st.upsert_match(r)
        # 1) Base COMPLÈTE de noms depuis l'asset Unity du jeu (deck builder), avec cache.
        cache = pathlib.Path(args.db + ".cardnames.json")
        full_names = load_card_names(sources.paths.resources_assets, cache)
        if full_names:
            st.import_card_names(full_names)
            print(f"Base de cartes : {len(full_names)} noms extraits du jeu.")
        # 2) Complète couleur/coût/power via les Cards/*.json locaux.
        carddb = CardDB(sources)
        for cid in st.all_card_ids():
            st.upsert_card_meta(carddb.meta(cid))
        st.conn.commit()
        total = st.query("SELECT COUNT(*) c FROM matches")[0]["c"]
        named = st.query("SELECT COUNT(*) c FROM cards WHERE name IS NOT NULL")[0]["c"]
        allc = st.query("SELECT COUNT(*) c FROM cards")[0]["c"]
    print(f"OK — {len(recs)} matchs traités, {total} en base ({args.db}).")
    print(f"Cartes nommées : {named}/{allc}.")
    return 0


def cmd_import_cards(args) -> int:
    """Importe un référentiel externe de noms de cartes (JSON {id: name} ou CSV id,name)."""
    import csv
    import pathlib

    p = pathlib.Path(args.file)
    mapping: dict[str, str] = {}
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text())
        if isinstance(data, dict):
            mapping = {k: str(v) for k, v in data.items()}
        elif isinstance(data, list):  # [{"id":..,"name":..}, ...]
            for row in data:
                if isinstance(row, dict) and row.get("id"):
                    mapping[row["id"]] = str(row.get("name", ""))
    else:  # CSV id,name
        with p.open() as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    mapping[row[0].strip()] = row[1].strip()
    with Store(args.db) as st:
        n = st.import_card_names(mapping)
    print(f"Importé {n} noms de cartes depuis {p}.")
    return 0


def cmd_watch(args) -> int:
    from .watcher import run_watch
    return run_watch(db_path=args.db, reveal_all=args.reveal_all)


def cmd_dashboard(args) -> int:
    from .api.server import run_api
    return run_api(db_path=args.db, port=args.port, reveal_all=args.reveal_all)


def cmd_overlay(args) -> int:
    # run_overlay gère lui-même l'absence de l'extra (pywebview/pyobjc) avec un message clair.
    from .overlay.app import run_overlay
    return run_overlay(db_path=args.db, port=args.port, owner=args.owner,
                       opacity=args.opacity, autostart_server=not args.no_server,
                       reveal_all=args.reveal_all, advanced=args.advanced,
                       zone=args.zone, hud_debug=args.hud_debug)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="optcgsim-haki", description="Tracker de stats OPTCGSim.")
    p.add_argument("--db", default=DEFAULT_DB, help="chemin de la base SQLite")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("backfill", help="importer tout l'historique local").set_defaults(func=cmd_backfill)

    pic = sub.add_parser("import-cards", help="importer un référentiel de noms (JSON/CSV)")
    pic.add_argument("file")
    pic.set_defaults(func=cmd_import_cards)

    pw = sub.add_parser("watch", help="suivi live d'une partie en cours (terminal)")
    pw.add_argument("--reveal-all", action="store_true",
                    help="⚠️ révèle l'info cachée de l'adversaire (triche en partie classée)")
    pw.set_defaults(func=cmd_watch)

    pd = sub.add_parser("dashboard", help="dashboard live web (API FastAPI + frontend Next.js)")
    pd.add_argument("--port", type=int, default=8765, help="port de l'API FastAPI")
    pd.add_argument("--reveal-all", action="store_true",
                    help="⚠️ révèle l'info cachée de l'adversaire (triche en partie classée)")
    pd.set_defaults(func=cmd_dashboard)

    po = sub.add_parser("overlay",
                        help="overlay HUD transparent au-dessus du jeu (macOS ; extra [overlay])")
    po.add_argument("--port", type=int, default=8765, help="port de l'API FastAPI")
    po.add_argument("--owner", default="OPTCGSim", help="nom de l'app dont suivre la fenêtre")
    po.add_argument("--opacity", type=float, default=1.0, help="opacité de l'overlay (0.0–1.0)")
    po.add_argument("--no-server", action="store_true",
                    help="ne pas démarrer l'API (si un dashboard tourne déjà sur --port)")
    po.add_argument("--advanced", action="store_true",
                    help="réactive les panneaux INFÉRÉS (lethal offensif, menaces…) ; "
                         "par défaut le HUD n'affiche que l'exact/public")
    po.add_argument("--reveal-all", action="store_true",
                    help="⚠️ révèle l'info cachée de l'adversaire (triche en partie classée)")
    po.add_argument("--zone", default=None, metavar="x:6,y:30,w:20,h:50",
                    help="zone du HUD en %% de la fenêtre du jeu (défaut : bande du chat)")
    po.add_argument("--hud-debug", action="store_true",
                    help="dessine le contour de la zone du HUD (pour la caler)")
    po.set_defaults(func=cmd_overlay)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
