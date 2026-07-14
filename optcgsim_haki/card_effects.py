"""Classification des effets de cartes à partir de leur texte (card_stats.json).

Le log nous dit QUEL verbe (Trash / Return / Send), mais pas DEPUIS QUELLE ZONE la carte est
déplacée. Seul l'effet de la carte SOURCE le précise :

    "return 1 of your Characters ... to the owner's hand"  -> déplace un Character (BOARD)
    "Place ... opponent's Characters ... at the bottom of the deck"  -> Character (BOARD)
    "trash 1 card from your hand"  /  "add ... card from your trash"  -> autre zone (PAS board)

On classe donc chaque carte source en « capacités » de retrait de board, par phrase :
    - "bounce"     : renvoie un Character vers une main
    - "deck"       : place/renvoie un Character vers le deck (top/bottom)
    - "trash_char" : trash un Character (coût d'un perso, retrait...)

Un KO se lit déjà via la ligne "Destroyed" (toujours un Character) : pas besoin de capacité.
La classification est volontairement par phrase pour ne pas mélanger deux effets distincts
d'une même carte (ex. Gecko Moria OP14-080 : "K.O. ... Character" + "trash 3 cards from hand").
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_CARD_STATS = Path(__file__).parent / "data" / "card_stats.json"

_cache: dict[str, frozenset] | None = None


# Verbe AVANT « Character » = la carte en jeu est l'OBJET déplacé (retrait de board).
# Ordre important : "Character ... from your trash/deck" = la zone est la SOURCE (fouille),
# pas un retrait — le verbe vient alors après, ou « trash/deck » est précédé de « your/the ».
_RE_BOUNCE = re.compile(r"\b(?:return|send)\b[^.]*\bcharacters?\b[^.]*\bhand\b")
_RE_DECK = re.compile(r"\b(?:place|return|send|put)\b[^.]*\bcharacters?\b[^.]*\b(?:bottom|top)\b[^.]*\bdeck\b")
# "trash ... Character" SANS « card » entre les deux : un Character (carte en jeu) mis au trash
# (coût d'un perso, retrait). Exclut "trash N card(s) from hand/deck" (coût depuis une autre zone)
# et "Character ... from your trash" (zone source, ordre inverse). Le KO se lit via "Destroyed".
_RE_TRASH_CHAR = re.compile(r"\btrash\b(?:(?!\bcards?\b)[^.])*\bcharacters?\b")


def caps_from_text(text: str | None) -> frozenset:
    """Capacités de retrait de board déduites du texte d'effet (par clause)."""
    caps: set[str] = set()
    if not text:
        return frozenset(caps)
    # Découpe aussi sur ':' pour séparer le COÛT (avant) de l'EFFET (après).
    for seg in re.split(r"[.\n;:]", text):
        s = seg.lower()
        if "character" not in s:
            continue  # n'agit pas sur une carte en jeu -> pas un retrait de board
        if _RE_BOUNCE.search(s):
            caps.add("bounce")
        if _RE_DECK.search(s):
            caps.add("deck")
        if _RE_TRASH_CHAR.search(s):
            caps.add("trash_char")
    return frozenset(caps)


def _load() -> dict[str, frozenset]:
    global _cache
    if _cache is None:
        _cache = {}
        try:
            data = json.loads(_CARD_STATS.read_text())
            for cid, d in data.get("cards", {}).items():
                c = caps_from_text(d.get("text"))
                if c:
                    _cache[cid] = c
        except Exception:
            _cache = {}
    return _cache


def source_caps(card_id: str) -> frozenset:
    """Capacités de retrait de board de la carte source (vide si inconnue)."""
    return _load().get(card_id, frozenset())


def warm() -> None:
    """Force le chargement+classification maintenant (à appeler au démarrage, hors partie).

    Évite le hoquet ~20 ms qui surviendrait sinon sur la 1re ligne d'effet rencontrée en live.
    """
    _load()
