"""Tests du backend FastAPI : endpoints /api/state, /api/stats, /api/decks."""

from fastapi.testclient import TestClient

from optcgsim_tracker.api.server import create_app
from optcgsim_tracker.db.store import Store
from optcgsim_tracker.model import MatchRecord, PlayerInfo


def _seed_db(path):
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


def test_api_state_empty(tmp_path):
    """L'API /api/state ne doit pas crasher sans partie en cours."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/state")
    assert r.status_code == 200
    data = r.json()
    assert data["active"] is False
    assert data["me"] is None
    assert data["opp"] is None


def test_api_stats_metas(tmp_path):
    """L'API /api/stats sans paramètre retourne la liste des metas."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["level"] == "metas"
    assert isinstance(data["metas"], list)


def test_api_decks_list(tmp_path):
    """L'API /api/decks retourne une liste (même vide si pas de decks .txt)."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/decks")
    assert r.status_code == 200
    data = r.json()
    assert "decks" in data
    assert isinstance(data["decks"], list)


def test_api_deck_detail_cards_well_formed(tmp_path, monkeypatch):
    """L'API /api/decks/{name} retourne les cartes avec card_id et qty corrects.

    Régression : d.cards est un dict[str, int], pas une liste d'objets.
    """
    db = tmp_path / "t.db"
    _seed_db(db)
    # Crée un deck .txt temporaire
    deck_dir = tmp_path / "decks"
    deck_dir.mkdir()
    deck_file = deck_dir / "test_deck.txt"
    deck_file.write_text("1xOP09-001\n4xOP09-002\n2xOP09-009\n")
    app = create_app(str(db))
    live = app.state.live
    monkeypatch.setattr(live, "_resolve_deck", lambda name: deck_file if name else deck_file)
    monkeypatch.setattr(live, "_deck_paths", lambda: [deck_file])
    c = TestClient(app)
    r = c.get("/api/decks/test_deck")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "test_deck"
    assert data["leader"] == "OP09-001"
    # cards doit être une liste d'objets {card_id, qty, name}
    assert isinstance(data["cards"], list)
    assert len(data["cards"]) == 2  # 2 cartes hors leader
    by_id = {c["card_id"]: c for c in data["cards"]}
    assert by_id["OP09-002"]["qty"] == 4
    assert by_id["OP09-009"]["qty"] == 2
    # Chaque entrée a bien les 3 clés attendues
    for c in data["cards"]:
        assert "card_id" in c and "qty" in c and "name" in c


def test_api_card_not_found(tmp_path):
    """L'API /api/card retourne 404 pour un ID inexistant."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/card?id=ZZ99-999")
    assert r.status_code == 404


def test_api_state_with_live_match(tmp_path):
    """L'API /api/state expose le payload live quand une partie est en cours."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    live = app.state.live
    st = live.state
    st.reset_match()
    st.me_tag, st.opp_tag = "Me#1", "Foe#2"
    st._player("Me#1").side = "me"
    st._player("Me#1").leader = "L1"
    st._player("Foe#2").side = "opp"
    st._player("Foe#2").leader = "OP09-001"
    st.active = True

    c = TestClient(app)
    r = c.get("/api/state")
    assert r.status_code == 200
    data = r.json()
    assert data["active"] is True
    assert data["me"] is not None
    assert data["opp"] is not None
    assert data["opp"]["hand"] is None  # fair-play


def test_api_cors_headers(tmp_path):
    """L'API doit renvoyer les headers CORS quand un Origin est présent (frontend Next.js)."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/state", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "*"


def test_api_stats_filters(tmp_path):
    """L'endpoint /api/stats/filters retourne les modes et formats distincts."""
    db = tmp_path / "t.db"
    with Store(db) as st:
        for i, (mode, fmt) in enumerate([
            ("ranked", "Standard (Eastern/Nationals/Western — pool identique)"),
            ("direct", "Standard (Eastern/Nationals/Western — pool identique)"),
            ("ranked", "Extra Regulation (sets hors-standard : ST31)"),
        ]):
            rec = MatchRecord(match_id=f"f{i}", mode=mode)
            rec.me = PlayerInfo("me", leader="L1")
            rec.opp = PlayerInfo("opp", leader="E1")
            rec.result = "win"
            st.upsert_match(rec)
            st.conn.execute("UPDATE matches SET format=? WHERE id=?", (fmt, f"f{i}"))
        st.conn.commit()
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/stats/filters")
    assert r.status_code == 200
    data = r.json()
    assert set(data["modes"]) == {"ranked", "direct"}
    assert set(data["formats"]) == {"Standard", "Extra Regulation"}


def test_api_stats_filter_by_mode(tmp_path):
    """L'endpoint /api/stats filtre par mode : ranked seulement."""
    db = tmp_path / "t.db"
    with Store(db) as st:
        for i, (mode, result) in enumerate([
            ("ranked", "win"), ("direct", "loss"), ("ranked", "win"),
        ]):
            rec = MatchRecord(match_id=f"m{i}", mode=mode)
            rec.me = PlayerInfo("me", leader="L1")
            rec.opp = PlayerInfo("opp", leader="E1")
            rec.result = result
            st.upsert_match(rec)
            st.conn.execute("UPDATE matches SET meta='OP10' WHERE id=?", (f"m{i}",))
        st.conn.commit()
    app = create_app(str(db))
    c = TestClient(app)
    # Filtre mode=ranked : 2 matchs (2W 0L)
    r = c.get("/api/stats?mode=ranked")
    data = r.json()
    total_ranked = sum(r["wins"] + r["losses"] for r in data["metas"])
    assert total_ranked == 2
    # Filtre mode=direct : 1 match (0W 1L)
    r = c.get("/api/stats?mode=direct")
    data = r.json()
    total_direct = sum(r["wins"] + r["losses"] for r in data["metas"])
    assert total_direct == 1


def test_api_deck_meta_check(tmp_path, monkeypatch):
    """Meta-Check : compare le deck du joueur à l'archétype moyen du même leader.

    On seed la base avec des decks adverses connus (side='opp', known=1) pour que
    l'ArchetypeModel puisse prédire l'archétype du leader L1. On crée un deck .txt
    temporaire et on monkey-patch le LiveEngine pour qu'il le trouve.
    """
    db = tmp_path / "t.db"
    with Store(db) as st:
        st.import_card_names({"L1": "MonLeader", "A-001": "StapleA", "B-001": "StapleB",
                              "C-001": "TechCard", "D-001": "Underperformer"})
        # 3 decks adverses avec leader L1 : A et B sont des staples (100% présence),
        # C est rare (33%).
        for i, deck in enumerate([
            {"A-001": 4, "B-001": 3, "C-001": 2},
            {"A-001": 4, "B-001": 4, "D-001": 2},
            {"A-001": 3, "B-001": 4},
        ]):
            rec = MatchRecord(match_id=f"opp_{i}", mode="ranked")
            rec.me = PlayerInfo("me", leader="L1")
            rec.opp = PlayerInfo("opp", leader="L1", deck=deck, deck_known=True)
            rec.result = "win"
            st.upsert_match(rec)

    # Deck du joueur : contient A (staple) et C (tech), mais PAS B (staple manquante).
    deck_dir = tmp_path / "decks"
    deck_dir.mkdir()
    deck_file = deck_dir / "test_deck.txt"
    deck_file.write_text("1xL1\n4xA-001\n2xC-001\n")

    app = create_app(str(db))
    live = app.state.live
    # Monkey-patch : le LiveEngine trouve notre deck temporaire.
    monkeypatch.setattr(live, "_resolve_deck", lambda name: deck_file if name else deck_file)
    monkeypatch.setattr(live, "_deck_paths", lambda: [deck_file])

    c = TestClient(app)
    r = c.get(f"/api/decks/test_deck/meta-check")
    assert r.status_code == 200
    data = r.json()

    assert data["deck_name"] == "test_deck"
    assert data["leader"] == "L1"
    assert data["n_historical"] == 3

    # B-001 est une staple (100% présence) absente du deck → staples_missing.
    missing_ids = {c["card_id"] for c in data["staples_missing"]}
    assert "B-001" in missing_ids

    # A-001 est une staple (100% présence) présente dans le deck → staples_present.
    present_ids = {c["card_id"] for c in data["staples_present"]}
    assert "A-001" in present_ids

    # C-001 est rare dans la meta (33% < 25% non, 33% > 25%, donc pas extra).
    # En fait C-001 a 33% de présence, ce qui est > 25%, donc pas extra_card.
    # Vérifions plutôt que A-001 (100%) n'est PAS dans extra_cards.
    extra_ids = {c["card_id"] for c in data["extra_cards"]}
    assert "A-001" not in extra_ids


def test_api_matches_list(tmp_path):
    """L'API /api/matches retourne la liste des parties récentes."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/matches?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2  # _seed_db crée 2 matches
    assert all("id" in m and "result" in m for m in data)


def test_api_match_timeline(tmp_path):
    """L'API /api/matches/{id}/timeline retourne snapshots + events + highlights."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    c = TestClient(app)
    # Récupère un match id.
    matches = c.get("/api/matches").json()
    assert len(matches) > 0
    mid = matches[0]["id"]
    r = c.get(f"/api/matches/{mid}/timeline")
    assert r.status_code == 200
    data = r.json()
    assert "match" in data
    assert "snapshots" in data
    assert "events" in data
    assert "highlights" in data
    assert data["match"]["id"] == mid
    # Les snapshots peuvent être vides (pas de turn_snapshots en seed),
    # mais la structure doit être correcte.
    assert isinstance(data["snapshots"], list)
    assert isinstance(data["events"], list)
    assert isinstance(data["highlights"], list)
    assert "value_timeline" in data
    assert isinstance(data["value_timeline"], list)


def test_api_match_timeline_404(tmp_path):
    """L'API /api/matches/{id}/timeline retourne 404 pour un match inexistant."""
    db = tmp_path / "t.db"
    _seed_db(db)
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/matches/nonexistent/timeline")
    assert r.status_code == 404


# --- Feature flags : gating value_score dans les réponses stats ---

def _seed_db_with_meta(path):
    """Seed une base avec un meta défini et un leader nommé (pour le niveau détail)."""
    with Store(path) as st:
        st.import_card_names({"OP09-001": "Shanks", "OP09-002": "Uta",
                              "OP09-009": "Benn Beckman", "OP09-004": "Shanks",
                              "L1": "MonLeader"})
        for i in range(5):
            rec = MatchRecord(match_id=f"d{i}", mode="ranked")
            rec.me = PlayerInfo("me", leader="L1")
            rec.opp = PlayerInfo("opp", leader="OP09-001")
            rec.result = "win" if i % 2 == 0 else "loss"
            st.upsert_match(rec)
            st.conn.execute("UPDATE matches SET meta='OP10' WHERE id=?", (f"d{i}",))
        st.conn.commit()


def test_api_stats_detail_value_score_off_by_default(tmp_path, monkeypatch):
    """value_score OFF par défaut : value_scores == [] et features présent dans la réponse."""
    monkeypatch.delenv("OPTCG_FEATURE_VALUE_SCORE", raising=False)
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    db = tmp_path / "t.db"
    _seed_db_with_meta(db)
    app = create_app(str(db))
    c = TestClient(app)
    r = c.get("/api/stats?meta=OP10&leader=MonLeader")
    assert r.status_code == 200
    data = r.json()
    assert data["level"] == "detail"
    # value_scores doit être [] (flag OFF → calcul non appelé).
    assert data["value_scores"] == []
    # features doit être présent à la racine.
    assert "features" in data
    assert data["features"]["value_score"] is False


def test_api_stats_detail_value_score_on_with_env(tmp_path, monkeypatch):
    """OPTCG_FEATURE_VALUE_SCORE=1 : value_scores est peuplé (le calcul est appelé)."""
    monkeypatch.setenv("OPTCG_FEATURE_VALUE_SCORE", "1")
    db = tmp_path / "t.db"
    _seed_db_with_meta(db)
    app = create_app(str(db))

    # On espionne value_score_per_card : sans events de deploy dans la seed,
    # la vraie fonction renvoie []. On la mock pour vérifier qu'elle EST appelée
    # (preuve que le gating laisse passer le calcul quand le flag est ON).
    sentinel = [{"card_id": "FAKE-001", "name": "Fake", "n": 3, "avg_value": 5.0,
                 "avg_value_win": 8.0, "avg_value_loss": -1.0, "avg_cost": 3,
                 "avg_early_value": 2.0, "vpd": 1.67, "ci_low": 1.0, "ci_high": 9.0,
                 "significant": True}]
    from optcgsim_tracker.analytics import Analytics
    monkeypatch.setattr(Analytics, "value_score_per_card", lambda self, **kw: sentinel)

    c = TestClient(app)
    r = c.get("/api/stats?meta=OP10&leader=MonLeader")
    assert r.status_code == 200
    data = r.json()
    assert data["level"] == "detail"
    # value_scores doit être peuplé (le calcul a été appelé car flag ON).
    assert data["value_scores"] == sentinel
    assert data["features"]["value_score"] is True


def test_api_stats_features_in_all_levels(tmp_path, monkeypatch):
    """features doit être présent à tous les niveaux de /api/stats."""
    monkeypatch.delenv("OPTCG_FEATURE_VALUE_SCORE", raising=False)
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    db = tmp_path / "t.db"
    _seed_db_with_meta(db)
    app = create_app(str(db))
    c = TestClient(app)

    # Niveau metas
    r = c.get("/api/stats")
    assert "features" in r.json()

    # Niveau meta
    r = c.get("/api/stats?meta=OP10")
    assert "features" in r.json()

    # Niveau détail
    r = c.get("/api/stats?meta=OP10&leader=MonLeader")
    assert "features" in r.json()

