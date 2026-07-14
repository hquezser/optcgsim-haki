"""Parseur du fichier `my_matches` d'OPBounty (parties classées).

Format : un objet JSON {"matches": [ <match>, ... ]} où chaque <match> est une LISTE
positionnelle à DEUX slots de joueur (slot A en indices pairs bas, slot B décalés). Le joueur
local peut être dans l'un OU l'autre slot ; on détecte son pseudo (le plus fréquent sur tout
l'historique) et on oriente chaque match de son point de vue.

Indices cartographiés par observation :

    slot A: [0] pseudo  [2] rating   [5] résultat   [17] deck   [20] delta rating
    slot B: [6] pseudo  [8] rating   [11] résultat  [18] deck   [21] delta rating
    communs: [14] durée (s)   [16] timestamp ISO   [22] [[main slot A], "keep"|"mulligan"]

La main de départ [22] n'est disponible que pour le slot A (limitation du format).
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from datetime import datetime

_DECK_ENTRY = re.compile(r"^(\d+)x(.+)$")


def _parse_deck(entries) -> tuple[dict[str, int], str | None, str | None]:
    """-> (deck {id:qty}, leader_id, platform). Le leader = 1ère entrée 1x."""
    deck: dict[str, int] = {}
    leader: str | None = None
    platform: str | None = None
    if not isinstance(entries, list):
        return deck, leader, platform
    for e in entries:
        if not isinstance(e, str):
            continue
        m = _DECK_ENTRY.match(e)
        if not m:
            platform = e  # ex: "Mobile"
            continue
        qty, cid = int(m.group(1)), m.group(2)
        deck[cid] = deck.get(cid, 0) + qty
        if leader is None:
            leader = cid
    return deck, leader, platform


def _to_float(x) -> float | None:
    try:
        return float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None


@dataclass
class RankedMatch:
    timestamp: datetime | None
    me: str
    opp: str
    my_result: str | None
    my_rating: float | None
    opp_rating: float | None
    my_delta: float | None
    duration_s: float | None
    my_deck: dict[str, int] = field(default_factory=dict)
    opp_deck: dict[str, int] = field(default_factory=dict)
    my_leader: str | None = None
    opp_leader: str | None = None
    opp_platform: str | None = None
    opening_hand: list[str] = field(default_factory=list)
    mulligan: bool | None = None


def detect_local_player(data: dict) -> str | None:
    """Le joueur local = le pseudo présent dans le plus de matchs (slot A ou B)."""
    counter: collections.Counter = collections.Counter()
    for m in data.get("matches", []):
        if not isinstance(m, list) or len(m) < 7:
            continue
        if isinstance(m[0], str):
            counter[m[0]] += 1
        if isinstance(m[6], str):
            counter[m[6]] += 1
    return counter.most_common(1)[0][0] if counter else None


def parse_my_matches(data: dict, local_player: str | None = None) -> list[RankedMatch]:
    if local_player is None:
        local_player = detect_local_player(data)

    out: list[RankedMatch] = []
    for m in data.get("matches", []):
        if not isinstance(m, list) or len(m) < 19:
            continue

        def g(i):
            return m[i] if i < len(m) else None

        ts = None
        if isinstance(g(16), str):
            try:
                ts = datetime.fromisoformat(g(16))
            except ValueError:
                ts = None

        a_name = str(g(0)) if g(0) is not None else ""
        b_name = str(g(6)) if g(6) is not None else ""
        a_deck, a_leader, a_plat = _parse_deck(g(17))
        b_deck, b_leader, b_plat = _parse_deck(g(18))

        a_hand: list[str] = []
        a_mull = None
        h = g(22)
        if isinstance(h, list) and h and isinstance(h[0], list):
            a_hand = [c for c in h[0] if isinstance(c, str)]
            if len(h) > 1 and isinstance(h[1], str):
                a_mull = h[1].lower() != "keep"

        # Oriente du point de vue local : local en slot A par défaut, sinon on échange.
        local_is_a = (local_player is None) or (b_name != local_player)

        if local_is_a:
            rm = RankedMatch(
                timestamp=ts, me=a_name, opp=b_name,
                my_result=g(5) if isinstance(g(5), str) else None,
                my_rating=_to_float(g(2)), opp_rating=_to_float(g(8)),
                my_delta=_to_float(g(20)), duration_s=_to_float(g(14)),
                my_deck=a_deck, opp_deck=b_deck,
                my_leader=a_leader, opp_leader=b_leader, opp_platform=b_plat,
                opening_hand=a_hand, mulligan=a_mull,
            )
        else:
            rm = RankedMatch(
                timestamp=ts, me=b_name, opp=a_name,
                my_result=g(11) if isinstance(g(11), str) else None,
                my_rating=_to_float(g(8)), opp_rating=_to_float(g(2)),
                my_delta=_to_float(g(21)), duration_s=_to_float(g(14)),
                my_deck=b_deck, opp_deck=a_deck,
                my_leader=b_leader, opp_leader=a_leader, opp_platform=a_plat,
                opening_hand=[],  # main du slot A uniquement -> indisponible côté local
                mulligan=None,
            )
        out.append(rm)
    return out
