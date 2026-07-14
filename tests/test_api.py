"""Tests du backend FastAPI : endpoints /api/state, /api/stats, /api/decks."""

from fastapi.testclient import TestClient

from optcgsim_haki.api.server import create_app
from optcgsim_haki.db.store import Store
from optcgsim_haki.model import MatchRecord, PlayerInfo


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


