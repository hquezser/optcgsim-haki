"""Source d'état exact : lit le JSON écrit par le mod BepInEx OPTCGSim Live Export.

Le mod (Partie A du plan OPTCGSIM_LIVE_EXACT_STATE_PLAN.md) lit l'état complet du jeu
dans le runtime Unity (GameStateManager) et l'écrit dans un fichier JSON atomique.
Ce module (Partie B) consomme ce JSON et le mappe vers le même format de payload que
``LiveEngine._state_payload()``, remplaçant l'inférence depuis les logs par l'état exact.

Schéma du JSON du mod (schema 1) :
    {
      "schema": 1,
      "ts": 1730000000.0,
      "turn": 7,
      "active_player": 0,
      "me": 0,                    # index du joueur local (0 ou 1)
      "players": {
        "0": {
          "leader": "OP09-001",
          "life": [{"cardId":"OP01-020","faceUp":false}, ...],
          "hand": [{"cardId":"OP16-017","uid":42,"faceUp":true}, ...],
          "deck": [{"cardId":"...","uid":...}, ...],
          "board": [{"cardId":"...","uid":...,"attachedDon":2}, ...],
          "trash": [...], "stage": [...],
          "activeDon": 5, "restedDon": 2
        },
        "1": { ... }
      }
    }

Éthique : l'état exact contient la main et le deck adverses. Fair-play par défaut
(hand adverse = None sauf reveal_all). Usage hors-ligne / revue / casual uniquement.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Chemin par défaut du fichier écrit par le mod BepInEx.
# macOS : ~/Library/Application Support/com.Batsu.OPTCGSim/live_exact_state.json
_DEFAULT_FILENAME = "live_exact_state.json"


def default_exact_state_path(app_support: Path) -> Path:
    """Chemin par défaut du fichier d'état exact dans le dossier App Support du jeu."""
    return app_support / _DEFAULT_FILENAME


class ExactStateSource:
    """Lit le JSON exact écrit par le mod BepInEx et le mappe au payload /api/state.

    Utilisation ::
        src = ExactStateSource(path)
        if src.available():
            raw = src.read()
            if raw:
                payload = src.to_payload(raw, reveal_all=False)
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._mtime: float = 0.0
        self._cache: dict | None = None

    def available(self) -> bool:
        """Vrai si le fichier d'état exact existe (le mod est chargé)."""
        return self.path.exists()

    def is_fresh(self, max_age_s: float = 15.0) -> bool:
        """Vrai si le fichier existe et a été modifié récemment (garde-fou fraîcheur).

        Le mod n'écrit le JSON QUE pendant une partie ; entre deux parties le fichier
        reste sur disque mais est périmé. On n'utilise l'état exact que si le mtime
        date de moins de ``max_age_s`` secondes (défaut 15s).
        """
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            # Fichier disparu entre le available() et le stat (race) : périmé.
            return False
        return (time.time() - mtime) < max_age_s

    def read(self) -> dict | None:
        """Lit et parse le JSON s'il a changé depuis la dernière lecture.

        Retourne None si le fichier n'existe pas, est vide, ou échoue au parsing
        (lecture partielle pendant écriture atomique — on ignore gracieusement).
        """
        if not self.available():
            return None
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        if mtime == self._mtime and self._cache is not None:
            return self._cache
        try:
            text = self.path.read_text(errors="ignore")
            data = json.loads(text)
        except (json.JSONDecodeError, OSError, ValueError) as e:
            # Lecture pendant écriture atomique (.tmp -> replace) : on ignore.
            log.debug("exact_state: parse échec (écriture en cours ?) : %s", e)
            return self._cache  # garde le dernier cache valide
        if not isinstance(data, dict):
            return None
        self._mtime = mtime
        self._cache = data
        return data

    def to_payload(self, raw: dict, reveal_all: bool = False) -> dict:
        """Mappe le JSON du mod vers le même format que LiveEngine._state_payload().

        Garde fair-play : la main adverse n'est exposée que si ``reveal_all=True``.
        Sinon ``hand=None`` et ``hand_count=len(hand)``.
        """
        players = raw.get("players", {})
        me_idx = str(raw.get("me", 0))
        opp_idx = "1" if me_idx == "0" else "0"

        me_raw = players.get(me_idx)
        opp_raw = players.get(opp_idx)

        if me_raw is None:
            return {"active": True, "me": None, "opp": None}

        payload = {
            "active": True,
            "room_code": None,
            "version": None,
            "result": None,
            "win_reason": None,
            "reveal_all": reveal_all,
            "me": self._player_dict(me_raw, is_me=True, reveal_all=reveal_all),
            "opp": self._player_dict(opp_raw, is_me=False, reveal_all=reveal_all),
            # Marqueur : l'état provient du mod (exact), pas du log (inféré).
            "exact_state": True,
        }
        return payload

    @staticmethod
    def _player_dict(p_raw: dict | None, is_me: bool,
                     reveal_all: bool) -> dict | None:
        """Convertit un joueur du schema mod vers le format _player_dict de LiveState."""
        if p_raw is None:
            return None

        def _card_list(cards: list) -> list[dict]:
            """Convertit une liste de GameStateCard en [{id, name}]."""
            out = []
            for c in cards or []:
                cid = c.get("cardId") or c.get("card_id")
                out.append({"id": cid, "name": cid})  # name rempli plus tard par le tracker
            return out

        hand = _card_list(p_raw.get("hand", []))
        board = _card_list(p_raw.get("board", []))
        trash = _card_list(p_raw.get("trash", []))
        life_cards = p_raw.get("life", [])
        deck = p_raw.get("deck", [])

        leader = p_raw.get("leader")
        active_don = p_raw.get("activeDon", 0)
        rested_don = p_raw.get("restedDon", 0)
        don_on_field = (active_don or 0) + (rested_don or 0)

        d = {
            "tag": "me" if is_me else "opp",
            "side": "me" if is_me else "opp",
            "leader": leader,
            "leader_name": None,  # rempli par LiveEngine via card_meta
            "life": len(life_cards),  # vie = nombre de life cards
            "deck_remaining": len(deck),
            "don_on_field": don_on_field,
            "board": board,
            "trash": trash,
            "hand_count": len(hand),
            "hand_count_approx": False,  # exact, pas approximatif
            "modifiers": {},  # le mod ne gère pas les modifiers (v1)
        }

        # Fair-play : la main adverse n'est exposée que si reveal_all.
        if is_me or reveal_all:
            d["hand"] = hand
        else:
            d["hand"] = None  # cachée

        # MON deck restant (ids) -> sert au calcul EXACT des odds de pioche côté engine.
        # Uniquement le mien (pas de fair-play à violer : c'est ma propre information).
        if is_me:
            d["deck_ids"] = [c["id"] for c in _card_list(deck) if c.get("id")]

        return d

    def reset(self) -> None:
        """Réinitialise le cache (nouvelle partie)."""
        self._mtime = 0.0
        self._cache = None
