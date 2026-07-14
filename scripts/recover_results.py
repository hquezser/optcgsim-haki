"""Script de maintenance : rattrape les résultats manquants des logs AutoSaved tronqués.

OPTCGSim écrit parfois le .log d'une partie avant d'y inscrire la ligne finale
('Wins!'/'Concedes!') — typiquement quand on retourne vite au menu après le coup gagnant.
Ces parties sont bien en base mais avec result=NULL, donc invisibles dans toutes les stats
(qui filtrent `result IN ('win','loss')`).

Ce script rejoue les logs AutoSaved encore présents sur le disque et, pour chaque match
NULL dont le parser arrive maintenant à *inférer* le résultat (voir
parser.match._infer_truncated_result), met la base à jour.

Usage :
    python3 scripts/recover_results.py [--db optcg.db] [--dry-run] [--apply]

Par défaut : --dry-run (montre ce qui serait corrigé sans rien écrire).
Ajouter --apply pour écrire réellement les corrections.
"""

from __future__ import annotations

import argparse
import sys

from optcgsim_tracker.db.store import Store
from optcgsim_tracker.parser.match import parse_log
from optcgsim_tracker.sources import Sources


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="optcg.db", help="chemin de la base SQLite")
    ap.add_argument("--apply", action="store_true", help="écrire les corrections en base")
    ap.add_argument("--dry-run", action="store_true",
                    help="ne rien écrire (défaut si --apply absent)")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    store = Store(args.db)

    # Matchs sans résultat du tout (clé = content_hash du log). On ne touche QUE les NULL :
    # les statuts explicites (selfdc, started, ...) portent une info qu'on ne veut pas écraser.
    null_ids = {
        r["id"] for r in store.query("SELECT id FROM matches WHERE result IS NULL")
    }
    print(f"{len(null_ids)} match(s) sans résultat (NULL) en base.")

    logs = Sources().autosaved_logs()
    print(f"{len(logs)} log(s) AutoSaved sur le disque.\n")

    recovered: list[tuple[str, str, str]] = []  # (id, result, opp_leader)
    seen_on_disk = 0
    for lf in logs:
        mid = lf.content_hash()
        if mid not in null_ids:
            continue
        seen_on_disk += 1
        rec = parse_log(lf.read_text(), match_id=mid,
                        played_at=lf.mtime, source="autosaved")
        if rec.result in ("win", "loss"):
            recovered.append((mid, rec.result, rec.opp.leader or "?"))
            if apply:
                store.conn.execute(
                    "UPDATE matches SET result = ?, win_reason = ? WHERE id = ?",
                    (rec.result, rec.win_reason or "inferred", mid),
                )

    if apply:
        store.conn.commit()

    print(f"Parmi les NULL, {seen_on_disk} ont encore leur log sur le disque.")
    print(f"{len(recovered)} résultat(s) {'corrigé(s)' if apply else 'récupérable(s)'} :")
    for mid, result, opp in recovered:
        name = store.card_name(opp)
        print(f"  {mid}  ->  {result:4}  vs {name} ({opp})")

    unrecovered = len(null_ids) - len(recovered)
    if not apply and recovered:
        print(f"\n(dry-run) Relance avec --apply pour écrire ces {len(recovered)} corrections.")
    print(f"\n{unrecovered} match(s) restent sans résultat "
          f"(log absent, ou partie réellement incomplète).")
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
