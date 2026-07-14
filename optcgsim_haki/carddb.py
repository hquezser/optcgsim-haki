"""Métadonnées des cartes : set d'origine, bloc, et (si dispo localement) couleur/coût/power.

Note importante : seul un sous-ensemble de cartes possède un fichier `Cards/<id>.json` sur le
disque (le reste est embarqué dans le `.pck` du jeu). Les **noms** de cartes, eux, sont présents
en clair dans les logs de partie — c'est le parser qui les collecte (id -> name). carddb se
concentre donc sur ce qui est dérivable de façon fiable : le set (préfixe de l'id) et le bloc.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from .sources import Sources

# Codes couleur Unity -> nom (observés dans cardColors).
COLOR_NAMES = {0: "Red", 1: "Green", 2: "Blue", 3: "Purple", 4: "Black", 5: "Yellow"}
# Codes type de carte.
CARD_TYPE_NAMES = {1: "Character", 2: "Event", 3: "Stage", 4: "Leader"}


def set_prefix(card_id: str) -> str:
    """OP09-001 -> OP09 ; P-998 -> P ; ST31-005 -> ST31."""
    return card_id.split("-", 1)[0]


@dataclass(frozen=True)
class CardMeta:
    card_id: str
    set_code: str
    block: int | None = None
    name: str | None = None
    color: str | None = None
    cost: int | None = None
    power: int | None = None
    counter: int | None = None
    card_type: str | None = None


class CardDB:
    """Index paresseux des cartes/sets disponibles localement."""

    def __init__(self, sources: Sources | None = None):
        self.sources = sources or Sources()
        self._cache: dict[str, CardMeta] = {}

    @cached_property
    def set_to_block(self) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for s in self.sources.sets_raw():
            name = s.get("setName")
            block = s.get("blockNumber")
            if name is not None and block is not None:
                mapping[name] = block
        return mapping

    def meta(self, card_id: str) -> CardMeta:
        if card_id in self._cache:
            return self._cache[card_id]
        sc = set_prefix(card_id)
        block = self.set_to_block.get(sc)
        raw = self.sources.card_raw(card_id)
        if raw and "cardDefinition" in raw:
            d = raw["cardDefinition"]
            colors = d.get("cardColors") or []
            meta = CardMeta(
                card_id=card_id,
                set_code=sc,
                block=block,
                name=d.get("characterName") or None,
                color=COLOR_NAMES.get(colors[0]) if colors else None,
                cost=d.get("cardCost"),
                power=d.get("cardPower"),
                counter=d.get("cardCounter"),
                card_type=CARD_TYPE_NAMES.get(d.get("cardType")),
            )
        else:
            meta = CardMeta(card_id=card_id, set_code=sc, block=block)
        self._cache[card_id] = meta
        return meta
