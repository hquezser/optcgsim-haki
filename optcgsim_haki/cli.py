"""Interface en ligne de commande du tracker OPTCGSim."""

from __future__ import annotations

import argparse
import json
import sys

import pathlib

from .analytics import Analytics
from .archetype import ArchetypeModel
from .cardmeta import build_card_meta
from .deckstats import compute_stats, parse_deck_file
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


def cmd_mulligan(args) -> int:
    with Store(args.db) as st:
        a = Analytics(st)
        rows = a.mulligan_by_leader(args.mode)
        print("### Mulligan par leader (garder vs mulligan)")
        for d in rows:
            kw = f"{d['kept_wr']:.0f}%" if d["kept_wr"] is not None else "—"
            mw = f"{d['mull_wr']:.0f}%" if d["mull_wr"] is not None else "—"
            print(f"  {d['leader']:<26} gardé {kw} ({d['kept_n']})  |  "
                  f"mulligan {mw} ({d['mull_n']})")
        base_wr, cards = a.opening_card_impact(leader=args.leader, min_games=args.min_games)
        print(f"\n### Cartes d'ouverture vs baseline ({base_wr:.0f}%) — lift (≥{args.min_games} parties)")
        print("  Meilleures :")
        for d in cards[:8]:
            print(f"    {d['name']:<30} {d['winrate']:5.1f}%  (lift {d['lift']:+.1f}, n={d['n']})")
        print("  Pires :")
        for d in cards[-5:]:
            print(f"    {d['name']:<30} {d['winrate']:5.1f}%  (lift {d['lift']:+.1f}, n={d['n']})")
    return 0


def cmd_archetype(args) -> int:
    with Store(args.db) as st:
        model = ArchetypeModel(st)
        revealed = set(args.revealed or [])
        pred = model.predict(args.leader, revealed)
        if not pred:
            print(f"Aucun historique pour le leader {args.leader}.")
            return 1
        print(f"### Archétype probable — {pred.leader_name} [{pred.leader}]")
        print(f"Basé sur {pred.n_historical} decks adverses historiques.")
        if revealed:
            print(f"Cartes révélées : {len(revealed)} | recouvrement meilleur deck : "
                  f"{pred.nearest_overlap*100:.0f}%")
        print("\nDeck typique (présence sur l'historique) :")
        for c in pred.expected_cards:
            seen = "✓" if c["card_id"] in revealed else " "
            print(f"  [{seen}] {c['name']:<30} {c['presence']:3.0f}%  "
                  f"(~{c['avg_copies']:.1f}x) {c['card_id']}")
        if revealed and pred.unseen_likely:
            print("\nProbablement encore dans le deck (≥50% présence, non vues) :")
            for c in pred.unseen_likely[:10]:
                print(f"  {c['name']:<30} {c['presence']:3.0f}%")
    return 0


def _print_deck_stats(s) -> None:
    lead = f"{s.leader_name or '?'} [{s.leader}]" if s.leader else "?"
    print(f"\n### {s.name}  — Leader: {lead}   ({s.total} cartes, hors leader)")
    if s.unknown:
        print(f"  ⚠ {len(s.unknown)} carte(s) sans données : {', '.join(s.unknown)}")

    # Category (type de carte)
    print("\n  Category")
    for t in ("Character", "Event", "Stage"):
        print(f"    {t:<10} {s.types.get(t, 0)}")

    # Cost (courbe)
    print("\n  Cost")
    mx = max(s.curve.values(), default=1)
    for cost in range(0, (max(s.curve) if s.curve else 0) + 1):
        n = s.curve.get(cost, 0)
        print(f"    {cost}  {n:>2}  {'█' * round(n / mx * 18)}")

    # Counter (valeurs > 0 + total)
    print("\n  Counter")
    for val in sorted(c for c in s.counters if c > 0):
        print(f"    +{val}  {s.counters[val]}")
    print(f"    total  {s.counter_total}")

    # Type (traits / subtypes)
    if s.subtypes:
        print("\n  Type")
        for sub, n in s.subtypes.items():
            print(f"    {sub:<22} {n}")

    print("  Couleurs : " + ", ".join(f"{c} {n}" for c, n in s.colors.items()))


def cmd_watch_decks(args) -> int:
    """Surveille les fichiers de deck et affiche les stats à chaque sauvegarde."""
    import time

    paths = Sources().paths
    meta = build_card_meta(paths, pathlib.Path(args.db + ".cardmeta.json"))
    deck_dir = paths.app_support
    seen = {p: p.stat().st_mtime for p in deck_dir.glob("*.txt")}
    print(f"Surveillance des decks dans {deck_dir}\n(sauvegarde un deck dans OPTCGSim — Ctrl-C pour arrêter)\n")
    try:
        while True:
            for p in deck_dir.glob("*.txt"):
                mt = p.stat().st_mtime
                if seen.get(p) != mt:
                    seen[p] = mt
                    _print_deck_stats(compute_stats(parse_deck_file(p), meta))
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nArrêt.")
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

    pmu = sub.add_parser("mulligan", help="analyse mulligan + impact des cartes d'ouverture")
    pmu.add_argument("--mode", default="all", choices=["all", "ranked", "direct"])
    pmu.add_argument("--leader", default=None, help="filtrer l'impact des cartes par id de leader")
    pmu.add_argument("--min-games", type=int, default=15)
    pmu.set_defaults(func=cmd_mulligan)

    pa = sub.add_parser("archetype", help="prédire le deck adverse d'un leader")
    pa.add_argument("leader", help="id du leader adverse (ex: OP09-001)")
    pa.add_argument("revealed", nargs="*", help="cartes déjà révélées (ids)")
    pa.set_defaults(func=cmd_archetype)

    sub.add_parser("watch-decks",
                   help="afficher les stats d'un deck à chaque sauvegarde (deckbuilding live)"
                   ).set_defaults(func=cmd_watch_decks)

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
