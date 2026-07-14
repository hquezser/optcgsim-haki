"""Tests du module exact_state : source d'état exact (mod BepInEx)."""

import json
import os
from pathlib import Path

from optcgsim_tracker.exact_state import ExactStateSource, default_exact_state_path


def _sample_raw(me_idx: int = 0) -> dict:
    """JSON d'exemple au schema du mod BepInEx."""
    return {
        "schema": 1,
        "ts": 1730000000.0,
        "turn": 5,
        "active_player": 0,
        "me": me_idx,
        "players": {
            "0": {
                "leader": "PRB01-001",
                "life": [{"cardId": "L1", "faceUp": False}, {"cardId": "L2", "faceUp": False}],
                "hand": [{"cardId": "OP16-017", "uid": 42, "faceUp": True},
                         {"cardId": "OP09-014", "uid": 43, "faceUp": True}],
                "deck": [{"cardId": "D1", "uid": 1}, {"cardId": "D2", "uid": 2},
                         {"cardId": "D3", "uid": 3}],
                "board": [{"cardId": "EB04-004", "uid": 10, "attachedDon": 2}],
                "trash": [{"cardId": "TR1", "uid": 99}],
                "stage": [],
                "activeDon": 3,
                "restedDon": 2,
            },
            "1": {
                "leader": "OP09-001",
                "life": [{"cardId": "Y1", "faceUp": False}, {"cardId": "Y2", "faceUp": False},
                         {"cardId": "Y3", "faceUp": False}],
                "hand": [{"cardId": "OP09-015", "uid": 50, "faceUp": True}],
                "deck": [{"cardId": "D4", "uid": 4}],
                "board": [{"cardId": "OP09-009", "uid": 20, "attachedDon": 1}],
                "trash": [{"cardId": "OP09-011", "uid": 21}],
                "stage": [],
                "activeDon": 2,
                "restedDon": 1,
            },
        },
    }


def _write_json(path: Path, data: dict) -> None:
    """Écriture atomique (comme le mod)."""
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def test_exact_state_not_available(tmp_path):
    """available() retourne False si le fichier n'existe pas."""
    src = ExactStateSource(tmp_path / "nonexistent.json")
    assert not src.available()
    assert src.read() is None


def test_exact_state_read_and_cache(tmp_path):
    """read() parse le JSON et le met en cache."""
    p = tmp_path / "state.json"
    _write_json(p, _sample_raw())
    src = ExactStateSource(p)
    assert src.available()
    raw = src.read()
    assert raw is not None
    assert raw["schema"] == 1
    assert raw["turn"] == 5
    # Deuxième lecture : cache (même mtime)
    raw2 = src.read()
    assert raw2 is raw  # même objet (cache)


def test_exact_state_read_handles_corrupt_json(tmp_path):
    """read() ignore gracieusement un JSON corrompu (lecture pendant écriture)."""
    p = tmp_path / "state.json"
    _write_json(p, _sample_raw())
    src = ExactStateSource(p)
    # Première lecture OK
    assert src.read() is not None
    # Écrire du JSON invalide
    p.write_text("{corrupt json")
    # read() doit retourner le cache précédent (pas crash)
    raw = src.read()
    assert raw is not None
    assert raw["schema"] == 1


def test_exact_state_to_payload_basic(tmp_path):
    """to_payload mappe correctement les champs de base."""
    src = ExactStateSource(tmp_path / "state.json")
    payload = src.to_payload(_sample_raw(), reveal_all=False)

    assert payload["exact_state"] is True
    assert payload["active"] is True

    me = payload["me"]
    assert me["leader"] == "PRB01-001"
    assert me["life"] == 2  # 2 life cards
    assert me["deck_remaining"] == 3
    assert me["don_on_field"] == 5  # activeDon(3) + restedDon(2)
    assert len(me["board"]) == 1
    assert me["board"][0]["id"] == "EB04-004"
    assert len(me["hand"]) == 2
    assert me["hand_count"] == 2


def test_exact_state_to_payload_fair_play(tmp_path):
    """Sans reveal_all, la main adverse est cachée (hand=None)."""
    src = ExactStateSource(tmp_path / "state.json")
    payload = src.to_payload(_sample_raw(), reveal_all=False)

    opp = payload["opp"]
    assert opp["hand"] is None
    assert opp["hand_count"] == 1  # count visible, contenu caché


def test_exact_state_to_payload_reveal_all(tmp_path):
    """Avec reveal_all, la main adverse est exposée."""
    src = ExactStateSource(tmp_path / "state.json")
    payload = src.to_payload(_sample_raw(), reveal_all=True)

    opp = payload["opp"]
    assert opp["hand"] is not None
    assert len(opp["hand"]) == 1
    assert opp["hand"][0]["id"] == "OP09-015"


def test_exact_state_to_payload_me_idx_1(tmp_path):
    """Si me=1, l'adversaire est le joueur 0 (inversion)."""
    src = ExactStateSource(tmp_path / "state.json")
    payload = src.to_payload(_sample_raw(me_idx=1), reveal_all=False)

    me = payload["me"]
    opp = payload["opp"]
    assert me["leader"] == "OP09-001"  # joueur 1 = me
    assert opp["leader"] == "PRB01-001"  # joueur 0 = opp


def test_exact_state_to_payload_opp_life_exact(tmp_path):
    """La vie adverse est exacte (len des life cards), pas inférée."""
    src = ExactStateSource(tmp_path / "state.json")
    payload = src.to_payload(_sample_raw(), reveal_all=False)
    opp = payload["opp"]
    assert opp["life"] == 3  # 3 life cards


def test_exact_state_to_payload_trash_exposed(tmp_path):
    """Le trash adverse est public (toujours exposé, pas de fair-play)."""
    src = ExactStateSource(tmp_path / "state.json")
    payload = src.to_payload(_sample_raw(), reveal_all=False)
    opp = payload["opp"]
    assert len(opp["trash"]) == 1
    assert opp["trash"][0]["id"] == "OP09-011"


def test_exact_state_to_payload_hand_count_approx_false(tmp_path):
    """hand_count_approx=False car le compte est exact (pas inféré)."""
    src = ExactStateSource(tmp_path / "state.json")
    payload = src.to_payload(_sample_raw(), reveal_all=False)
    assert payload["me"]["hand_count_approx"] is False
    assert payload["opp"]["hand_count_approx"] is False


def test_exact_state_to_payload_missing_player(tmp_path):
    """Si un joueur manque (partie pas commencée), to_payload gère le cas."""
    src = ExactStateSource(tmp_path / "state.json")
    raw = _sample_raw()
    del raw["players"]["1"]
    payload = src.to_payload(raw, reveal_all=False)
    assert payload["opp"] is None
    assert payload["me"] is not None


def test_exact_state_reset(tmp_path):
    """reset() efface le cache (nouvelle partie)."""
    p = tmp_path / "state.json"
    _write_json(p, _sample_raw())
    src = ExactStateSource(p)
    assert src.read() is not None
    src.reset()
    assert src._cache is None
    assert src._mtime == 0.0


def test_exact_state_default_path():
    """default_exact_state_path retourne le chemin dans App Support."""
    from optcgsim_tracker.paths import GamePaths
    p = Path("/tmp/fake_app_support")
    result = default_exact_state_path(p)
    assert result == p / "live_exact_state.json"
    assert result.name == "live_exact_state.json"


def test_exact_state_to_payload_empty_zones(tmp_path):
    """Les zones vides (hand, board, trash) sont gérées correctement."""
    src = ExactStateSource(tmp_path / "state.json")
    raw = _sample_raw()
    raw["players"]["0"]["hand"] = []
    raw["players"]["0"]["board"] = []
    raw["players"]["0"]["trash"] = []
    payload = src.to_payload(raw, reveal_all=False)
    me = payload["me"]
    assert me["hand"] == []
    assert me["hand_count"] == 0
    assert me["board"] == []
    assert me["trash"] == []


def test_exact_state_is_fresh_recent(tmp_path):
    """is_fresh() renvoie True si le fichier vient d'être écrit."""
    p = tmp_path / "state.json"
    _write_json(p, _sample_raw())
    src = ExactStateSource(p)
    # Le fichier vient d'être écrit : mtime ~ maintenant.
    assert src.is_fresh() is True


def test_exact_state_is_fresh_stale(tmp_path):
    """is_fresh() renvoie False si le fichier a un mtime ancien (entre deux parties)."""
    p = tmp_path / "state.json"
    _write_json(p, _sample_raw())
    # Vieillir le mtime : 1h dans le passé (3600s > max_age_s par défaut 15s).
    vieux = 1_000_000_000  # timestamp arbitraire ancien
    os.utime(p, (vieux, vieux))
    src = ExactStateSource(p)
    assert src.is_fresh() is False


def test_exact_state_is_fresh_missing(tmp_path):
    """is_fresh() renvoie False si le fichier n'existe pas (OSError géré)."""
    src = ExactStateSource(tmp_path / "nonexistent.json")
    assert src.is_fresh() is False
