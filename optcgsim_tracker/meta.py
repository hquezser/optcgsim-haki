"""Définition des « meta » (périodes de jeu) et rattachement d'une partie à son meta.

Un meta = la dernière sortie meta-définissante (set OP principal, ou EB/PRB pour les sous-metas
« .5 ») à la date de la partie. Les dates de sortie sont extraites de l'OPBounty.pck. Des
overrides éditables permettent d'ajouter des frontières non liées à une sortie (ex. banlist).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .cardmeta import iter_pck_objects

# Sets pris en compte comme frontières de meta (ST/promo exclus).
_META_SET = re.compile(r"^(OP\d{2}|EB\d{2}|PRB\d{2})$")
_OP_MAIN = re.compile(r"^OP\d{2}$")


@dataclass(frozen=True)
class Meta:
    code: str        # set d'origine (OP15, EB03…)
    label: str       # libellé affiché (OP15, OP14.5 (EB03)…)
    start: str       # date de début "YYYY-MM-DD"


def set_release_dates(pck_path: Path) -> dict[str, str]:
    """{set_code: date de sortie 'YYYY-MM-DD'} extrait des champs Date du pck."""
    if not pck_path or not pck_path.exists():
        return {}
    data = pck_path.read_bytes().decode("latin-1")
    rel: dict[str, str] = {}
    for d in iter_pck_objects(data):
        num, date = d.get("Number"), d.get("Date")
        if not num or not date:
            continue
        setc = num.split("-", 1)[0]
        day = date[:10]
        if setc not in rel or day < rel[setc]:
            rel[setc] = day
    return rel


def build_meta_timeline(paths, overrides_path: Path | None = None) -> list[Meta]:
    """Chronologie des metas : sorties OP/EB/PRB + overrides, triées par date.

    Labels : un set OP principal -> son code (OP15). Un EB/PRB après OP_N -> sous-meta
    'OP_N.5 (EB03)', '.6' s'il y en a plusieurs.
    """
    rel = set_release_dates(paths.opbounty / "OPBounty.pck")
    releases = sorted(((s, d) for s, d in rel.items() if _META_SET.match(s)),
                      key=lambda x: x[1])
    metas: list[Meta] = []
    last_op, last_op_day, sub = None, None, 0
    for code, day in releases:
        if _OP_MAIN.match(code):
            last_op, last_op_day, sub = code, day, 0
            label = code
        else:
            # Un EB/PRB sorti le même jour qu'un set OP fait partie de ce lancement
            # (pas un sous-meta distinct) -> on l'ignore.
            if day == last_op_day:
                continue
            sub += 1
            label = f"{last_op}.{4 + sub} ({code})" if last_op else code
        metas.append(Meta(code=code, label=label, start=day))

    # Overrides éditables (ban-driven, etc.) : [{"label":..,"start":"YYYY-MM-DD","code":?}]
    if overrides_path and overrides_path.exists():
        try:
            for o in json.loads(overrides_path.read_text()):
                metas.append(Meta(code=o.get("code", o["label"]), label=o["label"],
                                  start=o["start"][:10]))
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    return sorted(metas, key=lambda m: m.start)


def meta_of(date: str | None, timeline: list[Meta]) -> Meta | None:
    """Le meta actif à la date donnée (dernier dont start <= date)."""
    if not date or not timeline:
        return None
    day = date[:10]
    found = None
    for m in timeline:
        if m.start <= day:
            found = m
        else:
            break
    return found


def _set_prefix(card_id: str) -> str:
    return card_id.split("-", 1)[0]


def card_meta(card_ids, timeline: list[Meta], release: dict[str, str]) -> Meta | None:
    """Meta déduit du set le plus récent présent parmi les cartes (gère les queues anticipées)."""
    newest = None
    for cid in card_ids:
        d = release.get(_set_prefix(cid))
        if d and (newest is None or d > newest):
            newest = d
    return meta_of(newest, timeline)


def resolve_meta(date: str | None, card_ids, timeline: list[Meta],
                 release: dict[str, str]) -> Meta | None:
    """Meta d'une partie = le plus RÉCENT entre la période jouée et le set le plus récent
    présent dans les cartes. Corrige les queues anticipées (ex. OP16 joué avant sa sortie)."""
    by_date = meta_of(date, timeline)
    by_card = card_meta(card_ids, timeline, release)
    cands = [m for m in (by_date, by_card) if m]
    return max(cands, key=lambda m: m.start) if cands else None
