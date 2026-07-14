"""Structures de données du domaine (un match parsé)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Event:
    """Une action atomique du déroulé de la partie."""

    seq: int
    turn: int
    side: str                 # "me" | "opp"
    type: str                 # draw | deploy | attack | attack_fail | counter | counter_event
                              #   | don | don_attach | end_turn | result
                              #   | ko | effect_remove | trash_bare | life_damage  (Value Score)
    card_id: str | None = None
    target_id: str | None = None
    power: int | None = None
    value: int | None = None  # ex: nb de damage, counter value, don count
    raw: str = ""


@dataclass
class TurnSnapshot:
    """État d'un joueur capturé au début d'un tour."""

    turn: int
    side: str
    hand_ids: list[str] = field(default_factory=list)
    board_ids: list[str] = field(default_factory=list)
    trash_ids: list[str] = field(default_factory=list)
    life: int | None = None
    deck_remaining: int | None = None  # depuis le flux RZ1

    @property
    def hand_count(self) -> int:
        return len(self.hand_ids)


@dataclass
class PlayerInfo:
    side: str                 # "me" | "opp"
    name: str | None = None   # pseudo (anonymisable)
    leader: str | None = None  # card_id du leader
    opening_hand: list[str] = field(default_factory=list)
    mulligan: bool | None = None   # True = a mulligan, False = keep
    deck: dict[str, int] = field(default_factory=dict)  # card_id -> qty (si connu)
    deck_known: bool = False  # True si decklist complète (my_matches), sinon "cartes vues"
    deck_remaining: int | None = None  # cartes restantes en fin de partie (RZ1)
    rating: float | None = None
    rating_delta: float | None = None


@dataclass
class MatchRecord:
    """Résultat complet du parsing d'une partie."""

    match_id: str                       # hash idempotent
    played_at: datetime | None = None   # heure de fin (mtime du log) ou timestamp ranked
    source: str = "autosaved"           # autosaved | live | opbounty
    room_code: str | None = None
    engine_version: str | None = None
    mode: str | None = None             # ranked | direct | unknown
    format: str | None = None
    format_confidence: str | None = None
    meta: str | None = None             # période meta résolue (date + cartes), ex. "OP16"

    me: PlayerInfo = field(default_factory=lambda: PlayerInfo("me"))
    opp: PlayerInfo = field(default_factory=lambda: PlayerInfo("opp"))

    i_went_first: bool | None = None
    my_deck: str | None = None          # nom du deck nommé inféré (None = non identifié)
    result: str | None = None           # win | loss | unknown
    win_reason: str | None = None       # concede | disconnect | damage | inferred | unknown
    duration_s: float | None = None

    events: list[Event] = field(default_factory=list)
    snapshots: list[TurnSnapshot] = field(default_factory=list)

    cards_seen: set[str] = field(default_factory=set)
    # id -> name collecté depuis les lignes "Drew/Deploy ... Name [id]".
    card_names: dict[str, str] = field(default_factory=dict)

    def player(self, side: str) -> PlayerInfo:
        return self.me if side == "me" else self.opp
