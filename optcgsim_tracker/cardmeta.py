"""Métadonnées COMPLÈTES des cartes (coût, counter, power, couleur, type…).

Source principale : la base embarquée dans l'OPBounty.pck (Godot), au format JSON, qui contient
pour ~2650 cartes : Number, Name, Cost, Counterplus (valeur de counter), Power, Life, Color,
CardType, Subtypes, Rarity. Complétée par les Cards/*.json Unity locaux pour les sets les plus
récents éventuellement absents du pck (ST31, etc.). Résultat mis en cache JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

# Début d'objet JSON (clé entre guillemets) — point d'ancrage pour extraire chaque objet-carte
# du pck par appariement d'accolades (cf. _extract_object). Un ancien regex `[^{}]*` excluait à
# tort toute carte dont la DESCRIPTION contient des accolades de trait (ex. {Red-Haired Pirates}),
# soit ~200 cartes ; on apparie donc désormais les accolades en tenant compte des chaînes.
_OBJ_START = re.compile(r'\{"')

# Bump à chaque évolution du parseur pck pour invalider les caches `.cardmeta.json` existants.
_PARSER_VERSION = 2


def _extract_object(s: str, start: int, cap: int = 20000) -> str | None:
    """À partir du '{' en position `start`, renvoie l'objet JSON équilibré, ou None.

    Conscient des chaînes (les accolades à l'intérieur d'une valeur texte ne comptent pas) et des
    échappements. Borné à `cap` caractères : un objet englobant (ex. {"groups":[... tout le set]})
    dépasse la borne -> None -> ignoré ; seuls les objets-carte plats sont capturés.
    """
    depth = 0
    in_str = False
    esc = False
    for i in range(start, min(len(s), start + cap)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def iter_pck_objects(data: str):
    """Itère les dicts JSON des objets-carte du pck (ceux ayant un 'Number' + 'CardType')."""
    for m in _OBJ_START.finditer(data):
        obj = _extract_object(data, m.start())
        if not obj or '"Number"' not in obj or '"CardType"' not in obj:
            continue
        try:
            d = json.loads(obj)
        except (json.JSONDecodeError, ValueError):
            continue
        num = d.get("Number")
        if isinstance(num, str) and num:
            yield d


@dataclass
class CardMeta:
    card_id: str
    name: str | None = None
    cost: int | None = None
    counter: int = 0          # valeur de counter (0 si la carte n'en a pas)
    power: int | None = None
    life: int | None = None
    colors: list[str] | None = None
    card_type: str | None = None   # Leader | Character | Event | Stage
    subtypes: list[str] | None = None
    rarity: str | None = None
    attributes: list[str] | None = None   # Strike / Slash / Special / Ranged / Wisdom
    description: str = ""                  # texte d'effet (pour en extraire les "effect keys")


def _to_int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_pck_cards(pck_path: Path) -> dict[str, CardMeta]:
    if not pck_path or not pck_path.exists():
        return {}
    data = pck_path.read_bytes().decode("latin-1")
    out: dict[str, CardMeta] = {}
    for d in iter_pck_objects(data):
        num = d["Number"]
        colors = [c for c in str(d.get("Color", "")).split(";") if c] or None
        subs = [s for s in str(d.get("Subtypes", "")).split(";") if s] or None
        attrs = [a for a in str(d.get("Attribute", "")).split(";") if a] or None
        out[num] = CardMeta(
            card_id=num, name=d.get("Name"),
            cost=_to_int(d.get("Cost")), counter=_to_int(d.get("Counterplus")) or 0,
            power=_to_int(d.get("Power")), life=_to_int(d.get("Life")),
            colors=colors, card_type=d.get("CardType"), subtypes=subs,
            rarity=d.get("Rarity"), attributes=attrs, description=d.get("Description") or "",
        )
    return out


_COLOR_NAMES = {0: "Red", 1: "Green", 2: "Blue", 3: "Purple", 4: "Black", 5: "Yellow"}
_TYPE_NAMES = {1: "Character", 2: "Event", 3: "Stage", 4: "Leader"}


def parse_local_cards(cards_dir: Path | None) -> dict[str, CardMeta]:
    """Cards/*.json Unity (cardDefinition) -> CardMeta. Complète les sets récents."""
    if not cards_dir or not cards_dir.exists():
        return {}
    out: dict[str, CardMeta] = {}
    for f in cards_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text()).get("cardDefinition", {})
        except (json.JSONDecodeError, OSError):
            continue
        cid = d.get("cardID")
        if not cid:
            continue
        colors = [_COLOR_NAMES[c] for c in d.get("cardColors", []) if c in _COLOR_NAMES] or None
        out[cid] = CardMeta(
            card_id=cid, name=d.get("characterName") or None,
            cost=d.get("cardCost"), counter=d.get("cardCounter") or 0,
            power=d.get("cardPower"), life=d.get("cardLife"),
            colors=colors, card_type=_TYPE_NAMES.get(d.get("cardType")),
        )
    return out


_RE_LEADER_IS = re.compile(
    r'^\[(?P<who>[^\]]+)\]\s*Leader is .*?\[<mark><link="(?P<id>[A-Z0-9-]+)">')
_RE_LIFE_PREFIXED = re.compile(r'^\[(?P<who>[^\]]+)\]\s*Life:\s*(?P<life>\d+)')


def learn_leader_life_from_logs(autosaved_dir: Path | None,
                                cache_path: Path | None = None) -> dict[str, int]:
    """Déduit la vie de base de chaque leader depuis les logs AutoSaved.

    Les cartes des sets récents (ex. OP16) ne sont pas encore dans l'OPBounty.pck : leur vie
    manque donc à `card_meta`. Mais chaque log AutoSaved contient « Leader is X [id] » et les
    snapshots « Life: N » des deux joueurs. La vie de base = le MAX observé pour ce leader
    (la vie ne monte qu'au setup, sauf soin rare). Sert de repli pour la vie live + le lethal.

    Résultat mis en cache JSON (clé = nb de logs + mtime du plus récent).
    """
    if not autosaved_dir or not autosaved_dir.exists():
        return {}
    logs = sorted(autosaved_dir.glob("*.log"))
    sig = [len(logs), max((p.stat().st_mtime for p in logs), default=0)]
    if cache_path and cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text())
            if raw.get("_sig") == sig:
                return {k: int(v) for k, v in raw.get("life", {}).items()}
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    life: dict[str, int] = {}
    for p in logs:
        try:
            lines = p.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        who_leader: dict[str, str] = {}      # tag -> leader_id (dans CE log)
        for ln in lines:
            ml = _RE_LEADER_IS.match(ln)
            if ml:
                who_leader[ml.group("who")] = ml.group("id")
                continue
            mlf = _RE_LIFE_PREFIXED.match(ln)
            if mlf:
                lid = who_leader.get(mlf.group("who"))
                if lid:
                    v = int(mlf.group("life"))
                    if v > life.get(lid, 0):
                        life[lid] = v

    if cache_path and life:
        try:
            cache_path.write_text(json.dumps({"_sig": sig, "life": life}))
        except OSError:
            pass
    return life


def build_card_meta(paths, cache_path: Path | None = None) -> dict[str, CardMeta]:
    """Fusionne pck (principal) + Cards json locaux (complément), avec cache JSON.

    Le cache porte `_PARSER_VERSION` : tout changement du parseur l'invalide automatiquement
    (sans quoi un ancien cache masquerait, p. ex., les cartes récupérées par le fix accolades).
    """
    pck = paths.opbounty / "OPBounty.pck"
    newest_mtime = max((p.stat().st_mtime for p in (pck, paths.cards_dir or Path("/nonexistent"))
                        if p and p.exists()), default=0)
    if cache_path and cache_path.exists() and cache_path.stat().st_mtime >= newest_mtime:
        try:
            raw = json.loads(cache_path.read_text())
            if raw.get("_v") == _PARSER_VERSION:
                return {k: CardMeta(**v) for k, v in raw.get("cards", {}).items()}
        except (json.JSONDecodeError, TypeError, OSError, AttributeError):
            pass

    meta = parse_pck_cards(pck)
    for cid, m in parse_local_cards(paths.cards_dir).items():
        meta.setdefault(cid, m)  # le pck prime ; le local complète les manquants

    if cache_path and meta:
        try:
            cache_path.write_text(json.dumps(
                {"_v": _PARSER_VERSION, "cards": {k: asdict(v) for k, v in meta.items()}}))
        except OSError:
            pass
    return meta
