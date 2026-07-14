"""Script de maintenance : rattache les matchs existants à un deck nommé du joueur.

Aucun nom de deck n'est écrit dans les logs : on infère le deck joué en comparant les
cartes du joueur (decklist complète ranked, ou cartes vues AutoSaved) aux decklists
nommées du jeu (même leader). Voir optcgsim_haki/deck_match.py.

À relancer après avoir édité/renommé/ajouté des decks dans le jeu : le rattachement
reflète les fichiers de deck *actuels*.

Usage :
    python3 scripts/assign_decks.py [--db optcg.db] [--dry-run] [--apply]

Par défaut : --dry-run (montre la répartition sans rien écrire).
Ajouter --apply pour écrire la colonne matches.my_deck.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from optcgsim_haki.db.store import Store
from optcgsim_haki.deck_match import load_named_decks, match_deck, my_cards_from_db


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="optcg.db", help="chemin de la base SQLite")
    ap.add_argument("--apply", action="store_true", help="écrire matches.my_deck en base")
    ap.add_argument("--dry-run", action="store_true", help="ne rien écrire (défaut)")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    decks = load_named_decks()
    if not decks:
        print("Aucun fichier de deck nommé trouvé (dossier du jeu).", file=sys.stderr)
        return 1
    print(f"{len(decks)} deck(s) nommé(s) chargé(s).")

    store = Store(args.db)
    # Seuls les matchs avec un leader local connu sont rattachables.
    matches = store.query(
        "SELECT id, my_leader FROM matches WHERE my_leader IS NOT NULL")
    print(f"{len(matches)} match(s) avec leader local.\n")

    tally: Counter = Counter()
    changes = 0
    for m in matches:
        cards, full = my_cards_from_db(store, m["id"])
        deck = match_deck(cards, m["my_leader"], decks, full=full)
        tally[deck or "(deck non identifié)"] += 1
        if apply:
            cur = store.conn.execute(
                "UPDATE matches SET my_deck = ? WHERE id = ? AND IFNULL(my_deck,'') != IFNULL(?, '')",
                (deck, m["id"], deck))
            changes += cur.rowcount
    if apply:
        store.conn.commit()

    print("Répartition des rattachements :")
    for name, n in tally.most_common():
        print(f"  {n:5}  {name}")
    identified = sum(n for k, n in tally.items() if k != "(deck non identifié)")
    print(f"\n{identified}/{len(matches)} rattachés à un deck nommé "
          f"({100*identified/len(matches):.0f}%).")
    if apply:
        print(f"{changes} ligne(s) mise(s) à jour.")
    else:
        print("\n(dry-run) Relance avec --apply pour écrire ces rattachements.")
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
