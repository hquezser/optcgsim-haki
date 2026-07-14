"""Tests du stockage SQLite : persistance, idempotence, fair-play live."""

from optcgsim_tracker.db.store import Store
from optcgsim_tracker.live import LiveState
from optcgsim_tracker.parser.match import parse_log
from optcgsim_tracker.watcher import MatchTimer


def test_match_timer_measures_direct_game_duration():
    clock = {"t": 1000.0}
    timer = MatchTimer(clock=lambda: clock["t"])
    timer.on_state(active=True, has_result=False)   # début
    clock["t"] = 1042.5
    timer.on_state(active=True, has_result=True)     # fin (résultat)
    assert timer.take_duration() == 42.5
    assert timer.take_duration() is None             # consommée une seule fois


def test_store_roundtrip_and_idempotence(tmp_path, autosaved_log):
    rec = parse_log(autosaved_log, match_id="m1")
    db = tmp_path / "t.db"
    with Store(db) as st:
        st.upsert_match(rec)
        st.upsert_match(rec)  # ré-insertion = pas de doublon
        assert st.query("SELECT COUNT(*) c FROM matches")[0]["c"] == 1
        ev = st.query("SELECT COUNT(*) c FROM events")[0]["c"]
        assert ev == len(rec.events)
        m = st.query("SELECT * FROM matches WHERE id='m1'")[0]
        assert m["result"] == "win"
        assert m["i_went_first"] == 0
        oh = st.query("SELECT card_id FROM opening_hands WHERE side='me' ORDER BY position")
        assert [r["card_id"] for r in oh] == rec.me.opening_hand


def test_import_card_names_does_not_override(tmp_path, autosaved_log):
    rec = parse_log(autosaved_log, match_id="m1")
    with Store(tmp_path / "t.db") as st:
        st.upsert_match(rec)
        # OP09-020 est déjà nommé par les logs ; l'import ne doit pas l'écraser.
        existing = st.card_name("OP09-020")
        n = st.import_card_names({"OP09-020": "FAUX NOM", "ZZ99-999": "Carte Externe"})
        assert n == 2
        assert st.card_name("OP09-020") == existing  # préservé
        assert st.card_name("ZZ99-999") == "Carte Externe"  # ajouté


def test_live_fairplay_hides_opponent_hand(player_log_lines):
    state = LiveState()
    for line in player_log_lines:
        state.feed_line(line)

    assert state.me_tag == "Alice#0001"
    assert state.opp_tag == "Bob#0002"
    # L'info est connue en interne…
    assert state.opp.hand_ids == ["OP10-018", "OP09-004", "OP09-009", "EB04-005", "OP09-011"]

    # …mais le rendu fair-play ne l'expose pas.
    fair = state.render(reveal_all=False)
    assert "cachées" in fair
    assert "OP10-018" not in fair  # carte adverse non révélée

    # reveal_all l'expose, avec avertissement.
    full = state.render(reveal_all=True)
    assert "OP10-018" in full or "Kamakura" in full
    assert "RÉVÉLATION TOTALE" in full
