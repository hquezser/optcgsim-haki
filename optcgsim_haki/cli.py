"""Interface en ligne de commande du tracker OPTCGSim."""

from __future__ import annotations

import argparse
import json
import sys

import pathlib

from .analytics import Analytics, sparkline
from .archetype import ArchetypeModel
from .cardmeta import build_card_meta
from .deckstats import compute_stats, parse_deck_file
from .meta import build_meta_timeline
from .carddb import CardDB
from .cardnames import load_card_names
from .db.store import Store
from .ingest import ingest_all
from .sources import Sources
from .stats import Row, Stats

DEFAULT_DB = "optcg.db"


def _print_rows(title: str, rows: list[Row], limit: int | None = None) -> None:
    print(f"\n== {title} ==")
    if not rows:
        print("  (aucune donnée)")
        return
    if limit:
        rows = rows[:limit]
    for r in rows:
        bar = "█" * round(r.winrate / 5)
        print(f"  {r.label:<34} {r.winrate:5.1f}%  ({r.wins}-{r.losses})  {bar}")


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


def cmd_stats(args) -> int:
    with Store(args.db) as st:
        stats = Stats(st)
        mode = args.mode
        ov = stats.overall(mode)
        scope = "tous modes" if mode == "all" else mode
        print(f"\n### Statistiques ({scope}) — {ov.wins}-{ov.losses}  "
              f"({ov.winrate:.1f}% sur {ov.total} parties décisives)")
        dur = stats.avg_duration(mode)
        if dur:
            print(f"Durée moyenne : {dur/60:.1f} min")
        _print_rows("Par leader (≥5 parties)", stats.by_my_leader(mode, having_min=5), limit=15)
        _print_rows("Par deck (≥5 parties)", stats.by_my_deck(mode, having_min=5), limit=20)
        _print_rows("Par matchup (≥3 parties)", stats.by_matchup(mode, having_min=3), limit=15)
        _print_rows("Premier / Second", stats.by_turn_order(mode))
        _print_rows("Mulligan", stats.by_mulligan(mode))
    return 0


def cmd_show(args) -> int:
    with Store(args.db) as st:
        rows = st.query("SELECT * FROM matches WHERE id LIKE ?", (args.match_id + "%",))
        if not rows:
            print(f"Aucun match avec id ~ {args.match_id}")
            return 1
        m = rows[0]
        name = lambda c: st.card_name(c) if c else "?"
        print(f"\n=== Match {m['id']} ===")
        print(f"  {m['played_at']}  | {m['mode']} | {m['format']} ({m['format_confidence']})")
        print(f"  {m['me']} [{name(m['my_leader'])}]  vs  {m['opponent']} [{name(m['opp_leader'])}]")
        order = "premier" if m["i_went_first"] == 1 else ("second" if m["i_went_first"] == 0 else "?")
        print(f"  Ordre : {order} | Résultat : {m['result']} ({m['win_reason']})"
              f"{' | durée %.0fs' % m['duration_s'] if m['duration_s'] else ''}")
        if m["my_rating"] is not None:
            print(f"  Rating : {m['my_rating']:.1f} (Δ {m['rating_delta']:+.1f})")

        for side, who in (("me", m["me"]), ("opp", m["opponent"])):
            oh = st.query(
                "SELECT card_id, kept FROM opening_hands WHERE match_id=? AND side=? ORDER BY position",
                (m["id"], side))
            if oh:
                kept = "gardée" if oh[0]["kept"] == 1 else ("mulligan" if oh[0]["kept"] == 0 else "?")
                cards = ", ".join(name(r["card_id"]) for r in oh)
                print(f"  Main {who} ({kept}) : {cards}")

        snaps = st.query(
            "SELECT turn, side, hand_count, board_ids, life, deck_remaining FROM turn_snapshots "
            "WHERE match_id=? AND side='me' ORDER BY idx", (m["id"],))
        if snaps:
            print("  Évolution (moi) :")
            for s in snaps:
                board = len(json.loads(s["board_ids"]))
                deck = s["deck_remaining"] if s["deck_remaining"] is not None else "?"
                print(f"    T{s['turn']}: main={s['hand_count']} deck={deck} "
                      f"board={board} life={s['life']}")
    return 0


def cmd_matchups(args) -> int:
    with Store(args.db) as st:
        matrix = Analytics(st).matchup_matrix(args.mode, args.min_games)
        if not matrix:
            print("Pas assez de données.")
            return 0
        for leader in sorted(matrix, key=lambda k: -sum(c.total for c in matrix[k])):
            cells = matrix[leader]
            tot_w = sum(c.wins for c in cells)
            tot_l = sum(c.losses for c in cells)
            print(f"\n### {leader}  ({tot_w}-{tot_l})")
            for c in cells:
                flag = "✓" if c.winrate >= 50 else "✗"
                label = f"{c.opp_name} [{c.opp_leader}]"
                print(f"  {flag} vs {label:<34} {c.winrate:5.1f}%  ({c.wins}-{c.losses})")
    return 0


def cmd_elo(args) -> int:
    with Store(args.db) as st:
        curve = Analytics(st).elo_curve(args.leader)
        if not curve:
            print("Aucune donnée de rating (parties classées requises).")
            return 0
        vals = [r for _, r in curve]
        print(f"Rating (parties classées) : {len(vals)} points")
        print(f"  début {vals[0]:.0f} → actuel {vals[-1]:.0f}  "
              f"(min {min(vals):.0f}, max {max(vals):.0f}, pic Δ {max(vals)-vals[0]:+.0f})")
        print("  " + sparkline(vals))
    return 0


def cmd_streaks(args) -> int:
    with Store(args.db) as st:
        a = Analytics(st)
        s = a.streaks(args.mode)
        kind = {"win": "victoires", "loss": "défaites", None: "—"}[s["current"][0]]
        print(f"Séries ({args.mode}) sur {s['total']} parties :")
        print(f"  meilleure série victoires : {s['best_win_streak']}")
        print(f"  pire série défaites       : {s['best_loss_streak']}")
        print(f"  série en cours            : {s['current'][1]} {kind}")
        days = a.by_day(args.mode)
        if days:
            print("\nPar jour (10 derniers) :")
            for d, w, l in days[-10:]:
                wr = 100 * w / (w + l) if (w + l) else 0
                print(f"  {d}  {w}-{l}  ({wr:.0f}%)  {'█' * w}{'░' * l}")
        cu = a.counter_usage(args.mode)
        if cu:
            print(f"\nCounters joués (parties loggées, n={cu['n_matches']}) :")
            print(f"  moyenne {cu['avg_counters']:.1f}/partie  |  "
                  f"victoires {cu['avg_in_wins']:.1f}  vs  défaites {cu['avg_in_losses']:.1f}")
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


def _deck_dir():
    return Sources().paths.app_support


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


def cmd_decks(args) -> int:
    meta = build_card_meta(Sources().paths, pathlib.Path(args.db + ".cardmeta.json"))
    decks = sorted(_deck_dir().glob("*.txt"))
    if not decks:
        print("Aucun deck trouvé.")
        return 0
    print(f"{len(decks)} decks :")
    for p in decks:
        s = compute_stats(parse_deck_file(p), meta)
        print(f"  {s.name:<26} {s.leader_name or s.leader or '?':<18} "
              f"{s.total} cartes | counter +1k×{s.counter_1000} +2k×{s.counter_2000}")
    return 0


def cmd_deck(args) -> int:
    meta = build_card_meta(Sources().paths, pathlib.Path(args.db + ".cardmeta.json"))
    matches = [p for p in _deck_dir().glob("*.txt") if args.name.lower() in p.stem.lower()]
    if not matches:
        print(f"Aucun deck correspondant à « {args.name} ».")
        return 1
    for p in matches:
        _print_deck_stats(compute_stats(parse_deck_file(p), meta))
    return 0


def cmd_meta(args) -> int:
    timeline = build_meta_timeline(Sources().paths, pathlib.Path(args.db + ".metas.json"))
    if not timeline:
        print("Impossible de construire la timeline des metas (OPBounty.pck introuvable ?).")
        return 1
    with Store(args.db) as st:
        a = Analytics(st)
        if args.meta:                       # drill-down Meta -> Leader
            rows = a.leaders_in_meta(timeline, args.meta, args.mode, having_min=args.min_games)
            if not rows:
                labels = ", ".join(m.label for m in timeline)
                print(f"Aucune donnée pour le meta « {args.meta} ».\nMetas connus : {labels}")
                return 1
            _print_rows(f"Leaders en {args.meta} ({args.mode})", rows)
        else:                               # vue d'ensemble par meta
            _print_rows(f"Winrate par meta ({args.mode})", a.by_meta(timeline, args.mode))
            print("\n→ détail d'un meta : optcgsim-haki meta \"<label>\"")
    return 0


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

    ps = sub.add_parser("stats", help="afficher les statistiques")
    ps.add_argument("--mode", default="all", choices=["all", "ranked", "direct"])
    ps.set_defaults(func=cmd_stats)

    psh = sub.add_parser("show", help="détail d'un match (préfixe d'id)")
    psh.add_argument("match_id")
    psh.set_defaults(func=cmd_show)

    pm = sub.add_parser("matchups", help="matrice de matchups par leader")
    pm.add_argument("--mode", default="all", choices=["all", "ranked", "direct"])
    pm.add_argument("--min-games", type=int, default=3)
    pm.set_defaults(func=cmd_matchups)

    pe = sub.add_parser("elo", help="courbe de rating dans le temps")
    pe.add_argument("--leader", default=None, help="filtrer par id de leader")
    pe.set_defaults(func=cmd_elo)

    pst = sub.add_parser("streaks", help="séries et performance par jour")
    pst.add_argument("--mode", default="all", choices=["all", "ranked", "direct"])
    pst.set_defaults(func=cmd_streaks)

    pmu = sub.add_parser("mulligan", help="analyse mulligan + impact des cartes d'ouverture")
    pmu.add_argument("--mode", default="all", choices=["all", "ranked", "direct"])
    pmu.add_argument("--leader", default=None, help="filtrer l'impact des cartes par id de leader")
    pmu.add_argument("--min-games", type=int, default=15)
    pmu.set_defaults(func=cmd_mulligan)

    pa = sub.add_parser("archetype", help="prédire le deck adverse d'un leader")
    pa.add_argument("leader", help="id du leader adverse (ex: OP09-001)")
    pa.add_argument("revealed", nargs="*", help="cartes déjà révélées (ids)")
    pa.set_defaults(func=cmd_archetype)

    pmt = sub.add_parser("meta", help="stats par meta (période) ; puis par leader")
    pmt.add_argument("meta", nargs="?", default=None, help="label de meta pour le détail par leader")
    pmt.add_argument("--mode", default="all", choices=["all", "ranked", "direct"])
    pmt.add_argument("--min-games", type=int, default=1)
    pmt.set_defaults(func=cmd_meta)

    sub.add_parser("decks", help="lister tes decks avec stats résumées").set_defaults(func=cmd_decks)

    pdk = sub.add_parser("deck", help="stats détaillées d'un deck (courbe, counters, couleurs)")
    pdk.add_argument("name", help="nom (ou fragment) du deck")
    pdk.set_defaults(func=cmd_deck)

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
