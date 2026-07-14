"""Détection du format/pool de jeu à partir des cartes réellement vues dans une partie.

Le mode n'est pas écrit dans les logs. On le déduit en croisant les cartes vues avec les banlists
des formats (`Formats/*.json` : bannedSets / bannedCards / bannedBlocks / bannedPair1/2).

- Une carte d'un set banni PAR TOUS les formats compétitifs (ex. ST31-36) => Extra Regulation.
- Sinon, on renvoie les formats compatibles (aucune carte vue interdite).
- `bannedPair1/2` = groupes "restreints" : sert à départager des formats par ailleurs identiques.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .carddb import set_prefix
from .sources import Sources


@dataclass
class FormatVerdict:
    sets_seen: list[str]
    compatible_formats: list[str]
    extra_regulation_sets: list[str]
    verdict: str
    confidence: str  # "high" | "medium" | "low"
    per_format: dict[str, list[str]] = field(default_factory=dict)  # nom -> violations


class FormatDetector:
    def __init__(self, sources: Sources | None = None, formats: list[dict] | None = None):
        # `formats` permet l'injection directe (tests) sans dépendre de l'installation.
        if formats is not None:
            self.sources = None
            self.formats = formats
        else:
            self.sources = sources or Sources()
            self.formats = list(self.sources.formats_raw())

    @staticmethod
    def _signature(fmt: dict) -> tuple:
        """Signature des contraintes APPLIQUÉES (sets + cartes bannis).

        On ignore bannedBlocks/bannedPair : faute de mapping bloc et de sémantique de paire
        vérifiée, on ne les applique pas — deux formats identiques sur sets+cartes sont donc
        indistinguables par le contenu d'un deck (ex. Eastern/Nationals/Western).
        """
        return (
            tuple(sorted(fmt.get("bannedSets", []))),
            tuple(sorted(fmt.get("bannedCards", []))),
        )

    def _banned_everywhere(self) -> set[str]:
        """Sets bannis par l'intersection de tous les formats (= hors-standard partout)."""
        if not self.formats:
            return set()
        common: set[str] | None = None
        for fmt in self.formats:
            bs = set(fmt.get("bannedSets", []))
            common = bs if common is None else (common & bs)
        return common or set()

    def detect(self, cards_seen: set[str]) -> FormatVerdict:
        sets_seen = sorted({set_prefix(c) for c in cards_seen})
        per_format: dict[str, list[str]] = {}
        compatible: list[str] = []

        for fmt in self.formats:
            name = fmt.get("formatName", fmt.get("_file", "?"))
            banned_sets = set(fmt.get("bannedSets", []))
            banned_cards = set(fmt.get("bannedCards", []))
            banned_blocks = set(fmt.get("bannedBlocks", []))  # rarement peuplé

            violations: list[str] = []
            for c in cards_seen:
                if c in banned_cards:
                    violations.append(f"{c} (carte bannie)")
                elif set_prefix(c) in banned_sets:
                    violations.append(f"{c} (set {set_prefix(c)} banni)")
            # banned_blocks : nécessiterait le mapping bloc, ignoré si vide.
            _ = banned_blocks

            per_format[name] = sorted(set(violations))
            if not violations:
                compatible.append(name)

        extra = [s for s in sets_seen if s in self._banned_everywhere()]

        # Regroupe les formats compatibles par signature de banlist : des formats au pool
        # IDENTIQUE (ex. Eastern/Nationals/Western) sont indistinguables par le contenu d'un
        # deck — on les considère comme un même pool plutôt que de prétendre les départager.
        sig_groups: dict[tuple, list[str]] = {}
        for fmt in self.formats:
            if fmt.get("formatName") in compatible:
                sig_groups.setdefault(self._signature(fmt), []).append(fmt["formatName"])

        if extra:
            verdict = f"Extra Regulation (sets hors-standard : {extra})"
            confidence = "high"
        elif len(compatible) == 1:
            verdict = f"Standard — {compatible[0]}"
            confidence = "high"
        elif len(sig_groups) == 1 and compatible:
            # Tous les formats compatibles partagent le même pool -> certitude haute.
            names = "/".join(sorted(compatible))
            verdict = f"Standard ({names} — pool identique)"
            confidence = "high"
        elif compatible:
            verdict = f"Standard — compatible : {compatible}"
            confidence = "medium"
        else:
            verdict = "Indéterminé"
            confidence = "low"

        return FormatVerdict(
            sets_seen=sets_seen,
            compatible_formats=compatible,
            extra_regulation_sets=extra,
            verdict=verdict,
            confidence=confidence,
            per_format=per_format,
        )
