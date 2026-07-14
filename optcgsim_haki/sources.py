"""Localisation et lecture brute des sources de données du jeu.

Couche fine au-dessus de :mod:`optcgsim_haki.paths`. Fournit des itérateurs/lecteurs
qui renvoient le contenu brut ; le parsing vit dans :mod:`optcgsim_haki.parser`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .paths import GamePaths, detect_paths

# Garde-fou sécurité : on refuse explicitement de toucher au fichier d'identifiants.
_FORBIDDEN_NAMES = {"com.batsu.optcgsim.plist", "patreon_auth.json", "uinf.tres"}


def _guard(path: Path) -> None:
    if path.name.lower() in _FORBIDDEN_NAMES:
        raise PermissionError(
            f"Lecture refusée : {path.name} contient des données sensibles "
            "(identifiants/tokens) et est volontairement hors périmètre."
        )


@dataclass(frozen=True)
class LogFile:
    """Un fichier de log de partie sur le disque."""

    path: Path
    mtime: datetime  # = heure de FIN de partie pour les AutoSaved (écrits d'un bloc)

    def read_text(self) -> str:
        _guard(self.path)
        return self.path.read_text(errors="ignore")

    def content_hash(self) -> str:
        """Hash stable du contenu — sert de clé idempotente pour la base."""
        return hashlib.sha256(self.read_text().encode("utf-8", "ignore")).hexdigest()[:16]


class Sources:
    """Point d'accès unique aux sources de données du jeu."""

    def __init__(self, paths: GamePaths | None = None):
        self.paths = paths or detect_paths()

    # --- Logs de combat (post-match) ---
    def autosaved_logs(self) -> list[LogFile]:
        d = self.paths.autosaved_logs
        if not d.exists():
            return []
        out = [
            LogFile(p, datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc))
            for p in d.glob("*.log")
        ]
        return sorted(out, key=lambda lf: lf.mtime)

    def manual_logs(self) -> list[LogFile]:
        """Logs sauvegardés manuellement (racine de CombatLogs)."""
        d = self.paths.combat_logs
        if not d.exists():
            return []
        out = [
            LogFile(p, datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc))
            for p in d.glob("*.txt")
        ]
        return sorted(out, key=lambda lf: lf.mtime)

    # --- Flux live ---
    @property
    def player_log(self) -> Path:
        return self.paths.player_log

    # --- OPBounty (ranked) ---
    def my_matches_raw(self) -> dict | None:
        p = self.paths.my_matches
        if not p.exists():
            return None
        _guard(p)
        return json.loads(p.read_text(errors="ignore"))

    # --- Formats ---
    def formats_raw(self) -> Iterator[dict]:
        d = self.paths.formats_dir
        if not d or not d.exists():
            return
        for f in sorted(d.glob("*.json")):
            data = json.loads(f.read_text(errors="ignore"))
            data["_file"] = f.name
            yield data

    # --- Cartes / Sets ---
    def card_raw(self, card_id: str) -> dict | None:
        d = self.paths.cards_dir
        if not d:
            return None
        f = d / f"{card_id}.json"
        if not f.exists():
            return None
        return json.loads(f.read_text(errors="ignore"))

    def sets_raw(self) -> Iterator[dict]:
        d = self.paths.sets_dir
        if not d or not d.exists():
            return
        for f in sorted(d.glob("*.json")):
            yield json.loads(f.read_text(errors="ignore"))
