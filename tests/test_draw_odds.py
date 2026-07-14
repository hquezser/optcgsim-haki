"""Tests du calcul d'odds de pioche live (_build_draw_odds)."""

from optcgsim_tracker.cardmeta import CardMeta
from optcgsim_tracker.engine import _build_draw_odds


META = {
    "TRIG": CardMeta("TRIG", name="Trig", description="[Trigger] do something"),
    "CTR":  CardMeta("CTR", name="Counter card", counter=2000, description="[Blocker]"),
    "PLAIN": CardMeta("PLAIN", name="Plain", description="no keyword"),
}


def test_returns_none_when_pool_empty():
    assert _build_draw_odds({"TRIG": 2}, 0, META) is None


def test_returns_none_when_no_remaining():
    assert _build_draw_odds({"TRIG": 0, "CTR": 0}, 30, META) is None


def test_per_card_probabilities_and_sort():
    odds = _build_draw_odds({"PLAIN": 4, "TRIG": 1}, 40, META)
    assert odds["pool"] == 40
    assert odds["n_cards"] == 2
    # P(prochaine pioche) = copies/pool.
    by_id = {c["card_id"]: c for c in odds["per_card"]}
    assert by_id["PLAIN"]["p_next"] == 10.0          # 4/40
    assert by_id["TRIG"]["p_next"] == 2.5            # 1/40
    # Trié par proba décroissante : la carte à 4 copies d'abord.
    assert odds["per_card"][0]["card_id"] == "PLAIN"


def test_deck_level_trigger_and_counter():
    odds = _build_draw_odds({"TRIG": 3, "CTR": 2, "PLAIN": 5}, 50, META)
    assert odds["deck_level"]["trigger_next"] == 6.0   # 3/50
    assert odds["deck_level"]["counter_next"] == 4.0   # 2/50


def test_truncation_flag_and_top():
    remaining = {f"PLAIN{i}": 1 for i in range(20)}
    meta = {k: CardMeta(k, name=k, description="x") for k in remaining}
    odds = _build_draw_odds(remaining, 40, meta, top=12)
    assert odds["n_cards"] == 20
    assert odds["truncated"] is True
    assert len(odds["per_card"]) == 12
