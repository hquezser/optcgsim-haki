"""Tests du rattachement match -> deck nommé (deck_match)."""

from optcgsim_tracker.deck_match import NamedDeck, match_deck, match_deck_strict

# Deux decks du même leader, partageant un tronc commun mais avec une techno distincte.
_AGGRO = NamedDeck("Sanji Aggro", "PRB01-001",
                   frozenset({"A1", "A2", "A3", "A4", "A5", "CORE1", "CORE2", "CORE3"}))
_CONTROL = NamedDeck("Sanji Control", "PRB01-001",
                     frozenset({"C1", "C2", "C3", "C4", "C5", "CORE1", "CORE2", "CORE3"}))
_OTHER = NamedDeck("Yamato", "OP16-079", frozenset({"Y1", "Y2", "Y3", "Y4", "Y5"}))
_DECKS = [_AGGRO, _CONTROL, _OTHER]


def test_matches_clear_winner_full_decklist():
    # Decklist complète quasi identique à l'aggro -> Jaccard tranche nettement.
    cards = {"PRB01-001", "A1", "A2", "A3", "A4", "A5", "CORE1", "CORE2", "CORE3"}
    assert match_deck(cards, "PRB01-001", _DECKS, full=True) == "Sanji Aggro"


def test_matches_from_seen_cards_overlap():
    # Cartes vues (partielles) toutes présentes dans le control -> overlap tranche.
    cards = {"C1", "C2", "C3", "CORE1", "CORE2"}
    assert match_deck(cards, "PRB01-001", _DECKS, full=False) == "Sanji Control"


def test_ambiguous_returns_none():
    # Seulement le tronc commun : aucun des deux decks ne se détache -> None.
    cards = {"CORE1", "CORE2", "CORE3", "PRB01-001", "X1"}
    assert match_deck(cards, "PRB01-001", _DECKS, full=False) is None


def test_too_few_cards_returns_none():
    assert match_deck({"A1", "A2"}, "PRB01-001", _DECKS, full=False) is None


def test_no_candidate_for_leader_returns_none():
    cards = {"Z1", "Z2", "Z3", "Z4", "Z5", "Z6"}
    assert match_deck(cards, "OP99-001", _DECKS, full=False) is None


def test_leader_excluded_from_scoring():
    # Le leader ne doit pas suffire : retiré du calcul, il reste trop peu de cartes.
    assert match_deck({"PRB01-001", "A1", "A2"}, "PRB01-001", _DECKS, full=False) is None


# --- match_deck_strict : identification « fiable » (toutes les cartes vues ⊆ un seul deck) ---

def test_strict_unique_full_containment():
    cards = {"A1", "A2", "A3", "CORE1", "CORE2"}     # ⊆ aggro seulement
    assert match_deck_strict(cards, "PRB01-001", _DECKS) == "Sanji Aggro"


def test_strict_ambiguous_when_two_decks_contain_all():
    # 5+ cartes vues, toutes dans le tronc commun de DEUX decks -> indécidable.
    a = NamedDeck("V1", "L", frozenset({"S1", "S2", "S3", "S4", "S5", "X1"}))
    b = NamedDeck("V2", "L", frozenset({"S1", "S2", "S3", "S4", "S5", "X2"}))
    assert match_deck_strict({"S1", "S2", "S3", "S4", "S5"}, "L", [a, b]) is None
    # Dès qu'une carte discriminante apparaît -> certain.
    assert match_deck_strict({"S1", "S2", "S3", "S4", "X1"}, "L", [a, b]) == "V1"


def test_strict_none_when_a_seen_card_fits_no_deck():
    cards = {"A1", "A2", "A3", "CORE1", "ZZZ"}       # ZZZ n'existe dans aucun deck
    assert match_deck_strict(cards, "PRB01-001", _DECKS) is None


def test_strict_too_few_cards():
    assert match_deck_strict({"A1", "A2"}, "PRB01-001", _DECKS) is None


def test_strict_requires_leader():
    assert match_deck_strict({"A1", "A2", "A3", "A4", "A5"}, None, _DECKS) is None
