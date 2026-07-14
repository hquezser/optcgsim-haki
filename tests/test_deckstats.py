"""Tests des stats de deck (courbe, counters, couleurs, types)."""

from optcgsim_tracker.cardmeta import CardMeta
from optcgsim_tracker.deckstats import Deck, compute_stats, opening_odds, parse_deck_file


META = {
    "LDR-001": CardMeta("LDR-001", name="Leader", card_type="Leader", colors=["Red"], life=5),
    "C1": CardMeta("C1", name="One", cost=1, counter=1000, card_type="Character", colors=["Red"]),
    "C2": CardMeta("C2", name="Two", cost=2, counter=2000, card_type="Character", colors=["Red"]),
    "C5": CardMeta("C5", name="Five", cost=5, counter=0, card_type="Character", colors=["Red", "Green"],
                   subtypes=["Sky Island", "Vassals"]),
    "E1": CardMeta("E1", name="Ev", cost=1, counter=2000, card_type="Event", colors=["Red"]),
    "T1": CardMeta("T1", name="Trig", cost=2, counter=0, card_type="Event", colors=["Red"],
                   description="[Trigger] Draw 1 card."),
}


def test_compute_stats():
    deck = Deck(name="t", path=None, leader="LDR-001",
                cards={"C1": 4, "C2": 4, "C5": 2, "E1": 2})
    s = compute_stats(deck, META)
    assert s.total == 12
    assert s.leader_name == "Leader"
    assert s.curve == {1: 6, 2: 4, 5: 2}          # C1+E1 à coût 1
    assert s.counter_1000 == 4                      # C1
    assert s.counter_2000 == 6                      # C2 + E1
    assert s.counter_total == 10                    # toutes sauf C5
    assert s.types == {"Character": 10, "Event": 2}
    assert s.colors["Red"] == 12 and s.colors["Green"] == 2
    assert s.subtypes == {"Sky Island": 2, "Vassals": 2}   # C5 ×2
    assert s.unknown == []


def test_unknown_cards_flagged():
    deck = Deck(name="t", path=None, leader="LDR-001", cards={"C1": 4, "ZZ99-999": 4})
    s = compute_stats(deck, META)
    assert s.unknown == ["ZZ99-999"]
    assert s.total == 8           # comptées dans le total
    assert s.curve == {1: 4}      # mais exclues des stats


def test_parse_deck_file(tmp_path):
    p = tmp_path / "MonDeck.txt"
    p.write_text("1xLDR-001\n4xC1\n2xC2\n")
    d = parse_deck_file(p)
    assert d.name == "MonDeck"
    assert d.leader == "LDR-001"
    assert d.cards == {"C1": 4, "C2": 2}


def test_opening_odds():
    deck = Deck(name="t", path=None, leader="LDR-001",
                cards={"C1": 4, "C2": 4, "C5": 2, "E1": 2, "T1": 2})
    odds = opening_odds(deck, META, leader_life=5)

    # deck_size = somme des quantités connues (leader exclu, cartes inconnues exclues)
    assert odds["deck_size"] == 14
    assert odds["hand_size"] == 5

    # per_card : une entrée par carte connue, triée par qty desc puis nom
    pc = odds["per_card"]
    assert len(pc) == 5
    assert [c["qty"] for c in pc] == sorted((c["qty"] for c in pc), reverse=True)
    # tie-break par nom pour les cartes à même qty (C1 et C2 à 4)
    four = [c for c in pc if c["qty"] == 4]
    assert four[0]["name"] < four[1]["name"]

    # bornes [0, 100] et cohérence : p_mulligan >= p_opening (le mulligan ajoute une 2e main)
    for c in pc:
        assert 0.0 <= c["p_opening"] <= 100.0
        assert 0.0 <= c["p_mulligan"] <= 100.0
        assert c["p_mulligan"] >= c["p_opening"]

    # monotonie : plus de copies => p_opening plus élevé
    by_qty = {}
    for c in pc:
        by_qty.setdefault(c["qty"], []).append(c["p_opening"])
    qtys = sorted(by_qty)
    assert by_qty[qtys[-1]][0] > by_qty[qtys[0]][0]

    # deck_level : trigger (T1×2) et counter (C1+C2+E1 = 10) présents
    dl = odds["deck_level"]
    assert dl["life_size"] == 5
    assert 0.0 <= dl["trigger_in_hand"] <= 100.0
    assert 0.0 <= dl["trigger_in_life"] <= 100.0
    assert 0.0 <= dl["counter_in_hand"] <= 100.0
    # 10 counters sur 14 cartes => forte proba en main
    assert dl["counter_in_hand"] > dl["trigger_in_hand"]


def test_opening_odds_empty():
    deck = Deck(name="t", path=None, leader="LDR-001", cards={"ZZ99": 4})
    odds = opening_odds(deck, META)
    assert odds["deck_size"] == 0
    assert odds["per_card"] == []
    assert odds["deck_level"]["trigger_in_hand"] == 0.0
    assert odds["deck_level"]["life_size"] == 5
