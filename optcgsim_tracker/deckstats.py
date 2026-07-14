"""Statistiques d'un deck (courbe de coût, counters, couleurs, types) pour le deckbuilding."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import hypergeometric as hg
from .cardmeta import CardMeta

_ENTRY = re.compile(r"^(\d+)x(.+)$")
_BRACKET = re.compile(r"\[([^\]]+)\]")

# Mots-clés d'effet pertinents (normalisés). On ignore le bruit type "DON!! x1", "Rush"… selon besoin.
_EFFECT_KEYS = {
    "On Play", "When Attacking", "Blocker", "Counter", "Activate: Main", "Activate:Main",
    "On K.O.", "Your Turn", "Opponent's Turn", "Once Per Turn", "On Block", "Trigger",
    "On Your Opponent's Attack", "End of Your Turn", "DON!! x1", "DON!! x2", "Rush", "Double Attack",
    "Banish",
}


def _norm_key(k: str) -> str:
    return k.replace("Activate:Main", "Activate: Main").strip()


def effect_keys(description: str) -> list[str]:
    """Mots-clés d'effet entre crochets présents dans une description."""
    out = []
    for k in _BRACKET.findall(description or ""):
        nk = _norm_key(k)
        if nk in _EFFECT_KEYS:
            out.append(nk)
    return out


@dataclass
class Deck:
    name: str
    path: Path | None
    cards: dict[str, int] = field(default_factory=dict)  # id -> qty (hors leader)
    leader: str | None = None


def parse_deck_file(path: Path) -> Deck:
    deck = Deck(name=path.stem, path=path)
    for line in path.read_text(errors="ignore").splitlines():
        m = _ENTRY.match(line.strip())
        if not m:
            continue
        qty, cid = int(m.group(1)), m.group(2)
        if deck.leader is None:
            deck.leader = cid          # 1re entrée = leader
        else:
            deck.cards[cid] = deck.cards.get(cid, 0) + qty
    return deck


@dataclass
class DeckStats:
    name: str
    leader: str | None
    leader_name: str | None
    total: int                     # cartes hors leader (deck = 50 normalement)
    curve: dict[int, int]          # coût -> nb de cartes
    counters: dict[int, int]       # valeur de counter -> nb de cartes (0/1000/2000…)
    counter_total: int             # nb de cartes avec un counter > 0
    colors: dict[str, int]
    types: dict[str, int]          # Category : Character / Event / Stage
    subtypes: dict[str, int]       # Features : traits (Sky Island, Vassals, …)
    power: dict[int, int]          # courbe de puissance
    rarities: dict[str, int]
    attributes: dict[str, int]     # Strike / Slash / Special / Ranged / Wisdom
    effect_keys: dict[str, int]    # On Play / Blocker / Counter / …
    effects_total: int             # cartes avec un effet (description non vide)
    triggers_total: int            # cartes avec [Trigger]
    unknown: list[str]             # cartes sans métadonnées (exclues des stats)

    @property
    def counter_1000(self) -> int:
        return self.counters.get(1000, 0)

    @property
    def counter_2000(self) -> int:
        return self.counters.get(2000, 0)


def compute_stats(deck: Deck, meta: dict[str, CardMeta]) -> DeckStats:
    curve: Counter = Counter()
    counters: Counter = Counter()
    colors: Counter = Counter()
    types: Counter = Counter()
    subtypes: Counter = Counter()
    power: Counter = Counter()
    rarities: Counter = Counter()
    attributes: Counter = Counter()
    ekeys: Counter = Counter()
    unknown: list[str] = []
    total = counter_total = effects_total = triggers_total = 0

    for cid, qty in deck.cards.items():
        total += qty
        m = meta.get(cid)
        if not m:
            unknown.append(cid)
            continue
        if m.cost is not None:
            curve[m.cost] += qty
        if m.power is not None:
            power[m.power] += qty
        counters[m.counter] += qty
        if m.counter > 0:
            counter_total += qty
        for col in (m.colors or []):
            colors[col] += qty
        types[m.card_type or "?"] += qty
        for sub in (m.subtypes or []):
            subtypes[sub] += qty
        for a in (m.attributes or []):
            attributes[a] += qty
        if m.rarity:
            rarities[m.rarity] += qty
        keys = effect_keys(m.description)
        for k in set(keys):
            if k != "Trigger":
                ekeys[k] += qty
        if (m.description or "").strip():
            effects_total += qty
        if "Trigger" in keys:
            triggers_total += qty

    lm = meta.get(deck.leader) if deck.leader else None
    return DeckStats(
        name=deck.name, leader=deck.leader,
        leader_name=lm.name if lm else None,
        total=total, curve=dict(sorted(curve.items())),
        counters=dict(sorted(counters.items())), counter_total=counter_total,
        colors=dict(colors.most_common()), types=dict(types.most_common()),
        subtypes=dict(subtypes.most_common()),
        power=dict(sorted(power.items())), rarities=dict(rarities.most_common()),
        attributes=dict(attributes.most_common()), effect_keys=dict(ekeys.most_common()),
        effects_total=effects_total, triggers_total=triggers_total,
        unknown=sorted(unknown),
    )


def opening_odds(deck: Deck, meta: dict[str, CardMeta], leader_life: int = 5) -> dict:
    """Probabilités hypergéométriques d'ouverture pour un deck.

    Renvoie, pour chaque carte connue du deck, la probabilité de la voir dans la
    main d'ouverture (5 cartes) et après mulligan, plus des probas deck-level
    (trigger/counter en main, trigger en vies). Tout est en POURCENTAGE arrondi
    à 1 décimale. Cartes inconnues ignorées (cohérent avec compute_stats).
    """
    per_card = []
    N = 0
    triggers_total = 0
    counter_total = 0
    for cid, qty in deck.cards.items():
        m = meta.get(cid)
        if not m:
            continue
        N += qty
        if "Trigger" in effect_keys(m.description):
            triggers_total += qty
        if m.counter > 0:
            counter_total += qty
        per_card.append({
            "card_id": cid,
            "name": m.name,
            "qty": qty,
        })

    if N <= 0:
        return {
            "deck_size": 0,
            "hand_size": 5,
            "per_card": [],
            "deck_level": {
                "trigger_in_hand": 0.0,
                "trigger_in_life": 0.0,
                "counter_in_hand": 0.0,
                "life_size": leader_life,
            },
        }

    for c in per_card:
        c["p_opening"] = round(100 * hg.p_at_least_one(N, c["qty"], 5), 1)
        c["p_mulligan"] = round(100 * hg.p_mulligan(N, c["qty"], 5), 1)

    per_card.sort(key=lambda c: (-c["qty"], c["name"]))

    return {
        "deck_size": N,
        "hand_size": 5,
        "per_card": per_card,
        "deck_level": {
            "trigger_in_hand": round(100 * hg.p_at_least_one(N, triggers_total, 5), 1),
            "trigger_in_life": round(100 * hg.p_at_least_one(N, triggers_total, leader_life), 1),
            "counter_in_hand": round(100 * hg.p_at_least_one(N, counter_total, 5), 1),
            "life_size": leader_life,
        },
    }
