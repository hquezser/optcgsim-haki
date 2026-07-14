"""Extraction de la base COMPLÈTE de noms de cartes depuis l'asset Unity du jeu.

OPTCGSim embarque toutes les cartes (deck builder) dans `resources.assets`. Les chaînes y sont
stockées de façon très régulière : chaque carte apparaît comme

    <cardID>
    <cardID>      (l'identifiant est répété)
    <nom de la carte>

On extrait les chaînes imprimables (équivalent `strings`, en pur Python) puis on lit ce motif.
Résultat mis en cache JSON pour éviter de rescanner l'asset (~33 Mo) à chaque fois.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Run de caractères imprimables ASCII (équivalent `strings -n 2`).
_PRINTABLE = re.compile(rb"[\x20-\x7e]{2,}")
# Un identifiant de carte strict.
_CARD_ID = re.compile(r"^(?:OP|ST|EB|PRB)\d{2}-\d{3}$|^P-[0-9A-Z]+$")
# Préfixes à ignorer (ce ne sont pas des noms de carte).
_SKIP_PREFIX = ("Action.", "Trigger.", "ButtonChoice", "Passive.", "OnPlay.")


def _extract_strings(data: bytes) -> list[str]:
    return [m.group().decode("ascii", "ignore") for m in _PRINTABLE.finditer(data)]


def extract_card_names(assets_path: Path) -> dict[str, str]:
    """Renvoie {cardID: nom} depuis resources.assets. Vide si chemin invalide."""
    if not assets_path or not assets_path.exists():
        return {}
    strings = _extract_strings(assets_path.read_bytes())
    names: dict[str, str] = {}
    for i in range(len(strings) - 2):
        a, b, c = strings[i], strings[i + 1], strings[i + 2]
        if _CARD_ID.match(a) and a == b and not _CARD_ID.match(c) \
                and not c.startswith(_SKIP_PREFIX):
            names.setdefault(a, c)
    return names


def load_card_names(assets_path: Path | None, cache_path: Path | None = None) -> dict[str, str]:
    """Charge depuis le cache si à jour, sinon extrait et met en cache.

    Le cache est invalidé si l'asset est plus récent (nouvelle version du jeu).
    """
    if cache_path and cache_path.exists():
        if not assets_path or not assets_path.exists() \
                or cache_path.stat().st_mtime >= assets_path.stat().st_mtime:
            try:
                return json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    names = extract_card_names(assets_path) if assets_path else {}
    if cache_path and names:
        try:
            cache_path.write_text(json.dumps(names))
        except OSError:
            pass
    return names
