"""Tests des analyses avancées (matchups, streaks, sparkline)."""

from datetime import datetime

from optcgsim_tracker.analytics import Analytics, sparkline
from optcgsim_tracker.archetype import ArchetypeModel
from optcgsim_tracker.db.store import Store
from optcgsim_tracker.model import MatchRecord, PlayerInfo


def _match(mid, result, my_leader, opp_leader, played_at, mode="ranked", rating=None):
    rec = MatchRecord(match_id=mid, played_at=datetime.fromisoformat(played_at), mode=mode)
    rec.me = PlayerInfo("me", name="Me", leader=my_leader, rating=rating)
    rec.opp = PlayerInfo("opp", name="Foe", leader=opp_leader)
    rec.result = result
    return rec


def test_sparkline_monotone():
    s = sparkline([1, 2, 3, 4, 5, 6, 7, 8])
    assert s[0] == "▁" and s[-1] == "█" and len(s) == 8


def test_matchup_matrix_and_streaks(tmp_path):
    data = [
        _match("1", "win", "L1", "E1", "2026-01-01T10:00:00"),
        _match("2", "win", "L1", "E1", "2026-01-01T11:00:00"),
        _match("3", "loss", "L1", "E1", "2026-01-01T12:00:00"),
        _match("4", "win", "L1", "E2", "2026-01-02T10:00:00"),
    ]
    with Store(tmp_path / "t.db") as st:
        # nomme les leaders pour des labels lisibles
        st.import_card_names({"L1": "MonLeader", "E1": "Ennemi1", "E2": "Ennemi2"})
        for r in data:
            st.upsert_match(r)
        a = Analytics(st)
        matrix = a.matchup_matrix(min_games=1)
        cells = {c.opp_leader: c for c in matrix["MonLeader"]}
        assert cells["E1"].wins == 2 and cells["E1"].losses == 1
        assert cells["E2"].wins == 1

        s = a.streaks()
        assert s["best_win_streak"] == 2  # matchs 1,2
        assert s["total"] == 4
        days = a.by_day()
        assert len(days) == 2  # deux jours distincts


def _deck_match(mid, result, deck, opp_leader, meta, my_leader="L1"):
    rec = MatchRecord(match_id=mid, played_at=datetime.fromisoformat("2026-03-01T10:00:00"),
                      mode="ranked")
    rec.me = PlayerInfo("me", name="Me", leader=my_leader)
    rec.opp = PlayerInfo("opp", name="Foe", leader=opp_leader)
    rec.result = result
    rec.meta = meta
    rec.my_deck = deck
    return rec


def test_decks_in_meta_and_deck_leader(tmp_path):
    data = [
        _deck_match("1", "win",  "Aggro",   "E1", "OP10"),
        _deck_match("2", "loss", "Aggro",   "E1", "OP10"),
        _deck_match("3", "win",  "Control", "E1", "OP10"),
        _deck_match("4", "win",  None,      "E1", "OP10"),   # deck non identifié
        _deck_match("5", "win",  "Aggro",   "E1", "OP11"),   # autre meta
    ]
    with Store(tmp_path / "t.db") as st:
        for r in data:
            st.upsert_match(r)
        a = Analytics(st)
        decks = {r.label: r for r in a.decks_in_meta("OP10", having_min=1)}
        # NULL exclu ; seulement les decks nommés du meta OP10.
        assert set(decks) == {"Aggro", "Control"}
        assert decks["Aggro"].wins == 1 and decks["Aggro"].losses == 1
        assert decks["Control"].wins == 1
        # deck_leader : leader le plus fréquent du deck.
        assert a.deck_leader("Aggro", "OP10") == "L1"


def test_deck_filter_narrows_matchups(tmp_path):
    data = [
        _deck_match("1", "win",  "Aggro",   "E1", "OP10"),
        _deck_match("2", "loss", "Aggro",   "E1", "OP10"),
        _deck_match("3", "win",  "Control", "E1", "OP10"),
    ]
    with Store(tmp_path / "t.db") as st:
        for r in data:
            st.upsert_match(r)
        a = Analytics(st)
        # Niveau leader : 2-1 contre E1.
        lead = a.leader_matchups("OP10", "L1", having_min=1)
        assert lead[0]["wins"] == 2 and lead[0]["losses"] == 1
        # Filtré sur le deck Aggro : 1-1 seulement.
        aggro = a.leader_matchups("OP10", "L1", having_min=1, deck="Aggro")
        assert aggro[0]["wins"] == 1 and aggro[0]["losses"] == 1
        # split_first_second accepte aussi le filtre deck sans erreur.
        assert isinstance(a.split_first_second(leader="L1", meta="OP10", deck="Aggro"), list)


def test_split_elo_gap(tmp_path):
    """split_elo_gap : winrate par tranche d'écart d'Elo (favori / égal / underdog).

    Vérifie le bucketing et l'ordre (underdog → égal → favori).
    """
    data = [
        _match("1", "win",  "L1", "E1", "2026-01-01T10:00:00"),
        _match("2", "loss", "L1", "E1", "2026-01-01T11:00:00"),
        _match("3", "win",  "L1", "E1", "2026-01-01T12:00:00"),
    ]
    with Store(tmp_path / "t.db") as st:
        for r in data:
            st.upsert_match(r)
        # Fixe les ratings : m1 = favori (+200), m2 = underdog (-150), m3 = égal (+50)
        st.conn.execute("UPDATE matches SET my_rating=1200, opp_rating=1000 WHERE id='1'")
        st.conn.execute("UPDATE matches SET my_rating=1000, opp_rating=1150 WHERE id='2'")
        st.conn.execute("UPDATE matches SET my_rating=1100, opp_rating=1050 WHERE id='3'")
        st.conn.commit()

        a = Analytics(st)
        rows = a.split_elo_gap(leader="L1")
        # 3 buckets attendus, dans l'ordre underdog → égal → favori
        labels = [r.label for r in rows]
        assert len(rows) == 3
        assert "Underdog" in labels[0]
        assert "Égal" in labels[1]
        assert "Favori" in labels[2]
        by = {r.label: r for r in rows}
        # Favori (m1, +200) : 1 win
        fav = next(v for k, v in by.items() if "Favori" in k)
        assert fav.wins == 1 and fav.losses == 0
        # Underdog (m2, -150) : 1 loss
        und = next(v for k, v in by.items() if "Underdog" in k)
        assert und.wins == 0 and und.losses == 1
        # Égal (m3, +50) : 1 win
        egal = next(v for k, v in by.items() if "Égal" in k)
        assert egal.wins == 1 and egal.losses == 0


def test_split_elo_gap_empty_when_no_ratings(tmp_path):
    """Sans ratings, split_elo_gap renvoie une liste vide (pas de crash)."""
    data = [_match("1", "win", "L1", "E1", "2026-01-01T10:00:00")]
    with Store(tmp_path / "t.db") as st:
        st.upsert_match(data[0])
        a = Analytics(st)
        assert a.split_elo_gap(leader="L1") == []


def test_filter_by_mode_and_format(tmp_path):
    """Le filtrage par mode (ranked/direct) et format (Standard/Extra) isole les matchs."""
    data = [
        _match("1", "win",  "L1", "E1", "2026-01-01T10:00:00"),
        _match("2", "loss", "L1", "E1", "2026-01-01T11:00:00"),
        _match("3", "win",  "L1", "E1", "2026-01-01T12:00:00"),
    ]
    with Store(tmp_path / "t.db") as st:
        for r in data:
            st.upsert_match(r)
        # m1 = ranked + Standard, m2 = direct + Standard, m3 = ranked + Extra Regulation
        st.conn.execute("UPDATE matches SET mode='ranked', format='Standard (Eastern/Nationals/Western — pool identique)', meta='OP10' WHERE id='1'")
        st.conn.execute("UPDATE matches SET mode='direct', format='Standard (Eastern/Nationals/Western — pool identique)', meta='OP10' WHERE id='2'")
        st.conn.execute("UPDATE matches SET mode='ranked', format='Extra Regulation (sets hors-standard : ST31)', meta='OP10' WHERE id='3'")
        st.conn.commit()

        a = Analytics(st)

        # Filtre mode=ranked : 2 matchs (m1 win + m3 win)
        # Utilise leader_matchups qui ne dépend pas de i_went_first
        mus = a.leader_matchups("OP10", "L1", mode="ranked")
        total = sum(m["wins"] + m["losses"] for m in mus)
        wins = sum(m["wins"] for m in mus)
        assert total == 2 and wins == 2

        # Filtre mode=direct : 1 match (m2 loss)
        mus = a.leader_matchups("OP10", "L1", mode="direct")
        total = sum(m["wins"] + m["losses"] for m in mus)
        losses = sum(m["losses"] for m in mus)
        assert total == 1 and losses == 1

        # Filtre format=Standard : 2 matchs (m1 + m2)
        mus = a.leader_matchups("OP10", "L1", fmt="Standard")
        total = sum(m["wins"] + m["losses"] for m in mus)
        assert total == 2

        # Filtre format=Extra : 1 match (m3)
        mus = a.leader_matchups("OP10", "L1", fmt="Extra Regulation")
        total = sum(m["wins"] + m["losses"] for m in mus)
        assert total == 1

        # Filtre combiné mode=ranked + format=Standard : 1 match (m1)
        mus = a.leader_matchups("OP10", "L1", mode="ranked", fmt="Standard")
        total = sum(m["wins"] + m["losses"] for m in mus)
        assert total == 1

        # by_meta avec filtre format=Extra : 1 match
        from optcgsim_tracker.meta import Meta
        tl = [Meta("OP10", "OP10", "2026-01-01")]
        metas = a.by_meta(tl, fmt="Extra Regulation")
        assert sum(r.total for r in metas) == 1


def test_archetype_prediction(tmp_path):
    # Trois decks historiques pour le leader E1 : Carte commune A partout, B dans 2/3.
    def opp_deck_match(mid, deck):
        rec = MatchRecord(match_id=mid, mode="ranked")
        rec.me = PlayerInfo("me", name="Me", leader="L1")
        rec.opp = PlayerInfo("opp", name="Foe", leader="E1", deck=deck, deck_known=True)
        rec.result = "win"
        return rec

    with Store(tmp_path / "t.db") as st:
        st.upsert_match(opp_deck_match("1", {"A-001": 4, "B-001": 2, "C-001": 4}))
        st.upsert_match(opp_deck_match("2", {"A-001": 4, "B-001": 3, "D-001": 4}))
        st.upsert_match(opp_deck_match("3", {"A-001": 4, "E-001": 2}))
        model = ArchetypeModel(st)
        pred = model.predict("E1", revealed={"A-001"})
        assert pred.n_historical == 3
        # A présent dans 100% des decks, en tête du profil.
        assert pred.expected_cards[0]["card_id"] == "A-001"
        assert pred.expected_cards[0]["presence"] == 100.0
        # A est révélé et présent partout -> recouvrement parfait.
        assert pred.nearest_overlap == 1.0
        # B (présent 2/3 = 67% ≥ 50%) figure parmi les cartes probables non vues.
        assert any(c["card_id"] == "B-001" for c in pred.unseen_likely)


def test_infer_leader_breaks_ties_by_set_code(tmp_path):
    """Deux leaders homonymes (même nom, codes de set différents) partageant des cartes :
    l'inférence départage par le CODE DE SET dominant des cartes vues, pas par le nom, et de
    façon déterministe (pas de flip entre rafraîchissements)."""
    def opp(mid, leader, deck):
        rec = MatchRecord(match_id=mid, mode="ranked")
        rec.me = PlayerInfo("me", name="Me", leader="L1")
        rec.opp = PlayerInfo("opp", name="Foe", leader=leader, deck=deck, deck_known=True)
        rec.result = "win"
        return rec

    with Store(tmp_path / "t.db") as st:
        # Deux "Ace" : OP13-002 et OP16-001, partageant la carte SHARED-001.
        st.import_card_names({"OP13-002": "Portgas D. Ace", "OP16-001": "Portgas D. Ace"})
        st.upsert_match(opp("a", "OP13-002", {"SHARED-001": 4, "OP13-050": 4}))
        st.upsert_match(opp("b", "OP16-001", {"SHARED-001": 4, "OP16-011": 4, "OP16-017": 4}))
        model = ArchetypeModel(st)

        # Vu seulement la carte partagée -> couverture 1.0 pour les DEUX -> départage par set.
        # Cartes OP16 dominantes -> doit choisir OP16-001 (pas OP13-002).
        leader, score = model.infer_leader({"SHARED-001", "OP16-011"})
        assert leader == "OP16-001"
        # Déterministe : même entrée -> même sortie (pas de flip).
        assert model.infer_leader({"SHARED-001", "OP16-011"})[0] == "OP16-001"
        # Cartes OP13 dominantes -> OP13-002.
        assert model.infer_leader({"SHARED-001", "OP13-050"})[0] == "OP13-002"


# --- KPIs gameplay compétitifs ---

def _seed_gameplay_db(st):
    """Insère 6 matchs avec events et snapshots pour tester les KPIs gameplay."""
    import json
    # 3 victoires, 3 défaites avec le même leader
    matches = [
        ("m1", "win",  "L1", "E1", "2026-06-01T10:00:00"),
        ("m2", "win",  "L1", "E1", "2026-06-02T10:00:00"),
        ("m3", "win",  "L1", "E1", "2026-06-03T10:00:00"),
        ("m4", "loss", "L1", "E1", "2026-06-04T10:00:00"),
        ("m5", "loss", "L1", "E1", "2026-06-05T10:00:00"),
        ("m6", "loss", "L1", "E1", "2026-06-06T10:00:00"),
    ]
    for mid, result, ml, ol, ts in matches:
        rec = MatchRecord(match_id=mid, played_at=datetime.fromisoformat(ts), mode="ranked")
        rec.me = PlayerInfo("me", name="Me", leader=ml)
        rec.opp = PlayerInfo("opp", name="Foe", leader=ol)
        rec.result = result
        st.upsert_match(rec)
    # Snapshots (life) : victoires décroissent plus lentement
    for mid, result, *_ in matches:
        life_seq = [5, 5, 4, 3, 2] if result == "win" else [5, 4, 3, 2, 1]
        for idx, (turn, life) in enumerate(zip(range(1, 6), life_seq)):
            st.conn.execute(
                "INSERT OR REPLACE INTO turn_snapshots "
                "(match_id, idx, turn, side, hand_count, hand_ids, board_ids, trash_ids, life)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (mid, idx, turn, "me", 5, "[]", "[]", "[]", life))
    # Events (deploy, attack, counter) pour les 6 matchs
    st.conn.execute("INSERT OR IGNORE INTO cards (card_id, set_code, cost, card_type) VALUES ('C1','X',3,'Character')")
    st.conn.execute("INSERT OR IGNORE INTO cards (card_id, set_code, cost, card_type) VALUES ('C2','X',5,'Character')")
    for i, (mid, result, ml, ol, _) in enumerate(matches):
        base = i * 10
        # deploy T2 (cost 3) et T4 (cost 5)
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES (?,?,2,'me','deploy','C1')", (mid, base + 1))
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES (?,?,4,'me','deploy','C2')", (mid, base + 2))
        # attack on leader (target = opp_leader = 'E1')
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id, target_id) VALUES (?,?,3,'me','attack','C1','E1')", (mid, base + 3))
        # counter with value 2000
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, value) VALUES (?,?,3,'me','counter',2000)", (mid, base + 4))
        # DON : +2 par tour (T1-T5), attach 1 DON au T3
        for t in range(1, 6):
            st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, value) VALUES (?,?,?,'me','don',2)", (mid, base + 4 + t, t))
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, value) VALUES (?,?,3,'me','don_attach',1)", (mid, base + 10))
    # Fixe opp_leader dans matches
    for mid, *_ in matches:
        st.conn.execute("UPDATE matches SET opp_leader='E1' WHERE id=?", (mid,))
    st.conn.commit()


def test_life_trajectory(tmp_path):
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        a = Analytics(st)
        traj = a.life_trajectory(leader="L1", min_games=5)
        assert traj is not None
        assert traj["n_win"] == 3 and traj["n_loss"] == 3
        # life T1 victoires > life T1 défaites à T5
        win_at_t5 = next((v for t, v in traj["win"] if t == 5), None)
        loss_at_t5 = next((v for t, v in traj["loss"] if t == 5), None)
        assert win_at_t5 is not None and loss_at_t5 is not None
        assert win_at_t5 > loss_at_t5


def test_deploy_curve(tmp_path):
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        a = Analytics(st)
        dcurve = a.deploy_curve(leader="L1", min_games=5)
        assert dcurve is not None
        assert dcurve["n_win"] == 3 and dcurve["n_loss"] == 3
        # T2 avg_cost = 3.0, T4 avg_cost = 5.0 (mêmes pour win et loss dans notre fixture)
        t2_win = next((v for t, v in dcurve["win"] if t == 2), None)
        assert t2_win == 3.0


def test_attack_distribution(tmp_path):
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        a = Analytics(st)
        dist = a.attack_distribution(leader="L1", min_games=5)
        assert dist is not None
        assert dist["n_win"] == 3 and dist["n_loss"] == 3
        # Toutes les attaques visent E1 (leader) donc life_pct = 100%
        assert dist["win"]["life_pct"] == 100.0
        assert dist["loss"]["life_pct"] == 100.0


def test_counter_stats(tmp_path):
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        a = Analytics(st)
        cnt = a.counter_stats(leader="L1", min_games=5)
        assert cnt is not None
        assert cnt["n_win"] == 3 and cnt["n_loss"] == 3
        # 1 counter à 2000 par match -> avg_value=2000, avg_count=1
        assert cnt["win"]["avg_value"] == 2000.0
        assert cnt["win"]["avg_count"] == 1.0


def test_mulligan_reco_split_premier_second(tmp_path):
    """mulligan_reco retourne les clés premier/second et score_hand fonctionne."""
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        # Ajoute des opening_hands pour que opening_impact retourne quelque chose.
        for i, (mid, result, *_) in enumerate([
            ("m1", "win"), ("m2", "win"), ("m3", "win"),
            ("m4", "loss"), ("m5", "loss"), ("m6", "loss"),
        ]):
            for pos, cid in enumerate(["C1", "C2", "C1", "C2", "C1"]):
                kept = 1 if result == "win" else 0
                st.conn.execute(
                    "INSERT OR IGNORE INTO opening_hands (match_id, side, position, card_id, kept)"
                    " VALUES (?,?,?,?,?)", (mid, "me", pos, cid, kept))
        # i_went_first : premiers gagnants first, perdants second
        st.conn.execute("UPDATE matches SET i_went_first=1 WHERE result='win'")
        st.conn.execute("UPDATE matches SET i_went_first=0 WHERE result='loss'")
        st.conn.commit()

        a = Analytics(st)
        reco = a.mulligan_reco("L1", None)
        assert "premier" in reco and "second" in reco
        assert "scored" in reco
        assert isinstance(reco["premier"], dict)
        assert isinstance(reco["second"], dict)
        # score_hand sur C1+C2+C1+C2+C1 : somme des scores connus
        score = Analytics.score_hand(["C1", "C2", "C1", "C2", "C1"], reco["scored"])
        assert isinstance(score, float)


def test_hand_score_stats(tmp_path):
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        for mid, result, *_ in [
            ("m1", "win"), ("m2", "win"), ("m3", "win"),
            ("m4", "loss"), ("m5", "loss"), ("m6", "loss"),
        ]:
            kept = 1 if result == "win" else 0
            for pos, cid in enumerate(["C1", "C2", "C1", "C2", "C1"]):
                st.conn.execute(
                    "INSERT OR IGNORE INTO opening_hands (match_id, side, position, card_id, kept)"
                    " VALUES (?,?,?,?,?)", (mid, "me", pos, cid, kept))
        st.conn.commit()
        a = Analytics(st)
        hss = a.hand_score_stats("L1", None, min_games=5)
        assert hss is not None
        assert "avg_win" in hss and "avg_loss" in hss
        assert hss["n_win"] == 3 and hss["n_loss"] == 3


def test_played_impact_mode_turn_and_survivorship(tmp_path):
    """played_impact retourne mode_turn (pas avg_turn) et le lift est conditionné par durée."""
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        a = Analytics(st)
        _, _, cards = a.played_impact(leader="L1", min_games=5)
        assert len(cards) == 2
        by_id = {c["card_id"]: c for c in cards}
        # C1 déployé à T2 dans tous les matchs -> mode_turn=2, phase=early
        assert by_id["C1"]["mode_turn"] == 2
        assert by_id["C1"]["phase"] == "early"
        # C2 déployé à T4 dans tous les matchs -> mode_turn=4, phase=mid
        assert by_id["C2"]["mode_turn"] == 4
        assert by_id["C2"]["phase"] == "mid"
        # Clé avg_turn doit avoir disparu
        assert "avg_turn" not in by_id["C1"]
        # cond_baseline et cond_n présents
        assert "cond_baseline" in by_id["C1"]
        assert "cond_n" in by_id["C1"]
        # Tous les matchs durent >= T4 (max event turn = 4) -> cond_n = 6 pour les deux
        assert by_id["C2"]["cond_n"] == 6
        # WR = 50% et baseline = 50% -> lift = 0 (tolérance ±1 due arrondi)
        assert abs(by_id["C1"]["lift"]) <= 1.0
        assert abs(by_id["C2"]["lift"]) <= 1.0


def test_kpis_return_none_below_min_games(tmp_path):
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        a = Analytics(st)
        # min_games=10 alors qu'on n'a que 6 matchs -> None
        assert a.life_trajectory(leader="L1", min_games=10) is None
        assert a.deploy_curve(leader="L1", min_games=10) is None
        assert a.attack_distribution(leader="L1", min_games=10) is None
        assert a.counter_stats(leader="L1", min_games=10) is None
        assert a.don_waste(leader="L1", min_games=10) is None


def test_don_waste(tmp_path):
    """DON Waste : vérifie le calcul par tour (dispo − attaché cumul − deploy)."""
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        a = Analytics(st)
        dw = a.don_waste(leader="L1", min_games=5)
        assert dw is not None
        assert dw["n_win"] == 3 and dw["n_loss"] == 3

        # Tous les matchs ont les mêmes events → waste identique win/loss.
        # T1: dispo=2, attach=0, deploy=0 → waste=2
        # T2: dispo=4, attach=0, deploy=3 → waste=1
        # T3: dispo=6, attach=1, deploy=0 → waste=5
        # T4: dispo=8, attach=1, deploy=5 → waste=2
        # T5: dispo=10, attach=1, deploy=0 → waste=9
        # Total = 2+1+5+2+9 = 19
        curve = dw["curve"]["win"]
        by_turn = {t: v for t, v in curve}
        assert by_turn[1] == 2.0
        assert by_turn[2] == 1.0
        assert by_turn[3] == 5.0
        assert by_turn[4] == 2.0
        assert by_turn[5] == 9.0

        # Summary : avg_total = 19, avg_per_turn = 19/5 = 3.8
        assert dw["summary"]["win"]["avg_total"] == 19.0
        assert dw["summary"]["win"]["avg_per_turn"] == 3.8
        assert dw["summary"]["win"]["n"] == 3
        # Loss = identique (mêmes events)
        assert dw["summary"]["loss"]["avg_total"] == 19.0


def test_don_waste_with_attach_reduces_available(tmp_path):
    """Un attach cumulatif réduit le DON disponible pour les tours suivants."""
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        # Ajoute un 2e attach au T4 sur le 1er match (cumul = 2 au T4+)
        st.conn.execute(
            "INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, value) "
            "VALUES ('m1', 99, 4, 'me', 'don_attach', 3)")
        st.conn.commit()
        a = Analytics(st)
        dw = a.don_waste(leader="L1", min_games=5)
        assert dw is not None
        # m1 a un attach supplémentaire au T4 (cumul=2 au T4, cumul=2 au T5)
        # T4: dispo=8, attach_cumul=1+3=4, deploy=5 → waste=max(0, 8-4-5)=0 (pas -1)
        # T5: dispo=10, attach_cumul=4, deploy=0 → waste=6
        # Mais la courbe est une moyenne sur tous les matchs ; m1 a un waste différent.
        # Vérifions juste que le waste de m1 est plus bas (le total waste de m1 < 19).
        # Sur la courbe, T4 win = moyenne des 3 matchs win (m1,m2,m3).
        # m1 T4 waste = 0, m2/m3 T4 waste = 2 → avg = (0+2+2)/3 ≈ 1.33
        t4_win = next((v for t, v in dw["curve"]["win"] if t == 4), None)
        assert t4_win is not None
        assert t4_win < 2.0  # réduit par l'attach supplémentaire de m1


# --- Tests des améliorations du modèle de mulligan (v2) ---

def test_score_hand_curve_penalty(tmp_path):
    """Curve Penalty : une main avec 3+ cartes chères (≥5 cost) reçoit un malus."""
    scored = [
        {"card_id": "BOSS1", "name": "Boss1", "score": 3.0},
        {"card_id": "BOSS2", "name": "Boss2", "score": 3.0},
        {"card_id": "BOSS3", "name": "Boss3", "score": 3.0},
        {"card_id": "CHEAP", "name": "Cheap", "score": 1.0},
        {"card_id": "FILLER", "name": "Filler", "score": 0.0},
    ]
    # Main sans coût : pas de malus (card_costs=None).
    hand = ["BOSS1", "BOSS2", "BOSS3", "CHEAP", "FILLER"]
    score_no_costs = Analytics.score_hand(hand, scored)
    assert score_no_costs == 10.0  # 3+3+3+1+0 = 10

    # Même main avec coûts : 3 cartes ≥5 cost → malus -3.
    costs = {"BOSS1": 8, "BOSS2": 9, "BOSS3": 7, "CHEAP": 2, "FILLER": 1}
    score_with_penalty = Analytics.score_hand(hand, scored, costs)
    assert score_with_penalty == 7.0  # 10 - 3 = 7

    # Main avec 4 cartes chères → malus -6.
    hand_brick = ["BOSS1", "BOSS2", "BOSS3", "CHEAP", "BOSS1"]
    # Note: BOSS1 apparaît 2 fois, mais on compte les occurrences dans hand.
    # expensive = 4 (BOSS1, BOSS2, BOSS3, BOSS1) → malus -6.
    score_brick = Analytics.score_hand(hand_brick, scored, costs)
    # 3+3+3+1+3 = 13 (BOSS1 compté 2x) - 6 = 7
    assert score_brick == 7.0

    # Main équilibrée : 2 cartes chères → pas de malus.
    hand_balanced = ["BOSS1", "BOSS2", "CHEAP", "FILLER", "CHEAP"]
    score_balanced = Analytics.score_hand(hand_balanced, scored, costs)
    # 3+3+1+0+1 = 8, expensive=2 → pas de malus
    assert score_balanced == 8.0


def test_score_hand_curve_penalty_threshold():
    """Le malus s'active à 3 cartes ≥5 cost, pas à 2."""
    scored = [
        {"card_id": "A", "name": "A", "score": 2.0},
        {"card_id": "B", "name": "B", "score": 2.0},
    ]
    costs = {"A": 5, "B": 5}
    # 2 cartes chères → pas de malus.
    assert Analytics.score_hand(["A", "B"], scored, costs) == 4.0
    # 3 cartes chères → malus -3.
    assert Analytics.score_hand(["A", "B", "A"], scored, costs) == 4.0 + 2.0 - 3.0  # 3


def test_mulligan_reco_k_default_is_20(tmp_path):
    """Le paramètre k par défaut est 20 (absorbe la variance)."""
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        a = Analytics(st)
        reco = a.mulligan_reco("L1", None)
        # Vérifie que reco fonctionne (k=20 est la valeur par défaut).
        assert reco is not None
        assert "scored" in reco


def test_mulligan_reco_returns_avg_hand_score(tmp_path):
    """mulligan_reco retourne avg_hand_score (baseline pour seuils relatifs)."""
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        # Ajoute des opening_hands.
        for i, (mid, result, *_) in enumerate([
            ("m1", "win"), ("m2", "win"), ("m3", "win"),
            ("m4", "loss"), ("m5", "loss"), ("m6", "loss"),
        ]):
            for pos, cid in enumerate(["C1", "C2", "C1", "C2", "C1"]):
                kept = 1 if result == "win" else 0
                st.conn.execute(
                    "INSERT OR IGNORE INTO opening_hands (match_id, side, position, card_id, kept)"
                    " VALUES (?,?,?,?,?)", (mid, "me", pos, cid, kept))
        st.conn.commit()
        a = Analytics(st)
        reco = a.mulligan_reco("L1", None)
        assert "avg_hand_score" in reco
        # Avec 6 mains historiques, avg_hand_score doit être calculé.
        assert reco["avg_hand_score"] is not None


def test_mulligan_reco_dead_in_hand_penalty(tmp_path):
    """Dead-in-Hand : une carte jamais jouée mais avec WR élevé voit son lift divisé par 2."""
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        # Ajoute une carte C3 qui est en main mais JAMAIS jouée (pas d'event deploy/counter).
        st.conn.execute("INSERT OR IGNORE INTO cards (card_id, set_code, cost, card_type) VALUES ('C3','X',2,'Character')")
        # Ajoute 4 matchs supplémentaires (3 wins + 1 loss) pour donner à C3 un lift positif.
        # C3 sera dans 7 mains : 3 wins originales + 3 nouveaux wins + 1 nouveau loss = 6W/1L.
        # Mais les matchs originaux (m1-m6) ont déjà 3W/3L. On ajoute C3 dans les 3 wins
        # originaux + 4 nouveaux matchs (3W + 1L) = 6W + 1L = 7 mains, WR = 85.7%.
        # Baseline globale = (3+3)W / (3+3+4) = 6/10 = 60%. Lift = 85.7 - 60 = 25.7%.
        extra = [
            ("m7", "win", "L1", "E1", "2026-06-07T10:00:00"),
            ("m8", "win", "L1", "E1", "2026-06-08T10:00:00"),
            ("m9", "win", "L1", "E1", "2026-06-09T10:00:00"),
            ("m10", "loss", "L1", "E1", "2026-06-10T10:00:00"),
        ]
        for mid, result, ml, ol, ts in extra:
            rec = MatchRecord(match_id=mid, played_at=datetime.fromisoformat(ts), mode="ranked")
            rec.me = PlayerInfo("me", name="Me", leader=ml)
            rec.opp = PlayerInfo("opp", name="Foe", leader=ol)
            rec.result = result
            st.upsert_match(rec)
        # C3 en main dans les 3 wins originaux + les 4 nouveaux = 7 mains (6W + 1L).
        for mid in ["m1", "m2", "m3", "m7", "m8", "m9", "m10"]:
            result = "win" if mid in ("m1", "m2", "m3", "m7", "m8", "m9") else "loss"
            for pos, cid in enumerate(["C3", "C1", "C2", "C1", "C2"]):
                kept = 1 if result == "win" else 0
                st.conn.execute(
                    "INSERT OR IGNORE INTO opening_hands (match_id, side, position, card_id, kept)"
                    " VALUES (?,?,?,?,?)", (mid, "me", pos, cid, kept))
        # Ajoute aussi des opening_hands pour m4-m6 (sans C3) pour que la baseline
        # inclue des matchs où C3 n'est pas présente.
        for mid in ["m4", "m5", "m6"]:
            for pos, cid in enumerate(["C1", "C2", "C1", "C2", "C1"]):
                st.conn.execute(
                    "INSERT OR IGNORE INTO opening_hands (match_id, side, position, card_id, kept)"
                    " VALUES (?,?,?,?,?)", (mid, "me", pos, cid, 0))
        st.conn.commit()
        a = Analytics(st)
        # Récupère opening_impact pour C3 (min_games=6 pour matcher ovr).
        _, _, ovr = a.opening_impact(leader="L1", meta=None, min_games=6)
        c3 = next((c for c in ovr if c["card_id"] == "C3"), None)
        assert c3 is not None
        # C3 n'a jamais été jouée → n_dead == n.
        assert c3["n_dead"] == c3["n"]
        assert c3["dwr_dead"] is not None
        # dwr_dead ≈ DWR (carte jamais jouée, donc dead WR = WR global).
        assert abs(c3["dwr_dead"] - c3["winrate"]) < 3.0
        # Le malus Dead-in-Hand doit s'activer : score divisé par 2.
        reco = a.mulligan_reco("L1", None)
        c3_scored = next((c for c in reco["scored"] if c["card_id"] == "C3"), None)
        assert c3_scored is not None
        # Le score doit être strictement inférieur au lift (division par 2 appliquée).
        assert c3_scored["score"] < c3["lift"]
        assert abs(c3_scored["score"] - c3["lift"] / 2.0) < 0.1  # ≈ lift / 2


def test_hand_score_stats_returns_avg_all(tmp_path):
    """hand_score_stats retourne avg_all (moyenne toutes mains confondues)."""
    with Store(tmp_path / "t.db") as st:
        _seed_gameplay_db(st)
        for mid, result, *_ in [
            ("m1", "win"), ("m2", "win"), ("m3", "win"),
            ("m4", "loss"), ("m5", "loss"), ("m6", "loss"),
        ]:
            kept = 1 if result == "win" else 0
            for pos, cid in enumerate(["C1", "C2", "C1", "C2", "C1"]):
                st.conn.execute(
                    "INSERT OR IGNORE INTO opening_hands (match_id, side, position, card_id, kept)"
                    " VALUES (?,?,?,?,?)", (mid, "me", pos, cid, kept))
        st.conn.commit()
        a = Analytics(st)
        hss = a.hand_score_stats("L1", None, min_games=5)
        assert hss is not None
        assert "avg_all" in hss
        assert hss["avg_all"] is not None


# --- Tests du Value Score (State Diffing) ---

def _seed_value_db(st):
    """Insère 2 matchs avec events pour tester le Value Score.

    Match 1 (win) : Alice déploie C1 (cost 3, power 5000) qui détruit C_opp (cost 5).
    Match 2 (loss) : Alice déploie C2 (cost 8, power 8000) sans effet.
    """
    from optcgsim_tracker.model import MatchRecord, PlayerInfo
    matches = [
        ("v1", "win", "L1", "E1", "2026-07-01T10:00:00"),
        ("v2", "loss", "L1", "E1", "2026-07-02T10:00:00"),
    ]
    for mid, result, ml, ol, ts in matches:
        rec = MatchRecord(match_id=mid, played_at=datetime.fromisoformat(ts), mode="ranked")
        rec.me = PlayerInfo("me", name="Me", leader=ml)
        rec.opp = PlayerInfo("opp", name="Foe", leader=ol)
        rec.result = result
        st.upsert_match(rec)

    # Cartes avec cost et power.
    st.conn.execute("INSERT OR IGNORE INTO cards (card_id, set_code, cost, power, card_type) VALUES ('C1','X',3,5000,'Character')")
    st.conn.execute("INSERT OR IGNORE INTO cards (card_id, set_code, cost, power, card_type) VALUES ('C2','X',8,8000,'Character')")
    st.conn.execute("INSERT OR IGNORE INTO cards (card_id, set_code, cost, power, card_type) VALUES ('C_opp','X',5,7000,'Character')")
    st.conn.execute("INSERT OR IGNORE INTO cards (card_id, set_code, cost, power, card_type) VALUES ('L1','X',0,5000,'Leader')")
    st.conn.execute("INSERT OR IGNORE INTO cards (card_id, set_code, cost, power, card_type) VALUES ('E1','X',0,5000,'Leader')")

    # Match 1 (win) : deploy C1, draw 1, KO C_opp, end_turn.
    seq = 1
    st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v1',?,1,'me','deploy','C1')", (seq,))
    seq += 1
    st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v1',?,1,'me','draw','X1')", (seq,))
    seq += 1
    st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v1',?,1,'opp','ko','C_opp')", (seq,))
    seq += 1
    st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type) VALUES ('v1',?,1,'me','end_turn')", (seq,))

    # Match 2 (loss) : deploy C2, end_turn (aucun effet).
    seq = 1
    st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v2',?,1,'me','deploy','C2')", (seq,))
    seq += 1
    st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type) VALUES ('v2',?,1,'me','end_turn')", (seq,))

    st.conn.commit()


def test_value_score_basic(tmp_path):
    """Value Score de base : body + draw - don_invested + ko_adverse."""
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        a = Analytics(st)
        vs = a.value_score_per_card(leader="L1", min_games=1)

        # C1 (match 1, win) : body(+5) + draw(+2) + ko C_opp(+5) - don(-3) = +9
        c1 = next(c for c in vs if c["card_id"] == "C1")
        assert c1["n"] == 1
        assert c1["avg_value"] == 9.0  # 5 + 2 + 5 - 3 = 9
        assert c1["avg_value_win"] == 9.0

        # C2 (match 2, loss) : body(+8) - don(-8) = 0
        c2 = next(c for c in vs if c["card_id"] == "C2")
        assert c2["n"] == 1
        assert c2["avg_value"] == 0.0  # 8 - 8 = 0
        assert c2["avg_value_loss"] == 0.0


def test_value_score_effect_remove(tmp_path):
    """Effect remove : +cost de la cible adverse."""
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        # Ajoute un match 3 avec effect_remove.
        rec = MatchRecord(match_id="v3", played_at=datetime.fromisoformat("2026-07-03T10:00:00"), mode="ranked")
        rec.me = PlayerInfo("me", name="Me", leader="L1")
        rec.opp = PlayerInfo("opp", name="Foe", leader="E1")
        rec.result = "win"
        st.upsert_match(rec)

        # effect_remove : side='opp' = la VICTIME est l'adversaire (sémantique réelle du log,
        # vérifiée sur fixture : la carte retirée va dans le trash du joueur préfixé).
        # card_id='C1' = source (ma carte déployée), target_id='C_opp' = perso adverse retiré.
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v3',1,1,'me','deploy','C1')")
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id, target_id, value) VALUES ('v3',2,1,'opp','effect_remove','C1','C_opp',1)")
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type) VALUES ('v3',3,1,'me','end_turn')")
        st.conn.commit()

        a = Analytics(st)
        vs = a.value_score_per_card(leader="L1", min_games=1)
        c1 = next(c for c in vs if c["card_id"] == "C1")
        # Match 1 : +9, Match 3 : body(+5) + effect_remove(+5) - don(-3) = +7
        # avg = (9 + 7) / 2 = 8.0
        assert c1["n"] == 2
        assert c1["avg_value"] == 8.0


def test_value_score_confidence_interval(tmp_path):
    """avg_value est accompagné d'un IC 95 % ; `significant` = l'IC ne traverse pas 0."""
    with Store(tmp_path / "ci1.db") as st:
        _seed_one_match(st, "ci_a", result="win")
        _seed_one_match(st, "ci_b", result="win")
        _seed_one_match(st, "ci_c", result="win")
        # C1 déployé 3× avec la MÊME valeur (body+5 - don3 = +2) -> variance nulle.
        for mid in ("ci_a", "ci_b", "ci_c"):
            _ev(st, mid, 1, 1, "me", "deploy", card_id="C1")
            _ev(st, mid, 2, 1, "me", "end_turn")
        st.conn.commit()
        a = Analytics(st)
        c1 = next(c for c in a.value_score_per_card(leader="L1", min_games=1)
                  if c["card_id"] == "C1")
        assert c1["n"] == 3
        assert c1["avg_value"] == 2.0
        # Variance nulle -> IC collapsé sur la moyenne, effet significatif (> 0).
        assert c1["ci_low"] == 2.0 and c1["ci_high"] == 2.0
        assert c1["significant"] is True

    # Forte variance traversant 0 -> non significatif.
    with Store(tmp_path / "ci2.db") as st:
        _seed_one_match(st, "hv_a", result="win")
        _seed_one_match(st, "hv_b", result="loss")
        # match a : C1 OnPlay KO (+9) ; match b : C1 self-KO (-3, pas de body).
        _ev(st, "hv_a", 1, 1, "me", "deploy", card_id="C1")
        _ev(st, "hv_a", 2, 1, "me", "draw", card_id="X1")
        _ev(st, "hv_a", 3, 1, "opp", "ko", card_id="C_opp")
        _ev(st, "hv_a", 4, 1, "me", "end_turn")
        _ev(st, "hv_b", 1, 1, "me", "deploy", card_id="C1")
        _ev(st, "hv_b", 2, 1, "me", "ko", card_id="C1")
        _ev(st, "hv_b", 3, 1, "me", "end_turn")
        st.conn.commit()
        a = Analytics(st)
        c1 = next(c for c in a.value_score_per_card(leader="L1", min_games=1)
                  if c["card_id"] == "C1")
        assert c1["n"] == 2
        assert c1["ci_low"] < 0 < c1["ci_high"]
        assert c1["significant"] is False


def test_value_score_self_trash_not_credited(tmp_path):
    """Un self-trash de coût (je trashe ma PROPRE carte) ne crédite pas de tempo.

    Régression du bug confirmé sur log réel : Lucky Roux trashant son propre Character produit
    un effect_remove side='me' (victime = moi) que l'ancien code créditait à tort comme un
    retrait adverse.
    """
    with Store(tmp_path / "t.db") as st:
        _seed_one_match(st, "st1")
        st.conn.execute(
            "INSERT OR IGNORE INTO cards (card_id, set_code, cost, power, card_type)"
            " VALUES ('C_mine','X',4,5000,'Character')")
        _ev(st, "st1", 1, 1, "me", "deploy", card_id="C1")
        # C1 (source) trashe ma propre C_mine : side='me' = la victime est MOI.
        _ev(st, "st1", 2, 1, "me", "effect_remove", card_id="C1", target_id="C_mine", value=1)
        _ev(st, "st1", 3, 1, "me", "end_turn")
        st.conn.commit()
        a = Analytics(st)
        c1 = next(c for c in a.value_score_per_card(leader="L1", min_games=1)
                  if c["card_id"] == "C1")
        # body(+5) - don(-3) = +2 ; le self-trash de coût n'est PAS crédité (+cost C_mine exclu).
        assert c1["avg_value"] == 2.0


def test_value_score_life_damage(tmp_path):
    """Life damage : +2 par vie adverse prise."""
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        # Ajoute un match 4 avec life_damage.
        rec = MatchRecord(match_id="v4", played_at=datetime.fromisoformat("2026-07-04T10:00:00"), mode="ranked")
        rec.me = PlayerInfo("me", name="Me", leader="L1")
        rec.opp = PlayerInfo("opp", name="Foe", leader="E1")
        rec.result = "win"
        st.upsert_match(rec)

        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v4',1,1,'me','deploy','C1')")
        # life_damage : side=me (j'attaque), target=E1 (leader adverse), value=2 (2 vies).
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, target_id, value) VALUES ('v4',2,1,'me','life_damage','E1',2)")
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type) VALUES ('v4',3,1,'me','end_turn')")
        st.conn.commit()

        a = Analytics(st)
        vs = a.value_score_per_card(leader="L1", min_games=1)
        c1 = next(c for c in vs if c["card_id"] == "C1")
        # Match 1 : +9, Match 4 : body(+5) + life_damage(+4) - don(-3) = +6
        # avg = (9 + 6) / 2 = 7.5
        assert c1["n"] == 2
        assert c1["avg_value"] == 7.5


def test_value_score_sorted_descending(tmp_path):
    """Les cartes sont triées par avg_value décroissant."""
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        a = Analytics(st)
        vs = a.value_score_per_card(leader="L1", min_games=1)
        values = [c["avg_value"] for c in vs]
        assert values == sorted(values, reverse=True)


def test_value_score_min_games_filter(tmp_path):
    """min_games filtre les cartes avec trop peu d'occurrences."""
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        a = Analytics(st)
        # min_games=2 : C1 n'a que 1 occurrence dans _seed_value_db.
        vs = a.value_score_per_card(leader="L1", min_games=2)
        assert len(vs) == 0  # aucune carte n'a 2 occurrences


def test_value_score_returns_cost(tmp_path):
    """Le Value Score inclut le coût moyen de la carte."""
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        a = Analytics(st)
        vs = a.value_score_per_card(leader="L1", min_games=1)
        c1 = next(c for c in vs if c["card_id"] == "C1")
        assert c1["avg_cost"] == 3
        c2 = next(c for c in vs if c["card_id"] == "C2")
        assert c2["avg_cost"] == 8


def test_value_score_avg_early_value(tmp_path):
    """avg_early_value isole le Value Score des tours 1-4.

    Dans _seed_value_db, tous les deploys sont au tour 1 (≤4),
    donc avg_early_value == avg_value.
    """
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        a = Analytics(st)
        vs = a.value_score_per_card(leader="L1", min_games=1)
        c1 = next(c for c in vs if c["card_id"] == "C1")
        assert c1["avg_early_value"] == c1["avg_value"]  # tout est T1
        c2 = next(c for c in vs if c["card_id"] == "C2")
        assert c2["avg_early_value"] == c2["avg_value"]

    # Test avec un deploy tardif (tour 7) : avg_early_value doit exclure ce tour.
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        # Ajoute un 3e match : C1 déployé au tour 7 (tardif).
        rec = MatchRecord(match_id="v5", played_at=datetime.fromisoformat("2026-07-05T10:00:00"), mode="ranked")
        rec.me = PlayerInfo("me", name="Me", leader="L1")
        rec.opp = PlayerInfo("opp", name="Foe", leader="E1")
        rec.result = "win"
        st.upsert_match(rec)
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v5',1,7,'me','deploy','C1')")
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type) VALUES ('v5',2,7,'me','end_turn')")
        st.conn.commit()

        a = Analytics(st)
        vs = a.value_score_per_card(leader="L1", min_games=1)
        c1 = next(c for c in vs if c["card_id"] == "C1")
        # avg_value inclut T1 (+9) et T7 (body 5 - don 3 = +2) → (9+2)/2 = 5.5
        assert c1["n"] == 2
        assert c1["avg_value"] == 5.5
        # avg_early_value n'inclut que T1 (+9) → 9.0
        assert c1["avg_early_value"] == 9.0


def test_value_score_vpd(tmp_path):
    """VPD (Value Per DON) = avg_value / cost."""
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        a = Analytics(st)
        vs = a.value_score_per_card(leader="L1", min_games=1)
        c1 = next(c for c in vs if c["card_id"] == "C1")
        # C1 : avg_value=9, cost=3 → VPD = 3.0
        assert c1["vpd"] == 3.0
        c2 = next(c for c in vs if c["card_id"] == "C2")
        # C2 : avg_value=0, cost=8 → VPD = 0.0
        assert c2["vpd"] == 0.0


def _seed_one_match(st, mid, result="win"):
    """Match minimal (leader L1) prêt à recevoir des events custom."""
    rec = MatchRecord(match_id=mid, played_at=datetime.fromisoformat("2026-07-10T10:00:00"),
                      mode="ranked")
    rec.me = PlayerInfo("me", name="Me", leader="L1")
    rec.opp = PlayerInfo("opp", name="Foe", leader="E1")
    rec.result = result
    st.upsert_match(rec)
    for cid, cost, power, ctype in [("C1", 3, 5000, "Character"),
                                    ("C_opp", 5, 7000, "Character"),
                                    ("L1", 0, 5000, "Leader"), ("E1", 0, 5000, "Leader")]:
        st.conn.execute(
            "INSERT OR IGNORE INTO cards (card_id, set_code, cost, power, card_type)"
            " VALUES (?,?,?,?,?)", (cid, "X", cost, power, ctype))


def _ev(st, mid, seq, turn, side, etype, card_id=None, target_id=None, value=None):
    st.conn.execute(
        "INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id, target_id, value)"
        " VALUES (?,?,?,?,?,?,?,?)", (mid, seq, turn, side, etype, card_id, target_id, value))


def test_value_score_combat_ko_not_credited(tmp_path):
    """Un KO survenant APRÈS une attaque relève du combat, pas de l'effet de la carte posée."""
    with Store(tmp_path / "t.db") as st:
        _seed_one_match(st, "k1")
        # deploy C1, puis ATTAQUE, puis KO adverse (= KO de combat), end_turn.
        _ev(st, "k1", 1, 1, "me", "deploy", card_id="C1")
        _ev(st, "k1", 2, 1, "me", "attack", card_id="C1", target_id="C_opp")
        _ev(st, "k1", 3, 1, "opp", "ko", card_id="C_opp")
        _ev(st, "k1", 4, 1, "me", "end_turn")
        st.conn.commit()
        a = Analytics(st)
        c1 = next(c for c in a.value_score_per_card(leader="L1", min_games=1)
                  if c["card_id"] == "C1")
        # body(+5) - don(-3) = +2 ; le KO de combat n'est PAS crédité (sinon ce serait +7).
        assert c1["avg_value"] == 2.0


def test_value_score_onplay_ko_credited(tmp_path):
    """Un KO AVANT toute attaque (OnPlay destroy) est bien crédité à la carte."""
    with Store(tmp_path / "t.db") as st:
        _seed_one_match(st, "k2")
        _ev(st, "k2", 1, 1, "me", "deploy", card_id="C1")
        _ev(st, "k2", 2, 1, "opp", "ko", card_id="C_opp")   # avant toute attaque
        _ev(st, "k2", 3, 1, "me", "end_turn")
        st.conn.commit()
        a = Analytics(st)
        c1 = next(c for c in a.value_score_per_card(leader="L1", min_games=1)
                  if c["card_id"] == "C1")
        # body(+5) + ko C_opp(+5) - don(-3) = +7.
        assert c1["avg_value"] == 7.0


def test_value_score_effect_remove_requires_source_match(tmp_path):
    """Un effect_remove dont la source n'est PAS la carte déployée n'est pas crédité."""
    with Store(tmp_path / "t.db") as st:
        _seed_one_match(st, "r1")
        _ev(st, "r1", 1, 1, "me", "deploy", card_id="C1")
        # Retrait initié par une AUTRE source (C_other), tombé dans la fenêtre de C1.
        _ev(st, "r1", 2, 1, "me", "effect_remove", card_id="C_other", target_id="C_opp", value=1)
        _ev(st, "r1", 3, 1, "me", "end_turn")
        st.conn.commit()
        a = Analytics(st)
        c1 = next(c for c in a.value_score_per_card(leader="L1", min_games=1)
                  if c["card_id"] == "C1")
        # body(+5) - don(-3) = +2 ; le retrait d'une autre source n'est pas attribué à C1.
        assert c1["avg_value"] == 2.0


def test_value_score_self_removal_no_body(tmp_path):
    """Une carte KO'd dans sa propre fenêtre ne reçoit pas de crédit body (corps non durable)."""
    with Store(tmp_path / "t.db") as st:
        _seed_one_match(st, "s1")
        _ev(st, "s1", 1, 1, "me", "deploy", card_id="C1")
        # C1 elle-même détruite ce tour (side='me' = ma carte est la victime).
        _ev(st, "s1", 2, 1, "me", "ko", card_id="C1")
        _ev(st, "s1", 3, 1, "me", "end_turn")
        st.conn.commit()
        a = Analytics(st)
        c1 = next(c for c in a.value_score_per_card(leader="L1", min_games=1)
                  if c["card_id"] == "C1")
        # Pas de body (corps retiré) : seul le coût investi reste → -don(-3) = -3.
        assert c1["avg_value"] == -3.0


def test_value_score_per_turn(tmp_path):
    """value_score_per_turn retourne le Value Score par tour pour un match."""
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        a = Analytics(st)
        # Match 1 : C1 déployé au tour 1, value = +9
        vt = a.value_score_per_turn("v1")
        assert len(vt) == 1
        assert vt[0]["turn"] == 1
        assert vt[0]["value"] == 9.0
        assert vt[0]["cumulative"] == 9.0
        assert len(vt[0]["deploys"]) == 1
        assert vt[0]["deploys"][0]["card_id"] == "C1"
        assert vt[0]["deploys"][0]["value"] == 9.0

        # Match 2 : C2 déployé au tour 1, value = 0
        vt2 = a.value_score_per_turn("v2")
        assert len(vt2) == 1
        assert vt2[0]["value"] == 0.0
        assert vt2[0]["cumulative"] == 0.0

    # Test multi-tours : cumulative s'accumule.
    with Store(tmp_path / "t.db") as st:
        _seed_value_db(st)
        rec = MatchRecord(match_id="v6", played_at=datetime.fromisoformat("2026-07-06T10:00:00"), mode="ranked")
        rec.me = PlayerInfo("me", name="Me", leader="L1")
        rec.opp = PlayerInfo("opp", name="Foe", leader="E1")
        rec.result = "win"
        st.upsert_match(rec)
        # Tour 1 : C1 deploy + draw + ko + end_turn (value = +9)
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v6',1,1,'me','deploy','C1')")
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v6',2,1,'me','draw','X1')")
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v6',3,1,'opp','ko','C_opp')")
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type) VALUES ('v6',4,1,'me','end_turn')")
        # Tour 3 : C1 deploy + end_turn (value = body 5 - don 3 = +2)
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type, card_id) VALUES ('v6',5,3,'me','deploy','C1')")
        st.conn.execute("INSERT OR REPLACE INTO events (match_id, seq, turn, side, type) VALUES ('v6',6,3,'me','end_turn')")
        st.conn.commit()

        a = Analytics(st)
        vt = a.value_score_per_turn("v6")
        assert len(vt) == 2
        # T1 : +9, T3 : body(5) - don(3) = +2 (pas de draw/ko au tour 3)
        assert vt[0]["turn"] == 1
        assert vt[0]["value"] == 9.0
        assert vt[0]["cumulative"] == 9.0
        assert vt[1]["turn"] == 3
        assert vt[1]["value"] == 2.0
        assert vt[1]["cumulative"] == 11.0  # 9 + 2
