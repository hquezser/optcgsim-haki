"""Un Event [Counter] joué en défense au dernier tour ne doit pas passer pour 'mort en main'."""

from datetime import datetime

from optcgsim_haki.analytics import Analytics
from optcgsim_haki.db.store import Store
from optcgsim_haki.parser.match import parse_log

_REF = '[<mark><link="{0}">{0}</link></mark>]'


def _log() -> str:
    r = _REF.format
    # Mon Event Counter (OP14-018) est en main de départ, joué en défense au TOUT DERNIER
    # tour (Activate Counter), puis la partie se termine SANS nouveau snapshot Trash de moi.
    return "\n".join([
        f'[Bob#0002] Leader is Kaido {r("OP01-060")}',
        f'[Alice#0001] Leader is Sanji {r("PRB01-001")}',
        '[Alice#0001] Hand before Mulligan: [OP14-018,OP01-025]',
        '[Alice#0001] Chose to go Second',
        # Snapshot de moi (début de partie) : Trash vide, OP14-018 encore en main.
        '[Alice#0001] Hand: [OP14-018,OP01-025]',
        '[Alice#0001] Trash: []',
        '[Alice#0001] Life: 4',
        '[Alice#0001] End Turn',
        # Tour de l'adversaire : il attaque, je défends avec l'Event Counter, puis je perds.
        f'[Bob#0002] Kaido {r("OP01-060")} attacking Sanji {r("PRB01-001")}',
        f'[Alice#0001] Time for the Counter-Attack {r("OP14-018")}: Activate Counter',
        '[Bob#0002] Wins!',
    ])


def test_defensive_counter_event_emits_event():
    rec = parse_log(_log(), match_id="t")
    ce = [e for e in rec.events if e.type == "counter_event"]
    assert len(ce) == 1
    assert ce[0].card_id == "OP14-018"
    assert ce[0].side == "me"
    assert rec.result == "loss"  # Bob Wins!


def test_defensive_counter_event_not_dead_in_hand(tmp_path):
    rec = parse_log(_log(), match_id="t")
    with Store(tmp_path / "t.db") as st:
        st.upsert_match(rec)
        a = Analytics(st)
        # min_games=1 pour faire ressortir la carte malgré l'échantillon unique.
        _, _, cards = a.opening_impact(leader="PRB01-001", min_games=1)
        op = {c["card_id"]: c for c in cards}
        assert "OP14-018" in op
        # PRO = 100% (utilisée), et aucune partie "morte en main" -> dwr_dead None.
        assert op["OP14-018"]["pro"] == 100.0
        assert op["OP14-018"]["n_dead"] == 0
