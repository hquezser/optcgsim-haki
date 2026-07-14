"""Rattachement d'un match à un deck nommé du joueur.

Aucun nom de deck n'est écrit dans les logs (ni AutoSaved, ni ranked). On infère le deck
joué en comparant les cartes du joueur local dans le match aux decklists nommées
(fichiers .txt du jeu), parmi celles du même leader :
  - decklist complète connue (parties ranked) -> similarité de Jaccard,
  - seulement les cartes vues (parties AutoSaved directes) -> recouvrement (overlap).

Si aucun candidat ne se détache nettement (trop peu de cartes, score trop faible, ou
deux decks trop proches), on renvoie None : le match restera « deck non identifié ».
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .deckstats import parse_deck_file
from .sources import Sources

# Seuils calibrés empiriquement sur ~550 parties Sanji (8 variantes du même leader) :
# 83 % de rattachements nets, le bon deck étant systématiquement très détaché du 2e.
_MIN_CARDS = 5      # en-dessous : trop peu d'information pour trancher
_MIN_SCORE = 0.40   # score minimal du meilleur candidat
_MIN_MARGIN = 0.08  # écart minimal (best - second) pour lever l'ambiguïté


@dataclass(frozen=True)
class NamedDeck:
    name: str
    leader: str | None
    cards: frozenset[str]


def load_named_decks(sources: Sources | None = None) -> list[NamedDeck]:
    """Charge les decks nommés du joueur (fichiers .txt du dossier du jeu)."""
    src = sources or Sources()
    d = src.paths.app_support
    out: list[NamedDeck] = []
    if d.exists():
        for p in sorted(d.glob("*.txt")):
            deck = parse_deck_file(p)
            out.append(NamedDeck(p.stem, deck.leader, frozenset(deck.cards)))
    return out


def match_deck(cards: set[str], leader: str | None,
               decks: list[NamedDeck], *, full: bool) -> str | None:
    """Nom du deck nommé le plus probable pour ce match, ou None si indécidable.

    `full=True`  : decklist complète connue   -> Jaccard.
    `full=False` : seulement les cartes vues   -> overlap (fraction des cartes vues
                   présentes dans le deck candidat).
    """
    if not leader:
        return None
    cards = set(cards)
    cards.discard(leader)  # le leader est commun à tous les candidats : on l'ignore
    if len(cards) < _MIN_CARDS:
        return None
    scored: list[tuple[float, str]] = []
    for d in decks:
        if d.leader != leader or not d.cards:
            continue
        inter = len(cards & d.cards)
        union = len(cards | d.cards)
        score = (inter / union) if full else (inter / len(cards))
        scored.append((score, d.name))
    if not scored:
        return None
    scored.sort(reverse=True)
    best_score, best_name = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score < _MIN_SCORE or (best_score - second) < _MIN_MARGIN:
        return None
    return best_name


def match_deck_strict(cards: set[str], leader: str | None,
                      decks: list[NamedDeck]) -> str | None:
    """Identification STRICTE (critère « fiable » v1) : nom du deck seulement si TOUTES les
    cartes vues appartiennent à UN SEUL candidat du même leader. Sinon None.

    Tant que deux decks sauvegardés peuvent expliquer les cartes vues, on ne tranche pas ;
    dès qu'une carte vue n'existe que dans un deck, il devient certain (modulo un deck
    joué mais non sauvegardé — indétectable, assumé).
    """
    if not leader:
        return None
    cards = set(cards)
    cards.discard(leader)
    if len(cards) < _MIN_CARDS:
        return None
    full = [d.name for d in decks if d.leader == leader and d.cards and cards <= d.cards]
    return full[0] if len(full) == 1 else None


def my_cards_from_db(store, match_id: str) -> tuple[set[str], bool]:
    """Cartes jouées par le joueur local dans un match (depuis la base).

    Renvoie (cartes, full) : decklist complète (ranked) si dispo, sinon cartes vues
    reconstituées depuis les events et snapshots (AutoSaved).
    """
    full = {r["card_id"] for r in store.query(
        "SELECT card_id FROM decks WHERE match_id=? AND side='me' AND known=1", (match_id,))}
    if full:
        return full, True
    seen = {r["card_id"] for r in store.query(
        "SELECT DISTINCT card_id FROM events "
        "WHERE match_id=? AND side='me' AND card_id IS NOT NULL", (match_id,))}
    for row in store.query(
        "SELECT hand_ids, board_ids, trash_ids FROM turn_snapshots "
        "WHERE match_id=? AND side='me'", (match_id,)):
        for col in ("hand_ids", "board_ids", "trash_ids"):
            seen.update(json.loads(row[col] or "[]"))
    return seen, False


def my_cards_from_record(rec) -> tuple[set[str], bool]:
    """Idem my_cards_from_db mais depuis un MatchRecord fraîchement parsé (watcher)."""
    if rec.me.deck_known and rec.me.deck:
        return set(rec.me.deck), True
    seen = {e.card_id for e in rec.events if e.side == "me" and e.card_id}
    for s in rec.snapshots:
        if s.side == "me":
            seen.update(s.hand_ids)
            seen.update(s.board_ids)
            seen.update(s.trash_ids)
    return seen, False
