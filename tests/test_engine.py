"""Tests du dashboard live : payload /state (fair-play + archétype) et serveur HTTP."""

import json
import threading
import urllib.request

import pytest

from .conftest import FIXTURES
from optcgsim_haki.db.store import Store
from optcgsim_haki.engine import LiveEngine, _forecast_next_plays, _compute_lethal
from optcgsim_haki.engine import _solve_lethal, _don_cost
from optcgsim_haki.model import MatchRecord, PlayerInfo


# Ces tests valident la logique interne du chemin live/log (lethal, archétype,
# vie/main adverse reconstruites...). Le feature-gating v1 masque ces panneaux
# approximatifs par défaut ; on active donc le profil advanced pour exercer tout
# le pipeline. Le gating en lui-même est couvert par tests/test_features.py.
@pytest.fixture(autouse=True)
def _advanced_profile(monkeypatch):
    monkeypatch.setenv("OPTCG_PROFILE", "advanced")


def test_forecast_next_plays_ranks_affordable_drawn_cards():
    expected = [
        {"card_id": "A", "name": "Gros", "presence": 90, "avg_copies": 4},   # 8c, jouable
        {"card_id": "B", "name": "Cher", "presence": 80, "avg_copies": 2},   # 9c, trop cher
        {"card_id": "C", "name": "Petit", "presence": 70, "avg_copies": 4},  # 2c, jouable
        {"card_id": "D", "name": "Vu", "presence": 100, "avg_copies": 2},    # 2 exemplaires vus
    ]
    cost = {"A": 8, "B": 9, "C": 2, "D": 3}
    out = _forecast_next_plays(expected, cost, {}, opp_deck=30, don=8,
                               seen_counts={"D": 2})
    ids = [t["card_id"] for t in out]
    assert "B" not in ids          # coût 9 > DON 8
    assert "D" not in ids          # tous les exemplaires déjà vus
    assert ids[0] == "A"           # forte présence + 4 copies + abordable -> tête
    assert all(0 < t["prob"] <= 100 for t in out)
    # Plus le deck est entamé, plus la proba d'avoir pioché est élevée.
    early = _forecast_next_plays(expected, cost, {}, opp_deck=44, don=8, seen_counts={})
    late = _forecast_next_plays(expected, cost, {}, opp_deck=20, don=8, seen_counts={})
    pa = next(t["prob"] for t in early if t["card_id"] == "A")
    pb = next(t["prob"] for t in late if t["card_id"] == "A")
    assert pb > pa


def test_forecast_next_plays_phase_weighting():
    """L'affinage contextuel pondère le score par le play-rate à la phase actuelle."""
    expected = [
        {"card_id": "A", "name": "MidCard", "presence": 80, "avg_copies": 4},  # jouable
        {"card_id": "C", "name": "EarlyCard", "presence": 60, "avg_copies": 2},  # jouable
    ]
    cost = {"A": 5, "C": 2}
    # A est une carte mid/late (play-rate early=5%), C est early (play-rate early=70%).
    phase_rates = {
        "A": {"early": 5, "mid": 60, "late": 80, "n": 30},
        "C": {"early": 70, "mid": 50, "late": 20, "n": 30},
    }

    # En early : A (présence ~28% × play-rate 5% = 1.4%) est filtrée,
    #            C (présence ~11% × play-rate 70% = 8%) peut passer si min_prob bas.
    early = _forecast_next_plays(expected, cost, {}, opp_deck=45, don=5, seen_counts={},
                                 phase="early", phase_play_rates=phase_rates, min_prob=5)
    early_ids = [t["card_id"] for t in early]
    assert "C" in early_ids  # C est la vraie menace en early
    # A est filtrée en early (score trop bas)
    a_early = [t for t in early if t["card_id"] == "A"]
    assert not a_early or a_early[0]["prob"] < 5

    # En late : A (28% × 80% = 22%) domine, C (11% × 20% = 2%) est filtrée.
    late = _forecast_next_plays(expected, cost, {}, opp_deck=45, don=5, seen_counts={},
                                phase="late", phase_play_rates=phase_rates, min_prob=5)
    late_ids = [t["card_id"] for t in late]
    assert "A" in late_ids
    assert late[0]["card_id"] == "A"  # A est la menace principale en late

    # Vérifie que raw_prob et play_rate sont retournés quand pondération active.
    a_late = next(t for t in late if t["card_id"] == "A")
    assert a_late["raw_prob"] is not None
    assert a_late["play_rate"] == 80
    assert a_late["prob"] < a_late["raw_prob"]  # score pondéré < présence brute

    # Sans pondération (fallback) : raw_prob et play_rate sont None.
    no_phase = _forecast_next_plays(expected, cost, {}, opp_deck=45, don=5, seen_counts={})
    assert all(t["raw_prob"] is None for t in no_phase)
    assert all(t["play_rate"] is None for t in no_phase)


def _seed_db(path):
    """DB minimale : noms + quelques decks Shanks (OP09-001) pour l'archétype."""
    with Store(path) as st:
        st.import_card_names({"OP09-001": "Shanks", "OP09-002": "Uta",
                              "OP09-009": "Benn Beckman", "OP09-004": "Shanks"})
        for i, deck in enumerate([
            {"OP09-002": 4, "OP09-009": 4, "OP09-004": 3},
            {"OP09-002": 4, "OP09-009": 3, "OP09-004": 4},
        ]):
            rec = MatchRecord(match_id=f"h{i}", mode="ranked")
            rec.me = PlayerInfo("me", leader="L1")
            rec.opp = PlayerInfo("opp", leader="OP09-001", deck=deck, deck_known=True)
            rec.result = "win"
            st.upsert_match(rec)


def _live_match(srv, me_leader="L1", opp_leader="OP09-001"):
    """Installe un match live minimal (2 joueurs + leaders) sur l'état du serveur."""
    st = srv.state
    st.reset_match()
    st.me_tag, st.opp_tag = "Me#1", "Foe#2"
    st._player("Me#1").side = "me"; st._player("Me#1").leader = me_leader
    st._player("Foe#2").side = "opp"; st._player("Foe#2").leader = opp_leader
    return st


def _finished_rec(result="win", reason="concede", me_leader="L1", opp_leader="OP09-001"):
    rec = MatchRecord(match_id="x", mode="ranked")
    rec.me = PlayerInfo("me", leader=me_leader)
    rec.opp = PlayerInfo("opp", leader=opp_leader)
    rec.result, rec.win_reason = result, reason
    return rec


def test_apply_finished_result_marks_live_result(tmp_path):
    """Le résultat (issu de l'AutoSaved de fin) est réinjecté dans l'état live."""
    srv = LiveEngine(str(tmp_path / "t.db"), reveal_all=False)
    st = _live_match(srv)
    srv._apply_finished_result(_finished_rec("win", "concede"))
    assert st.result == "win" and st.win_reason == "concede" and st.active is False
    assert srv._state_payload()["result"] == "win"


def test_apply_finished_result_ignores_mismatched_leaders(tmp_path):
    """Un AutoSaved d'une AUTRE partie (leaders incompatibles) ne marque pas l'état courant."""
    srv = LiveEngine(str(tmp_path / "t.db"), reveal_all=False)
    st = _live_match(srv, me_leader="L1", opp_leader="OP09-001")
    srv._apply_finished_result(_finished_rec(me_leader="ZZ9-999", opp_leader="ZZ9-998"))
    assert st.result is None


def test_apply_finished_result_does_not_overwrite(tmp_path):
    srv = LiveEngine(str(tmp_path / "t.db"), reveal_all=False)
    st = _live_match(srv)
    st.result = "loss"
    srv._apply_finished_result(_finished_rec("win", "concede"))
    assert st.result == "loss"  # résultat déjà connu -> pas d'écrasement


def test_state_payload_empty_no_crash(tmp_path):
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    # Avant toute ligne de log : /state ne doit pas planter.
    payload = srv._state_payload()
    assert payload.get("me") is None
    assert payload.get("opp") is None


def test_state_payload_fairplay_and_archetype(tmp_path, autosaved_log):
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    for line in autosaved_log.splitlines():
        srv.state.feed_line(line)

    payload = srv._state_payload()
    # Fair-play : main adverse masquée.
    assert payload["opp"]["hand"] is None
    assert payload["opp"]["hand_count"] >= 0
    # Ma main est visible.
    assert isinstance(payload["me"]["hand"], list)
    # Archétype présent (opp = Shanks), prédiction non vide.
    arch = payload["archetype"]
    assert arch["leader_name"] == "Shanks"
    assert arch["n_historical"] == 2
    assert any(c["name"] == "Uta" for c in arch["expected_cards"])
    # 'revealed' ne contient que du public (board/trash), jamais la main.
    assert "revealed" in arch


def test_state_payload_writes_inferred_leader_id(tmp_path):
    """En live, le leader n'est pas loggé : le moteur le déduit ET écrit son id (pas seulement
    le nom) dans le payload, avec le flag leader_inferred. Régression : auparavant
    payload['opp']['leader'] restait None alors que le leader était connu."""
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = srv.state
    st.reset_match()
    st.me_tag, st.opp_tag = "Me#1", "Foe#2"
    st._player("Me#1").side = "me"
    st._player("Foe#2").side = "opp"
    # Cartes publiques adverses du deck Shanks (OP09-001) -> inférence du leader.
    st._player("Foe#2").board_ids = ["OP09-002", "OP09-009"]

    payload = srv._state_payload()
    assert payload["opp"]["leader"] == "OP09-001"          # id écrit (Bug A corrigé)
    assert payload["opp"]["leader_name"] == "Shanks"
    assert payload["opp"]["leader_inferred"] is True
    assert "leader_meta_missing" in payload["opp"]


def _seed_lethal_cards(db):
    with Store(db) as st:
        for cid, power in [("LME", 5000), ("LOPP", 5000), ("BIG", 10000)]:
            st.conn.execute(
                "INSERT OR IGNORE INTO cards (card_id, power, has_blocker, has_dbl_atk, counter,"
                " cost, card_type) VALUES (?,?,0,0,0,?,?)",
                (cid, power, 0 if cid.startswith("L") else 5,
                 "Leader" if cid.startswith("L") else "Character"))
        st.conn.commit()


def test_lethal_confidence_graded(tmp_path):
    """Le lethal offensif expose un niveau de confiance + un seuil de counter, pas un binaire."""
    db = tmp_path / "t.db"
    _seed_lethal_cards(db)
    srv = LiveEngine(str(db), reveal_all=False)
    common = dict(me_board_ids=["BIG"], opp_board_ids=[], me_hand_ids=[],
                  me_life=5, opp_life=1, opp_avg_counter=1000, me_don=8, opp_don=0)

    # Cas medium : main adverse non vide (counters estimés), leader connu.
    l = srv._build_lethal_payload("LME", "LOPP", opp_hand_count=3, **common)
    assert l["me_can_lethal"] is True
    conf = l["me_lethal_confidence"]
    assert conf is not None
    assert conf["level"] == "medium"
    assert l["me_counter_threshold"] is not None
    assert any("counters adverses estimés" in f for f in conf["factors"])

    # Cas high : adversaire sans carte en main -> aucun counter possible, leader connu.
    l_hi = srv._build_lethal_payload("LME", "LOPP", opp_hand_count=0, **common)
    assert l_hi["me_lethal_confidence"]["level"] == "high"

    # Cas low : leader adverse déduit -> confiance faible.
    l_lo = srv._build_lethal_payload("LME", "LOPP", opp_hand_count=3,
                                     opp_leader_inferred=True, **common)
    assert l_lo["me_lethal_confidence"]["level"] == "low"
    assert any("leader adverse déduit" in f for f in l_lo["me_lethal_confidence"]["factors"])


def test_reveal_all_exposes_opp_hand_from_rz1():
    """En live, reveal_all expose la main adverse reconstruite depuis le flux RZ1 (identités
    piochées moins jouées) ; en fair-play elle reste cachée."""
    from optcgsim_haki.live import LiveState
    s = LiveState()
    s.feed_line("shuffle deck for Foe#2222")
    s.feed_line("shuffle deck for Me#0000")
    s.feed_line("[ReplaySync] RZ1|1|1|OP01-001|0|49|1|0|1|1|0|0|0")  # ma pioche -> me=player1
    s.feed_line("Hand before Mulligan: [OP01-001]")
    for seq, c in [(2, "OP16-014"), (3, "OP16-017"), (4, "OP13-007")]:
        s.feed_line(f"[ReplaySync] RZ1|{seq}|2|{c}|0|49|1|0|0|1|0|0|0")  # pioches adverses
    assert s.me_tag == "Me#0000" and s.opp_tag == "Foe#2222"

    # Fair-play : main adverse cachée.
    assert s.to_dict(reveal_all=False)["opp"]["hand"] is None
    # Reveal-all : main adverse reconstruite.
    revealed = [c["id"] for c in s.to_dict(reveal_all=True)["opp"]["hand"]]
    assert revealed == ["OP16-014", "OP16-017", "OP13-007"]
    # L'adversaire joue une carte (main -> board) : elle quitte la main suivie.
    s.feed_line("[ReplaySync] RZ1|5|2|OP16-014|1|0|2|0|0|1|0|0|0")
    revealed2 = [c["id"] for c in s.to_dict(reveal_all=True)["opp"]["hand"]]
    assert "OP16-014" not in revealed2 and revealed2 == ["OP16-017", "OP13-007"]


def test_reveal_all_exposes_hand(tmp_path, autosaved_log):
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=True)
    for line in autosaved_log.splitlines():
        srv.state.feed_line(line)
    payload = srv._state_payload()
    assert isinstance(payload["opp"]["hand"], list)  # révélée
    assert payload["reveal_all"] is True


def test_state_payload_don_est_uses_don_on_field(tmp_path):
    """opp_don_est = don_on_field + 2 (capped 10) quand le flux RZ1 l'a mesuré ;
    sinon repli sur le proxy '44 - deck'."""
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = _live_match(srv)
    # Cas 1 : DON sur terrain mesuré = 4 -> T+1 = 6 (filtre coût ≤ 6, pas ≤ proxy).
    st.opp.don_on_field = 4
    st.opp.deck_remaining = 30  # proxy donnerait 28 -> capé 10 : trompeur, doit être ignoré
    p = srv._state_payload()
    assert p["opp_don_est"] == 6
    # Cap à 10 : 9 sur terrain -> 11 -> 10.
    st.opp.don_on_field = 9
    assert srv._state_payload()["opp_don_est"] == 10
    # Cas 2 : pas de DON mesuré -> repli proxy (deck=44 -> 0*2+2 = 2).
    st.opp.don_on_field = None
    st.opp.deck_remaining = 44
    assert srv._state_payload()["opp_don_est"] == 2


def test_state_payload_opp_life_from_base_minus_damage(tmp_path):
    """Vie adverse en live = CardMeta.life(leader) - dégâts cumulés ('hit for N damage').
    Pas de snapshot texte adverse en live -> opp.life reconstruit. Garde-fou : <0 -> None."""
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = _live_match(srv, opp_leader="OP09-001")  # Shanks, life 5
    st.opp.life = None  # live : pas de snapshot adverse
    # Aucun dégât -> vie de base.
    assert srv._state_payload()["opp"]["life"] == 5
    # 2 dégâts sur le leader adverse.
    st.feed_line('Shanks [<mark><link="OP09-001">OP09-001</link></mark>] hit for 1 damage')
    st.feed_line('Shanks [<mark><link="OP09-001">OP09-001</link></mark>] hit for 1 damage')
    assert srv._state_payload()["opp"]["life"] == 3
    # 5 dégâts cumulés -> vie 0 (encore valide, pas négatif).
    for _ in range(3):
        st.feed_line('Shanks [<mark><link="OP09-001">OP09-001</link></mark>] hit for 1 damage')
    assert srv._state_payload()["opp"]["life"] == 0
    # Un dégât de trop -> garde-fou, on ne devine pas une vie négative.
    st.feed_line('Shanks [<mark><link="OP09-001">OP09-001</link></mark>] hit for 1 damage')
    assert srv._state_payload()["opp"]["life"] is None


def test_state_payload_opp_life_from_life_added_to_hand(tmp_path):
    """En live, Player.log n'a pas de 'hit for damage' : la vie adverse est dérivée des
    'life added to hand' (1 vie perdue par l'un des deux) en retranchant MES pertes connues
    par snapshot. pertes_adverses = total - (vie_base_moi - ma_vie)."""
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = _live_match(srv, me_leader="OP09-001", opp_leader="OP09-001")  # Shanks, vie 5
    st.me.life = 4       # ma vie snapshot : j'ai perdu 1
    st.opp.life = None   # live : pas de snapshot adverse
    # 3 "life added to hand" au total ; 1 perdue par moi -> 2 par l'adversaire.
    for _ in range(3):
        st.feed_line("Queue up life added to hand actions")
    assert srv._state_payload()["opp"]["life"] == 3   # 5 - 2
    # Une de plus encaissée par l'adversaire (ma vie inchangée) -> opp à 2.
    st.feed_line("Queue up life added to hand actions")
    assert srv._state_payload()["opp"]["life"] == 2


def test_state_payload_opp_hand_count_rz1_plus_damage(tmp_path):
    """Main adverse en live = net RZ1 (draws/plays/counters) + life→main ( dégâts leader).
    Approximatif (≈), garde-fou si négatif. Snapshot adverse absent -> hand_count None avant."""
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = _live_match(srv, opp_leader="OP09-001")
    # Mapping RZ1 n° joueur -> tag (résolu en live via la main de mulligan).
    st._player_to_tag = {1: "Me#1", 2: "Foe#2"}
    st.opp.life = None
    # Opp (joueur RZ1 n°2) : 5 pioches (main de départ) puis 1 pose.
    for i, cid in enumerate(["OP09-002", "OP09-009", "OP09-011", "OP09-015", "OP09-004"], 1):
        st.feed_line(f"RZ1|{i}|2|{cid}|0|45|1|0|0|1|0|0|0")
    st.feed_line("RZ1|99|2|OP09-002|1|44|2|0|0|1|0|0|0")  # pose board -> -1
    # net RZ1 = 5 - 1 = 4, aucun dégât -> main ≈ 4.
    p = srv._state_payload()
    assert p["opp"]["hand_count"] == 4
    assert p["opp"]["hand_count_approx"] is True
    # 2 dégâts sur le leader adverse -> 2 life cards en main (non émises en RZ1) -> +2.
    st.feed_line('Shanks [<mark><link="OP09-001">OP09-001</link></mark>] hit for 1 damage')
    st.feed_line('Shanks [<mark><link="OP09-001">OP09-001</link></mark>] hit for 1 damage')
    assert srv._state_payload()["opp"]["hand_count"] == 6


def test_leader_damage_tracked_from_hit_lines():
    """Les lignes globales 'hit for N damage' cumulent les dégâts par leader (card_id)."""
    from optcgsim_haki.live import LiveState
    s = LiveState()
    s.feed_line('Shanks [<mark><link="OP09-001">OP09-001</link></mark>] hit for 2 damage')
    s.feed_line('Sanji [<mark><link="PRB01-001">PRB01-001</link></mark>] hit for 1 damage')
    s.feed_line('Shanks [<mark><link="OP09-001">OP09-001</link></mark>] hit for 1 damage')
    assert s.leader_damage("OP09-001") == 3
    assert s.leader_damage("PRB01-001") == 1
    assert s.leader_damage("OP99-999") == 0
    assert s.leader_damage(None) == 0




# ---------------------------------------------------------------------------
# Tests _compute_lethal : algorithme glouton de lethal OPTCG.
# ---------------------------------------------------------------------------

def test_compute_lethal_simple_overwhelm():
    """Attaquant écrase : 3 attaques à 9000 vs défenseur life=2, leader 5000, 0 blocker, 0 counter.
    Chaque attaque > leader power → 3 life perdues → lethal (3 >= 2)."""
    r = _compute_lethal(atk_leader_power=9000, atk_board=[(9000, False), (9000, False)],
                        def_life=2, def_leader_power=5000, def_blockers=0, def_counter_pool=0)
    assert r["can_lethal"] is True
    assert r["lives_dealt"] == 3
    assert r["n_attacks"] == 3


def test_compute_lethal_blocked_by_blockers():
    """3 attaques mais 2 blockers → 1 attaque passe → 1 life perdue → pas lethal si life=2."""
    r = _compute_lethal(atk_leader_power=9000, atk_board=[(9000, False), (9000, False)],
                        def_life=2, def_leader_power=5000, def_blockers=2, def_counter_pool=0)
    assert r["can_lethal"] is False
    assert r["lives_dealt"] == 1


def test_compute_lethal_countered():
    """Attaques 7000 vs leader 5000 : besoin de 2000 counter par attaque.
    3 attaques, 4000 counter → 2 contrées, 1 passe → pas lethal si life=2."""
    r = _compute_lethal(atk_leader_power=7000, atk_board=[(7000, False), (7000, False)],
                        def_life=2, def_leader_power=5000, def_blockers=0, def_counter_pool=4000)
    assert r["can_lethal"] is False
    assert r["lives_dealt"] == 1


def test_compute_lethal_double_attack():
    """Double Attack = 2 attaques pour 1 personnage. 1 leader + 1 char dbl_atk = 3 attaques."""
    r = _compute_lethal(atk_leader_power=6000, atk_board=[(8000, True)],
                        def_life=3, def_leader_power=5000, def_blockers=0, def_counter_pool=0)
    # Attaques : [8000, 8000, 6000] → toutes > 5000 → 3 life perdues → lethal.
    assert r["can_lethal"] is True
    assert r["lives_dealt"] == 3
    assert r["n_attacks"] == 3


def test_compute_lethal_leader_wins_clash_naturally():
    """Attaque 4000 vs leader 5000 : le leader gagne le clash sans counter → 0 life perdue."""
    r = _compute_lethal(atk_leader_power=4000, atk_board=[],
                        def_life=1, def_leader_power=5000, def_blockers=0, def_counter_pool=0)
    assert r["can_lethal"] is False
    assert r["lives_dealt"] == 0


def test_compute_lethal_insufficient_data():
    """Pas de leader power ou pas de vie → None."""
    assert _compute_lethal(None, [], def_life=5, def_leader_power=5000,
                           def_blockers=0, def_counter_pool=0) is None
    assert _compute_lethal(5000, [], def_life=None, def_leader_power=5000,
                           def_blockers=0, def_counter_pool=0) is None
    assert _compute_lethal(5000, [], def_life=0, def_leader_power=5000,
                           def_blockers=0, def_counter_pool=0) is None


def test_compute_lethal_greedy_blocker_assignment():
    """L'algorithme doit bloquer les attaques les plus fortes en priorité.
    Attaques [10000, 5000] vs leader 5000, 1 blocker :
    - Blocker absorbe le 10000 → 5000 vs leader 5000 → leader gagne → 0 life perdue."""
    r = _compute_lethal(atk_leader_power=10000, atk_board=[(5000, False)],
                        def_life=1, def_leader_power=5000, def_blockers=1, def_counter_pool=0)
    assert r["can_lethal"] is False
    assert r["lives_dealt"] == 0


# ---------------------------------------------------------------------------
# Tests payload lethal : intégration dans _state_payload.
# ---------------------------------------------------------------------------

def _seed_card_stats(path):
    """Force les power/blocker/dbl_atk/counter en SQL direct (contourne le COALESCE de
    import_card_stats qui ne met pas à jour power si déjà renseigné par card_stats.json)."""
    with Store(path) as st:
        stats = {
            "L1":       (5000, 0, 0, 0, 0, "Leader"),
            "OP09-001": (5000, 0, 0, 0, 0, "Leader"),
            "OP09-002": (9000, 2000, 0, 0, 0, "Character"),
            "OP09-009": (7000, 0, 1, 0, 0, "Character"),
            "OP09-004": (6000, 1000, 0, 0, 1, "Character"),
        }
        for cid, (pw, ctr, blk, rush, dbl, ctype) in stats.items():
            st.conn.execute(
                "INSERT OR IGNORE INTO cards (card_id, set_code) VALUES (?,?)",
                (cid, cid.split("-", 1)[0]),
            )
            st.conn.execute(
                "UPDATE cards SET power=?, counter=?, has_blocker=?, has_rush=?, "
                "has_dbl_atk=?, card_type=? WHERE card_id=?",
                (pw, ctr, blk, rush, dbl, ctype, cid),
            )
        st.conn.commit()


def test_state_payload_lethal_opp_can_lethal(tmp_path):
    """L'adversaire a 2 chars 9000 sur le board + leader 5000, j'ai life=2, 0 blocker, 0 counter.
    Attaques [9000, 9000, 5000] vs mon leader 5000 : le 5000 est absorbé (leader gagne le clash).
    → 2 life perdues → opp_can_lethal=True (2 >= 2)."""
    db = tmp_path / "t.db"
    _seed_db(db)
    _seed_card_stats(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = _live_match(srv, me_leader="L1", opp_leader="OP09-001")
    st.opp.life = None  # live : pas de snapshot adverse → calculé depuis base - dommages
    st.me.life = 2
    # Board adverse : 2 chars à 9000 power.
    st.opp.board_ids = ["OP09-002", "OP09-002"]
    # Mon board vide, ma main vide.
    st.me.board_ids = []
    st.me.hand_ids = []
    st.me.hand_count_known = True
    p = srv._state_payload()
    assert "lethal" in p
    assert p["lethal"]["opp_can_lethal"] is True
    assert p["lethal"]["lives_at_risk"] == 2  # 9000+9000 passent, 5000 absorbé par leader
    assert p["lethal"]["opp_power"] == 23000  # 5000 + 9000 + 9000


def test_state_payload_lethal_safe_with_blockers(tmp_path):
    """Même board adverse, mais j'ai 2 blockers → 2 attaques bloquées, la 3e (5000) est
    absorbée par mon leader 5000 → 0 life perdue → pas lethal."""
    db = tmp_path / "t.db"
    _seed_db(db)
    _seed_card_stats(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = _live_match(srv, me_leader="L1", opp_leader="OP09-001")
    st.opp.life = None
    st.me.life = 2
    st.opp.board_ids = ["OP09-002", "OP09-002"]
    # Mon board : 2 blockers (OP09-009 a blocker=True).
    st.me.board_ids = ["OP09-009", "OP09-009"]
    st.me.hand_ids = []
    st.me.hand_count_known = True
    p = srv._state_payload()
    assert p["lethal"]["opp_can_lethal"] is False
    assert p["lethal"]["lives_at_risk"] == 0  # 2 bloquées + 1 absorbée par leader
    assert p["lethal"]["my_blockers"] == 2


def test_state_payload_lethal_me_can_lethal(tmp_path):
    """Mon tour : leader 5000 + 1 char dbl_atk 6000 = 3 attaques vs opp life=1, 0 blocker, 0 counter.
    Attaques [6000, 6000, 5000] vs leader adverse 5000 : le 5000 est absorbé.
    → 2 life infligées → me_can_lethal=True (2 >= 1)."""
    db = tmp_path / "t.db"
    _seed_db(db)
    _seed_card_stats(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = _live_match(srv, me_leader="L1", opp_leader="OP09-001")
    st.opp.life = 1
    st.me.life = 5
    # Mon board : 1 char dbl_atk à 6000.
    st.me.board_ids = ["OP09-004"]
    st.me.hand_ids = []
    st.me.hand_count_known = True
    # Board adverse vide.
    st.opp.board_ids = []
    p = srv._state_payload()
    assert p["lethal"]["me_can_lethal"] is True
    assert p["lethal"]["lives_i_can_deal"] == 2  # 6000+6000 passent, 5000 absorbé par leader adverse
    assert p["lethal"]["me_attacks"] == 3


def test_state_payload_lethal_with_counters_in_hand(tmp_path):
    """Mes counters en main réduisent le danger : opp attaque 7000, mon leader 5000,
    j'ai 2000 counter en main → je gagne le clash → 0 life perdue."""
    db = tmp_path / "t.db"
    _seed_db(db)
    _seed_card_stats(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = _live_match(srv, me_leader="L1", opp_leader="OP09-001")
    st.opp.life = None
    st.me.life = 1
    # Board adverse : 1 char à 7000.
    st.opp.board_ids = ["OP09-009"]
    # Ma main : 1 carte avec 2000 counter (OP09-002).
    st.me.board_ids = []
    st.me.hand_ids = ["OP09-002"]
    st.me.hand_count_known = True
    p = srv._state_payload()
    # Attaques : [7000, 5000]. Leader 5000 gagne le 5000. Le 7000 : 5000+2000=7000 → gagne → 0 life.
    assert p["lethal"]["opp_can_lethal"] is False
    assert p["lethal"]["lives_at_risk"] == 0
    assert p["lethal"]["my_counter_pool"] == 2000


def test_state_payload_lethal_absent_without_card_stats(tmp_path):
    """Sans power dans la DB pour les leaders → _compute_lethal retourne None → pas de payload."""
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    # Leaders fictifs absents de card_stats.json → power NULL en DB.
    st = _live_match(srv, me_leader="ZZ1-001", opp_leader="ZZ1-002")
    st.me.life = 5
    st.opp.life = 5
    p = srv._state_payload()
    assert "lethal" not in p


# --- Tests du solveur de lethal (_solve_lethal) ---

def test_don_cost_basic():
    """Coût en DON!! pour atteindre une puissance cible."""
    assert _don_cost(5000, 5000) == 0   # déjà assez fort
    assert _don_cost(5000, 6000) == 1   # +1 DON
    assert _don_cost(5000, 7000) == 2   # +2 DON
    assert _don_cost(5000, 4000) == 0   # target plus bas → 0 DON
    assert _don_cost(3000, 9000) == 6   # +6 DON


def test_solve_lethal_simple():
    """Lethal simple : 1 attaquant à 5000, 1 vie adverse, leader 5000, 0 blocker, 0 counter, 0 DON.
    N_requis = 1 + 0 + 1 = 2 attaquants → board trop faible."""
    result = _solve_lethal(
        attackers_power=[5000],
        available_don=0,
        def_leader_power=5000,
        def_life=1,
        def_blockers=0,
        def_counter_pool=0,
    )
    assert result is not None
    assert result["is_lethal"] is False
    assert "Board trop faible" in result["reason"]


def test_solve_lethal_two_attackers_no_don():
    """2 attaquants à 6000, 1 vie, leader 5000, 0 blocker, 0 counter, 0 DON.
    N_requis = 2. Cibles = [5000, 5000]. Attaquants = [6000, 6000].
    Coût DON = 0 + 0 = 0 ≤ 0 → lethal.
    Sans counter, le coup de grâce est la cible la plus haute = 5000 (même que vie).
    Role assigné : i=0 pas coup_de_grace (counter=0), donc 'life'. i=1 aussi 'life'."""
    result = _solve_lethal(
        attackers_power=[6000, 6000],
        available_don=0,
        def_leader_power=5000,
        def_life=1,
        def_blockers=0,
        def_counter_pool=0,
    )
    assert result is not None
    assert result["is_lethal"] is True
    assert result["don_needed"] == 0
    assert len(result["attack_plan"]) == 2
    # Sans counter, toutes les cibles sont égales (5000) → pas de coup_de_grace distingué
    assert all(s["role"] in ("life", "coup_de_grace") for s in result["attack_plan"])


def test_solve_lethal_needs_don():
    """2 attaquants à 4000, 1 vie, leader 5000, 0 blocker, 0 counter, 2 DON.
    N_requis = 2. Cibles = [5000, 5000]. Coût = 1 + 1 = 2 DON ≤ 2 → lethal."""
    result = _solve_lethal(
        attackers_power=[4000, 4000],
        available_don=2,
        def_leader_power=5000,
        def_life=1,
        def_blockers=0,
        def_counter_pool=0,
    )
    assert result is not None
    assert result["is_lethal"] is True
    assert result["don_needed"] == 2
    assert result["attack_plan"][0]["don_attached"] == 1
    assert result["attack_plan"][0]["final_power"] == 5000


def test_solve_lethal_not_enough_don():
    """2 attaquants à 4000, 1 vie, leader 5000, 0 blocker, 0 counter, 1 DON.
    Coût = 2 DON > 1 → non lethal."""
    result = _solve_lethal(
        attackers_power=[4000, 4000],
        available_don=1,
        def_leader_power=5000,
        def_life=1,
        def_blockers=0,
        def_counter_pool=0,
    )
    assert result is not None
    assert result["is_lethal"] is False
    assert "1 DON" in result["reason"]


def test_solve_lethal_with_blockers():
    """3 attaquants à 6000, 1 vie, leader 5000, 1 blocker, 0 counter, 0 DON.
    N_requis = 1 + 1 + 1 = 3. Cibles = [5000, 5000, 5000]. Coût = 0 → lethal.
    Sans counter, pas de coup_de_grace. i=0 → 'life' (pas blocker car counter=0, i >= 0+0).
    Wait : i=0, counter=0 → pas coup_de_grace. i < def_blockers + 0 = 1 → i=0 < 1 → 'blocker'."""
    result = _solve_lethal(
        attackers_power=[6000, 6000, 6000],
        available_don=0,
        def_leader_power=5000,
        def_life=1,
        def_blockers=1,
        def_counter_pool=0,
    )
    assert result is not None
    assert result["is_lethal"] is True
    assert len(result["attack_plan"]) == 3
    # La première attaque doit être sur le blocker (i=0 < 1 blocker)
    assert result["attack_plan"][0]["role"] == "blocker"


def test_solve_lethal_with_counter():
    """2 attaquants à 6000, 1 vie, leader 5000, 0 blocker, 2000 counter, 0 DON.
    N_requis = 2. Cibles = [5000, 7000]. Attaquants triés = [6000, 6000].
    Coût = max(0, ceil((5000-6000)/1000)) + max(0, ceil((7000-6000)/1000)) = 0 + 1 = 1.
    Avec 0 DON → non lethal."""
    result = _solve_lethal(
        attackers_power=[6000, 6000],
        available_don=0,
        def_leader_power=5000,
        def_life=1,
        def_blockers=0,
        def_counter_pool=2000,
    )
    assert result is not None
    assert result["is_lethal"] is False
    assert "1 DON" in result["reason"]


def test_solve_lethal_with_counter_and_don():
    """Même scenario que ci-dessus mais avec 1 DON → lethal.
    Cibles triées = [7000, 5000]. Attaquants triés = [6000, 6000].
    Coût = max(0, ceil((7000-6000)/1000)) + max(0, ceil((5000-6000)/1000)) = 1 + 0 = 1 ≤ 1.
    Le coup de grâce (i=0, counter>0) est associé à la cible 7000."""
    result = _solve_lethal(
        attackers_power=[6000, 6000],
        available_don=1,
        def_leader_power=5000,
        def_life=1,
        def_blockers=0,
        def_counter_pool=2000,
    )
    assert result is not None
    assert result["is_lethal"] is True
    assert result["don_needed"] == 1
    # Le coup de grâce (i=0) doit avoir la cible 7000 (leader + counter)
    coup = [s for s in result["attack_plan"] if s["role"] == "coup_de_grace"][0]
    assert coup["target_power"] == 7000
    assert coup["don_attached"] == 1
    assert coup["final_power"] == 7000


def test_solve_lethal_three_lives():
    """4 attaquants à 8000, 3 vies, leader 5000, 0 blocker, 0 counter, 0 DON.
    N_requis = 3 + 0 + 1 = 4. Cibles = [5000, 5000, 5000, 5000]. Coût = 0 → lethal."""
    result = _solve_lethal(
        attackers_power=[8000, 8000, 8000, 8000],
        available_don=0,
        def_leader_power=5000,
        def_life=3,
        def_blockers=0,
        def_counter_pool=0,
    )
    assert result is not None
    assert result["is_lethal"] is True
    assert len(result["attack_plan"]) == 4


def test_solve_lethal_none_life():
    """Vie à None → retourne None."""
    result = _solve_lethal(
        attackers_power=[5000],
        available_don=5,
        def_leader_power=5000,
        def_life=None,
        def_blockers=0,
        def_counter_pool=0,
    )
    assert result is None


def test_solve_lethal_optimal_allocation():
    """Test de l'allocation optimale : gros attaqueur sur grosse cible.
    2 attaquants [3000, 9000], 1 vie, leader 5000, 0 blocker, 3000 counter, 3 DON.
    Cibles triées = [8000, 5000]. Attaquants triés = [9000, 3000].
    Coût = max(0, ceil((8000-9000)/1000)) + max(0, ceil((5000-3000)/1000)) = 0 + 2 = 2 ≤ 3.
    L'allocation gloutonne associe 9000 → 8000 (coup de grâce, 0 DON) et 3000 → 5000 (vie, 2 DON)."""
    result = _solve_lethal(
        attackers_power=[3000, 9000],
        available_don=3,
        def_leader_power=5000,
        def_life=1,
        def_blockers=0,
        def_counter_pool=3000,
    )
    assert result is not None
    assert result["is_lethal"] is True
    assert result["don_needed"] == 2
    # Vérifier que le 9000 est associé à la cible 8000 (coup de grâce, i=0)
    coup = [s for s in result["attack_plan"] if s["role"] == "coup_de_grace"][0]
    assert coup["attacker_power"] == 9000
    assert coup["target_power"] == 8000
    assert coup["don_attached"] == 0


# --- Tests du Modifier Engine ---

def test_modifier_engine_get_current_power_add():
    """get_current_power : ADD modificateur ajoute à la power de base."""
    from optcgsim_haki.live import LiveState, LivePlayer, Modifier
    st = LiveState()
    p = LivePlayer(tag="Alice", side="me", leader="PRB01-001")
    # Buff +2000 sur le leader
    st._apply_modifier(p, "PRB01-001", Modifier(
        source_id="EB04-004", mod_type="ADD", value=2000,
        expiry="END_OF_NEXT_TURN", applied_at_turn=5, applied_by_side="me"))
    assert st.get_current_power(p, "PRB01-001", 5000) == 7000


def test_modifier_engine_get_current_power_set_base():
    """get_current_power : SET_BASE remplace la power de base."""
    from optcgsim_haki.live import LiveState, LivePlayer, Modifier
    st = LiveState()
    p = LivePlayer(tag="Alice", side="me", leader="L1")
    # SET_BASE = 7000
    st._apply_modifier(p, "L1", Modifier(
        source_id="X", mod_type="SET_BASE", value=7000,
        expiry="END_OF_CURRENT_TURN", applied_at_turn=3, applied_by_side="me"))
    assert st.get_current_power(p, "L1", 5000) == 7000


def test_modifier_engine_set_base_plus_add():
    """SET_BASE écrase la base, puis ADD s'ajoute : (7000) + 2000 = 9000."""
    from optcgsim_haki.live import LiveState, LivePlayer, Modifier
    st = LiveState()
    p = LivePlayer(tag="Alice", side="me", leader="L1")
    st._apply_modifier(p, "L1", Modifier(
        source_id="X", mod_type="SET_BASE", value=7000,
        expiry="END_OF_CURRENT_TURN", applied_at_turn=3, applied_by_side="me"))
    st._apply_modifier(p, "L1", Modifier(
        source_id="Y", mod_type="ADD", value=2000,
        expiry="END_OF_CURRENT_TURN", applied_at_turn=3, applied_by_side="me"))
    assert st.get_current_power(p, "L1", 5000) == 9000


def test_modifier_engine_set_base_last_wins():
    """Si plusieurs SET_BASE, le dernier écrase les précédents."""
    from optcgsim_haki.live import LiveState, LivePlayer, Modifier
    st = LiveState()
    p = LivePlayer(tag="Alice", side="me", leader="L1")
    st._apply_modifier(p, "L1", Modifier(
        source_id="X", mod_type="SET_BASE", value=7000,
        expiry="END_OF_CURRENT_TURN", applied_at_turn=3, applied_by_side="me"))
    st._apply_modifier(p, "L1", Modifier(
        source_id="Y", mod_type="SET_BASE", value=9000,
        expiry="END_OF_CURRENT_TURN", applied_at_turn=4, applied_by_side="me"))
    assert st.get_current_power(p, "L1", 5000) == 9000


def test_modifier_engine_gc_end_of_current_turn():
    """GC : END_OF_CURRENT_TURN expire à la fin du tour du camp qui a appliqué."""
    from optcgsim_haki.live import LiveState, Modifier
    st = LiveState()
    st.me_tag = "Alice#0001"
    p = st._player("Alice#0001")
    p.side = "me"
    p.leader = "L1"
    st._apply_modifier(p, "L1", Modifier(
        source_id="X", mod_type="ADD", value=2000,
        expiry="END_OF_CURRENT_TURN", applied_at_turn=5, applied_by_side="me"))
    # Avant GC : buff actif
    assert st.get_current_power(p, "L1", 5000) == 7000
    # GC fin du tour me -> expire
    st._active_side = "me"
    st._gc_modifiers()
    assert st.get_current_power(p, "L1", 5000) == 5000


def test_modifier_engine_gc_end_of_next_turn():
    """GC : END_OF_NEXT_TURN expire à la fin du tour adverse, pas avant."""
    from optcgsim_haki.live import LiveState, Modifier
    st = LiveState()
    st.me_tag = "Alice#0001"
    p = st._player("Alice#0001")
    p.side = "me"
    p.leader = "L1"
    st._apply_modifier(p, "L1", Modifier(
        source_id="X", mod_type="ADD", value=2000,
        expiry="END_OF_NEXT_TURN", applied_at_turn=5, applied_by_side="me"))
    # GC fin du tour me -> ne PAS expirer (c'est le "next turn" = tour opp)
    st._active_side = "me"
    st._gc_modifiers()
    assert st.get_current_power(p, "L1", 5000) == 7000
    # GC fin du tour opp -> expirer
    st._active_side = "opp"
    st._gc_modifiers()
    assert st.get_current_power(p, "L1", 5000) == 5000


def test_modifier_engine_gc_permanent():
    """GC : PERMANENT ne expire jamais."""
    from optcgsim_haki.live import LiveState, Modifier
    st = LiveState()
    st.me_tag = "Alice#0001"
    p = st._player("Alice#0001")
    p.side = "me"
    p.leader = "L1"
    st._apply_modifier(p, "L1", Modifier(
        source_id="X", mod_type="ADD", value=1000,
        expiry="PERMANENT", applied_at_turn=1, applied_by_side="me"))
    st._active_side = "me"
    st._gc_modifiers()
    st._active_side = "opp"
    st._gc_modifiers()
    assert st.get_current_power(p, "L1", 5000) == 6000


def test_modifier_engine_parse_expiry():
    """_parse_expiry interprète correctement les textes d'expiry."""
    from optcgsim_haki.live import LiveState
    assert LiveState._parse_expiry("opponent's next turn end", "me") == "END_OF_NEXT_TURN"
    # « your/my next turn » = propre prochain tour de l'applicateur (distinct de l'adverse).
    assert LiveState._parse_expiry("your next turn end", "me") == "END_OF_OWN_NEXT_TURN"
    assert LiveState._parse_expiry("my next turn end", "me") == "END_OF_OWN_NEXT_TURN"
    assert LiveState._parse_expiry("next turn end", "me") == "END_OF_NEXT_TURN"
    assert LiveState._parse_expiry("this turn end", "me") == "END_OF_CURRENT_TURN"
    assert LiveState._parse_expiry("during this turn", "me") == "END_OF_CURRENT_TURN"
    assert LiveState._parse_expiry("this battle", "me") == "END_OF_CURRENT_TURN"


def test_modifier_engine_own_next_turn_gc():
    """END_OF_OWN_NEXT_TURN survit au tour adverse et expire au propre tour suivant."""
    from optcgsim_haki.live import LiveState, Modifier
    st = LiveState()
    st.me_tag = "Alice#0001"
    st.opp_tag = "Bob#0002"
    me = st._player("Alice#0001"); me.side = "me"; me.leader = "L1"
    opp = st._player("Bob#0002"); opp.side = "opp"
    # Buff appliqué par me au tour 1 (self._turn == 1).
    st._apply_modifier(me, "L1", Modifier(
        source_id="X", mod_type="ADD", value=2000,
        expiry="END_OF_OWN_NEXT_TURN", applied_at_turn=1, applied_by_side="me"))

    # Fin du tour de me (tour courant) : ne doit PAS expirer.
    st.feed_line("[Alice#0001] End Turn")
    assert st.get_current_power(me, "L1", 5000) == 7000
    # Fin du tour adverse : ne doit PAS expirer non plus.
    st.feed_line("[Bob#0002] End Turn")
    assert st.get_current_power(me, "L1", 5000) == 7000
    # Fin du PROPRE prochain tour de me : expire.
    st.feed_line("[Alice#0001] End Turn")
    assert st.get_current_power(me, "L1", 5000) == 5000


def test_modifier_engine_large_grant_is_add():
    """Un gros Grant (>= 5000) reste un ADD : le log émet un delta, pas une base absolue.

    Régression de l'ancien seuil « >= 5000 -> SET_BASE » qui écrasait la base avec le delta
    (un +6000 ponctuel devenait base=6000 au lieu de 5000+6000=11000) -> lethal manqué.
    """
    from optcgsim_haki.live import LiveState
    st = LiveState()
    st.me_tag = "Alice#0001"; st.opp_tag = "Bob#0002"
    me = st._player("Alice#0001"); me.side = "me"; me.leader = "OP01-001"
    opp = st._player("Bob#0002"); opp.side = "opp"

    line = ('[Alice#0001] Finisher [<mark><link="XX01-001">XX01-001</link></mark>]: '
            'Grant Leader [<mark><link="OP01-001">OP01-001</link></mark>] '
            "6000 until this turn end")
    st.feed_line(line)
    mod = st.me.modifiers["OP01-001"][0]
    assert mod.mod_type == "ADD"
    # ADD : 5000 + 6000 = 11000 (et non base écrasée à 6000).
    assert st.get_current_power(st.me, "OP01-001", 5000) == 11000


def test_modifier_engine_feed_line_grant():
    """feed_line capture un buff 'Grant ... 2000 until opponent's next turn end'."""
    from optcgsim_haki.live import LiveState
    st = LiveState()
    st.me_tag = "Alice#0001"
    st.opp_tag = "Bob#0002"
    me = st._player("Alice#0001")
    me.side = "me"
    me.leader = "PRB01-001"
    me.board_ids = ["EB04-004"]
    opp = st._player("Bob#0002")
    opp.side = "opp"
    opp.leader = "OP09-001"

    line = ('[Alice#0001] Zeff [<mark><link="EB04-004">EB04-004</link></mark>]: '
            'Grant Sanji [<mark><link="PRB01-001">PRB01-001</link></mark>] '
            "2000 until opponent's next turn end")
    st.feed_line(line)

    # Le buff doit être sur le leader me (PRB01-001)
    mods = me.modifiers.get("PRB01-001", [])
    assert len(mods) == 1
    assert mods[0].source_id == "EB04-004"
    assert mods[0].mod_type == "ADD"
    assert mods[0].value == 2000
    assert mods[0].expiry == "END_OF_NEXT_TURN"
    assert st.get_current_power(me, "PRB01-001", 5000) == 7000


def test_modifier_engine_feed_line_end_turn_gc():
    """feed_line déclenche la GC sur 'End Turn' et fait expirer les buffs."""
    from optcgsim_haki.live import LiveState, Modifier
    st = LiveState()
    st.me_tag = "Alice#0001"
    st.opp_tag = "Bob#0002"
    me = st._player("Alice#0001")
    me.side = "me"
    me.leader = "PRB01-001"
    opp = st._player("Bob#0002")
    opp.side = "opp"

    # Buff END_OF_CURRENT_TURN appliqué par me
    st._apply_modifier(me, "PRB01-001", Modifier(
        source_id="X", mod_type="ADD", value=2000,
        expiry="END_OF_CURRENT_TURN", applied_at_turn=1, applied_by_side="me"))
    assert st.get_current_power(me, "PRB01-001", 5000) == 7000

    # End Turn par me -> GC doit expirer le buff
    st.feed_line("[Alice#0001] End Turn")
    assert st.get_current_power(me, "PRB01-001", 5000) == 5000


def test_modifier_engine_fixture_log():
    """Le log de fixture capture le buff Zeff -> Sanji (+2000)."""
    from optcgsim_haki.live import LiveState
    st = LiveState()
    with open(FIXTURES / "match_autosaved.log") as f:
        for line in f:
            st.feed_line(line)
    # Le buff doit être présent sur le leader me (Sanji PRB01-001)
    me = st.me
    assert me is not None
    mods = me.modifiers.get("PRB01-001", [])
    assert len(mods) == 1
    assert mods[0].value == 2000
    assert st.get_current_power(me, "PRB01-001", 5000) == 7000


def test_modifier_engine_to_dict_exports_modifiers():
    """to_dict exporte les modificateurs dans le payload API."""
    from optcgsim_haki.live import LiveState, Modifier
    st = LiveState()
    st.me_tag = "Alice#0001"
    me = st._player("Alice#0001")
    me.side = "me"
    me.leader = "L1"
    st._apply_modifier(me, "L1", Modifier(
        source_id="X", mod_type="ADD", value=2000,
        expiry="END_OF_NEXT_TURN", applied_at_turn=3, applied_by_side="me"))
    d = st.to_dict()
    me_d = d["me"]
    assert "modifiers" in me_d
    assert "L1" in me_d["modifiers"]


# ---------------------------------------------------------------------------
# Solo vs Self
# ---------------------------------------------------------------------------

def test_solo_vs_self_detects_mode_and_assigns_sides():
    """En Solo vs Self, le tag shuffle est vide -> is_solo=True, tags synthétiques."""
    from optcgsim_haki.live import LiveState
    st = LiveState()
    st.feed_line("shuffle deck for ")
    assert st.is_solo
    assert st.me_tag == "solo_p1"
    assert st.opp_tag == "solo_p2"
    assert st.active


def test_solo_vs_self_correlates_hands_and_snapshots():
    """Solo vs Self : "Hand after Mulligan" + snapshots [] sont attribués aux bons joueurs
    via corrélation avec les pioches RZ1."""
    from optcgsim_haki.live import LiveState
    fixture = FIXTURES / "solo_vs_self.log"
    st = LiveState()
    for line in fixture.read_text().splitlines():
        st.feed_line(line)

    assert st.is_solo
    assert st.me_tag == "solo_p1"
    assert st.opp_tag == "solo_p2"

    # Les n° joueurs RZ1 sont mappés sur les tags synthétiques.
    assert st._player_to_tag.get(1) == "solo_p1"
    assert st._player_to_tag.get(2) == "solo_p2"

    me = st.me
    opp = st.opp
    assert me is not None and opp is not None

    # Mains post-mulligan attribuées correctement.
    assert me.hand_count_known
    assert set(me.hand_ids) == {"EB04-004", "OP06-007", "PRB02-003", "OP14-018"}
    # OP16-018 a été jouée (RZ1 33) -> retirée de la main.
    assert "OP16-018" not in me.hand_ids
    assert "OP16-018" in me.board_ids

    assert opp.hand_count_known
    assert set(opp.hand_ids) == {"ST21-017", "OP12-014", "OP16-003", "OP12-006", "OP12-018"}

    # Vies lues depuis les snapshots [].
    assert me.life == 5
    assert opp.life == 5

    # DON sur le terrain (RZ1).
    assert me.don_on_field is not None and me.don_on_field >= 1
    assert opp.don_on_field is not None and opp.don_on_field >= 1

    # Deck restant.
    assert me.deck_remaining is not None
    assert opp.deck_remaining is not None


def test_solo_vs_self_to_dict_exposes_both_hands():
    """En Solo vs Self, les deux mains sont locales -> exposées même sans reveal_all."""
    from optcgsim_haki.live import LiveState
    fixture = FIXTURES / "solo_vs_self.log"
    st = LiveState()
    for line in fixture.read_text().splitlines():
        st.feed_line(line)
    d = st.to_dict(reveal_all=False)
    # Les deux joueurs sont locaux en Solo vs Self -> main toujours visible.
    assert d["me"]["hand"] is not None
    assert d["opp"]["hand"] is not None
    assert len(d["me"]["hand"]) == 4   # 5 cartes - 1 jouée
    assert len(d["opp"]["hand"]) == 5


def test_solo_vs_self_new_match_reset():
    """Un nouveau shuffle après gameplay déclenche un reset, même en Solo vs Self."""
    from optcgsim_haki.live import LiveState
    st = LiveState()
    st.feed_line("shuffle deck for ")
    st.feed_line("start action phase for player (0), curr state is PlayerTurn_Action")
    assert st._played
    assert st.is_solo
    # Nouveau shuffle -> reset
    st.feed_line("shuffle deck for ")
    assert st.is_solo  # re-détecté après reset
    assert st.active


def test_counters_spent_tracked_per_player():
    """"Discard ... for Counter N" est un événement public : comptage exact par joueur
    (nombre + somme des valeurs), exposé dans to_dict."""
    from optcgsim_haki.live import LiveState
    s = LiveState()
    s.feed_line("shuffle deck for Foe#2222")
    s.feed_line("shuffle deck for Me#0000")
    s.feed_line("[ReplaySync] RZ1|1|1|OP01-001|0|49|1|0|1|1|0|0|0")
    s.feed_line("Hand before Mulligan: [OP01-001]")
    assert s.me_tag == "Me#0000" and s.opp_tag == "Foe#2222"

    s.feed_line('[Foe#2222] Discard Koby [<mark><link="PRB02-001">PRB02-001</link></mark>] for Counter 1000')
    s.feed_line('[Foe#2222] Discard Hongo [<mark><link="OP09-011">OP09-011</link></mark>] for Counter 2000')
    s.feed_line('[Me#0000] Discard Lucky Roux [<mark><link="PRB02-003">PRB02-003</link></mark>] for Counter 1000')

    d = s.to_dict()
    assert d["opp"]["counters_spent"] == {"count": 2, "total": 3000}
    assert d["me"]["counters_spent"] == {"count": 1, "total": 1000}


def test_counters_spent_not_confused_with_board_removal():
    """Un counter défaussé ne doit toujours PAS être compté comme retrait de board."""
    from optcgsim_haki.live import LiveState
    s = LiveState()
    s.feed_line("shuffle deck for Foe#2222")
    s.feed_line("shuffle deck for Me#0000")
    s.feed_line("[ReplaySync] RZ1|1|1|OP01-001|0|49|1|0|1|1|0|0|0")
    s.feed_line("Hand before Mulligan: [OP01-001]")
    # L'adversaire pose PRB02-001 puis défausse un AUTRE exemplaire en counter.
    s.feed_line("[ReplaySync] RZ1|2|2|PRB02-001|1|0|2|0|0|1|0|0|0")
    board_before = list(s.opp.board_ids)
    s.feed_line('[Foe#2222] Discard Koby [<mark><link="PRB02-001">PRB02-001</link></mark>] for Counter 1000')
    assert list(s.opp.board_ids) == board_before
    assert s.opp.counters_spent_count == 1


def test_playing_with_deck_and_v3_actions_tracked():
    """'Playing with deck' (mon deck exact) et 'Start Using V3 Action' (ids agissants,
    dont les leaders) sont captés ; le deck survit au reset (sélection avant shuffles)."""
    from optcgsim_haki.live import LiveState
    s = LiveState()
    s.feed_line("Playing with deck: 0Sanji 8k OP16")
    s.feed_line('Start Using V3 Action [Portgas D. Ace [<mark><link="OP16-001">OP16-001</link></mark>]]<0>')
    s.feed_line('Queue up V3 Action [Nami [<mark><link="OP01-016">OP01-016</link></mark>]]<0>(1)]')  # pas "Start Using" -> ignoré
    assert s.my_deck_name == "0Sanji 8k OP16"
    assert s.v3_action_ids == {"OP16-001"}
    s.reset_match()
    assert s.my_deck_name == "0Sanji 8k OP16"   # survit (décrit la partie qui démarre)
    assert s.v3_action_ids == set()             # remis à zéro par partie


def test_observed_opp_leader_beats_archetype_inference(tmp_path):
    """Le leader adverse OBSERVÉ (action V3 + type leader) prime sur l'inférence d'archétype
    — régression : l'inférence affichait Luffy alors qu'Ace [OP16-001] agissait dans le log."""
    class _Meta:
        def __init__(self, life): self.life = life

    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    # card_meta contrôlé : OP16-001 (Ace) et PRB01-001 (mon Sanji) sont des leaders.
    srv.card_meta = {"OP16-001": _Meta(5), "PRB01-001": _Meta(5), "OP01-016": _Meta(None)}
    st = _live_match(srv, me_leader="PRB01-001", opp_leader=None)
    # Cartes publiques adverses qui feraient inférer Shanks (deck OP09 du seed)...
    st._player("Foe#2").board_ids = ["OP09-002", "OP09-009"]
    # ...mais le leader adverse AGIT : observation exacte.
    st.feed_line('Start Using V3 Action [Portgas D. Ace [<mark><link="OP16-001">OP16-001</link></mark>]]<0>')

    payload = srv._state_payload()
    assert payload["opp"]["leader"] == "OP16-001"
    assert payload["opp"]["leader_inferred"] is False


def test_my_leader_and_reliable_odds_from_logged_deck(tmp_path, monkeypatch):
    """'Playing with deck' -> mon leader exact + odds fiables dès le tour 0 (deck loggé)."""
    # Sandbox app_support avec une decklist nommée.
    monkeypatch.setenv("OPTCG_APP_SUPPORT", str(tmp_path))
    deck = tmp_path / "MonDeck.txt"
    deck.write_text("1xPRB01-001\n4xOP01-013\n4xOP03-042\n")
    db = tmp_path / "t.db"
    _seed_db(db)
    srv = LiveEngine(str(db), reveal_all=False)
    st = srv.state
    st.feed_line("Playing with deck: MonDeck")
    st.feed_line("shuffle deck for Foe#2222")
    st.feed_line("shuffle deck for Me#0000")
    st.feed_line("[ReplaySync] RZ1|1|1|OP01-013|0|49|1|0|1|1|0|0|0")
    st.feed_line("Hand before Mulligan: [OP01-013]")

    payload = srv._state_payload()
    assert payload["me"]["leader"] == "PRB01-001"          # leader du deck loggé
    odds = payload.get("draw_odds")
    assert odds is not None and odds["reliable"] is True
    assert odds["deck_name"] == "MonDeck"
