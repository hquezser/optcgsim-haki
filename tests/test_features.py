"""Tests du système de feature flags (v1 : masquer l'approximatif)."""

import pytest

from optcgsim_tracker.features import feature, all_features, _DEFAULTS


# --- feature() : défauts ---

def test_feature_defaults():
    # Fiable : exposé par défaut.
    assert feature("stats") is True
    assert feature("mulligan_reco") is True
    # Approximatif : masqué par défaut.
    assert feature("live_lethal") is False
    assert feature("live_opp_hand") is False
    assert feature("value_score") is False


def test_feature_unknown_default_false():
    # Un flag inconnu n'est jamais activé par défaut.
    assert feature("does_not_exist") is False


# --- feature() : overrides env ---

def test_feature_env_override_on(monkeypatch):
    monkeypatch.setenv("OPTCG_FEATURE_LIVE_LETHAL", "1")
    assert feature("live_lethal") is True


def test_feature_env_override_off(monkeypatch):
    # Désactive explicitement un flag fiable par défaut.
    monkeypatch.setenv("OPTCG_FEATURE_STATS", "0")
    assert feature("stats") is False


@pytest.mark.parametrize("val", ["0", "false", "False", "no", ""])
def test_feature_env_falsy_values(monkeypatch, val):
    monkeypatch.setenv("OPTCG_FEATURE_LIVE_LETHAL", val)
    assert feature("live_lethal") is False


def test_feature_env_truthy_when_not_falsy(monkeypatch):
    # Toute valeur non listée comme falsy = ON.
    monkeypatch.setenv("OPTCG_FEATURE_LIVE_LETHAL", "yes")
    assert feature("live_lethal") is True


def test_feature_env_empty_string_is_off(monkeypatch):
    # Variable définie mais vide -> OFF (utile pour "désactiver sans supprimer").
    monkeypatch.setenv("OPTCG_FEATURE_STATS", "")
    assert feature("stats") is False


# --- feature() : OPTCG_PROFILE=advanced ---

def test_feature_profile_advanced_all_on(monkeypatch):
    monkeypatch.setenv("OPTCG_PROFILE", "advanced")
    for name in _DEFAULTS:
        assert feature(name) is True, name


def test_feature_profile_advanced_case_insensitive(monkeypatch):
    monkeypatch.setenv("OPTCG_PROFILE", "ADVANCED")
    assert feature("live_lethal") is True
    assert feature("value_score") is True


def test_feature_profile_advanced_overrides_env_off(monkeypatch):
    # advanced a priorité sur un OPTCG_FEATURE_*=0.
    monkeypatch.setenv("OPTCG_PROFILE", "advanced")
    monkeypatch.setenv("OPTCG_FEATURE_LIVE_LETHAL", "0")
    assert feature("live_lethal") is True


def test_feature_profile_other_value_no_effect(monkeypatch):
    monkeypatch.setenv("OPTCG_PROFILE", "basic")
    assert feature("live_lethal") is False
    assert feature("stats") is True


def test_feature_no_env_uses_defaults(monkeypatch):
    # S'assure qu'aucune variable OPTCG_* n'est présente dans l'environnement de test.
    for k in list(_DEFAULTS) + ["OPTCG_PROFILE"]:
        monkeypatch.delenv(k.upper().replace("OPTCG_FEATURE_", "OPTCG_FEATURE_"), raising=False)
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    for name, expected in _DEFAULTS.items():
        assert feature(name) is expected


# --- all_features() ---

def test_all_features_keys():
    feats = all_features()
    assert set(feats.keys()) == set(_DEFAULTS.keys())


def test_all_features_defaults(monkeypatch):
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    feats = all_features()
    for name, expected in _DEFAULTS.items():
        assert feats[name] is expected, name


def test_all_features_advanced(monkeypatch):
    monkeypatch.setenv("OPTCG_PROFILE", "advanced")
    feats = all_features()
    assert all(feats.values())


# --- LiveEngine._apply_feature_gating ---

def _sample_payload() -> dict:
    """Payload factice couvrant tous les champs approximatifs à filtrer."""
    return {
        "lethal": {"is_lethal": True},
        "next_plays": [{"card_id": "X"}],
        "next_plays_phase": "mid",
        "next_plays_turn": 4,
        "trigger_risk": {"pct": 12},
        "archetype": {"leader_name": "Luffy"},
        "draw_odds": {"pool": 40, "per_card": []},
        "opp": {"hand": ["OP09-015"], "life": 3, "leader": "OP09-001"},
        "me": {"leader": "PRB01-001"},
    }


def _make_engine():
    """Construit un LiveEngine minimal sans DB réelle (le gating n'en a pas besoin)."""
    from optcgsim_tracker.engine import LiveEngine
    # On évite __init__ (DB, caches, sources) : on instancie l'objet à la main.
    eng = LiveEngine.__new__(LiveEngine)
    return eng


def test_apply_feature_gating_log_mode(monkeypatch):
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    monkeypatch.delenv("OPTCG_FEATURE_LIVE_LETHAL", raising=False)
    eng = _make_engine()
    payload = _sample_payload()
    out = eng._apply_feature_gating(payload, exact=False)

    # features présent et reflete les défauts.
    assert "features" in out
    assert out["features"]["live_lethal"] is False
    assert out["features"]["stats"] is True

    # Champs approximatifs retirés.
    assert "lethal" not in out
    assert "next_plays" not in out
    assert "next_plays_phase" not in out
    assert "next_plays_turn" not in out
    assert "trigger_risk" not in out
    assert "archetype" not in out
    assert "draw_odds" not in out

    # opp.hand / opp.life masqués (None), mais le reste de opp intact.
    assert out["opp"]["hand"] is None
    assert out["opp"]["life"] is None
    assert out["opp"]["leader"] == "OP09-001"


def test_apply_feature_gating_exact_mode(monkeypatch):
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    eng = _make_engine()
    payload = _sample_payload()
    out = eng._apply_feature_gating(payload, exact=True)

    # En mode exact, les panneaux live sont forcés ON.
    assert out["features"]["live_lethal"] is True
    assert out["features"]["live_opp_hand"] is True
    assert out["features"]["live_opp_life"] is True
    assert out["features"]["live_menaces"] is True
    assert out["features"]["live_trigger_risk"] is True
    assert out["features"]["live_archetype"] is True
    assert out["features"]["live_draw_odds"] is True

    # Champs conservés.
    assert out["lethal"] == {"is_lethal": True}
    assert out["draw_odds"] == {"pool": 40, "per_card": []}
    assert out["next_plays"] == [{"card_id": "X"}]
    assert out["next_plays_phase"] == "mid"
    assert out["next_plays_turn"] == 4
    assert out["trigger_risk"] == {"pct": 12}
    assert out["archetype"] == {"leader_name": "Luffy"}
    assert out["opp"]["hand"] == ["OP09-015"]
    assert out["opp"]["life"] == 3


def test_apply_feature_gating_env_override(monkeypatch):
    # Activer live_lethal via env, même en mode LOG -> champ conservé.
    monkeypatch.setenv("OPTCG_FEATURE_LIVE_LETHAL", "1")
    eng = _make_engine()
    payload = _sample_payload()
    out = eng._apply_feature_gating(payload, exact=False)
    assert out["features"]["live_lethal"] is True
    assert "lethal" in out
    # Les autres restent masqués.
    assert "archetype" not in out


def test_apply_feature_gating_no_opp_safe(monkeypatch):
    # Pas de clé "opp" -> ne crash pas.
    eng = _make_engine()
    payload = {"lethal": {"x": 1}}
    out = eng._apply_feature_gating(payload, exact=False)
    assert "lethal" not in out
    assert "opp" not in out


# --- Panneau défense (fiable) : construit par l'engine, le gating ne fait que l'opt-out ---

def _payload_with_defense() -> dict:
    d = _sample_payload()
    d["defense"] = {"my_life": 4, "my_blockers": 2, "my_counter_pool": 9000,
                    "opp_attacks": 3, "opp_power": 17000, "opp_don": 5,
                    "opp_leader_known": True}
    return d


def test_gating_keeps_defense_by_default(monkeypatch):
    """live_defense ON par défaut : la défense traverse le gating même si tout
    l'inféré (lethal compris) est retiré."""
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    eng = _make_engine()
    out = eng._apply_feature_gating(_payload_with_defense(), exact=False)
    assert "lethal" not in out
    assert out["defense"]["my_counter_pool"] == 9000
    assert out["features"]["live_defense"] is True


def test_gating_defense_flag_off(monkeypatch):
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    monkeypatch.setenv("OPTCG_FEATURE_LIVE_DEFENSE", "0")
    eng = _make_engine()
    out = eng._apply_feature_gating(_payload_with_defense(), exact=False)
    assert "defense" not in out


def test_merge_defense_sim():
    """Les champs de simulation (vies à risque, alerte lethal) ne sont fusionnés que
    quand le lethal a pu être calculé (leaders connus)."""
    from optcgsim_tracker.engine import LiveEngine
    d = {"my_counter_pool": 2000}
    LiveEngine._merge_defense_sim(d, None)
    assert "lives_at_risk" not in d and "opp_can_lethal" not in d
    LiveEngine._merge_defense_sim(d, {"lives_at_risk": 2, "opp_can_lethal": True})
    assert d["lives_at_risk"] == 2 and d["opp_can_lethal"] is True


def test_gating_exact_forces_defense_on(monkeypatch):
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    monkeypatch.setenv("OPTCG_FEATURE_LIVE_DEFENSE", "0")
    eng = _make_engine()
    out = eng._apply_feature_gating(_payload_with_defense(), exact=True)
    assert out["features"]["live_defense"] is True
    assert "defense" in out


def test_gating_reliable_draw_odds_survive(monkeypatch):
    """live_draw_odds OFF, mais odds marquées reliable (deck identifié strictement ou
    mode exact) -> conservées. Non fiables -> retirées."""
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    eng = _make_engine()
    p = _sample_payload()
    p["draw_odds"] = {"pool": 40, "per_card": [], "mode": "approx", "reliable": True}
    out = eng._apply_feature_gating(p, exact=False)
    assert "draw_odds" in out

    p2 = _sample_payload()  # reliable absent -> approximatif -> retiré
    out2 = eng._apply_feature_gating(p2, exact=False)
    assert "draw_odds" not in out2


def test_feature_live_defense_default_on():
    assert feature("live_defense") is True


# --- Intégration : profil FIABLE par défaut sur une vraie partie (fixture) ---

def test_default_profile_payload_end_to_end(monkeypatch, tmp_path):
    """Sans profil advanced : le payload d'une partie réelle expose defense + counters_spent
    (exact/public) et AUCUN panneau inféré (lethal, menaces, archétype, odds)."""
    monkeypatch.delenv("OPTCG_PROFILE", raising=False)
    for k in ("LIVE_DEFENSE", "LIVE_LETHAL", "LIVE_MENACES"):
        monkeypatch.delenv("OPTCG_FEATURE_" + k, raising=False)
    # Hermétique : pas de decks nommés de la machine hôte (sinon draw_odds "reliable"
    # pourrait légitimement apparaître et rendre le test dépendant de l'environnement).
    monkeypatch.setenv("OPTCG_APP_SUPPORT", str(tmp_path))
    from .conftest import FIXTURES
    from optcgsim_tracker.engine import LiveEngine

    srv = LiveEngine(str(tmp_path / "t.db"), reveal_all=False)
    for line in (FIXTURES / "match_autosaved.log").read_text().splitlines():
        srv.state.feed_line(line)
    payload = srv._state_payload()

    # Fiable présent.
    assert payload["features"]["live_defense"] is True
    assert "defense" in payload
    d = payload["defense"]
    assert d["my_counter_pool"] >= 0 and isinstance(d["opp_can_lethal"], bool)
    for side in ("me", "opp"):
        cs = payload[side]["counters_spent"]
        assert cs["count"] >= 0 and cs["total"] >= 0
    # La fixture contient des "Discard ... for Counter N" -> au moins un joueur a compté.
    assert (payload["me"]["counters_spent"]["count"]
            + payload["opp"]["counters_spent"]["count"]) > 0

    # Inféré absent.
    for k in ("lethal", "next_plays", "archetype", "draw_odds", "trigger_risk"):
        assert k not in payload, k
    assert payload["opp"]["hand"] is None
    assert payload["opp"]["life"] is None
