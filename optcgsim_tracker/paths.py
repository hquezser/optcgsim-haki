"""Résolution multiplateforme des emplacements de données d'OPTCGSim / OPBounty.

Le jeu principal OPTCGSim est en Unity ; l'extension matchmaking OPBounty est en Godot.
Chaque plateforme range ces fichiers différemment. Ce module centralise la résolution pour
que le reste du code n'ait jamais à coder un chemin en dur.

Sécurité : on n'expose volontairement AUCUN accès au fichier de préférences
`com.Batsu.OPTCGSim.plist` (il contient identifiants OPBounty + tokens).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GamePaths:
    """Tous les emplacements utiles. Les chemins peuvent ne pas exister (à vérifier)."""

    app_support: Path        # com.Batsu.OPTCGSim (Unity, données du jeu)
    opbounty: Path           # OPBounty (Godot, matchmaking)
    player_log: Path         # Player.log (Unity, flux live)
    player_log_prev: Path    # Player-prev.log (session précédente)
    resources_assets: Path | None = None  # asset Unity contenant la base de cartes complète
    card_images: Path | None = None       # StreamingAssets/Cards (images par set)

    # --- Dérivés ---
    @property
    def combat_logs(self) -> Path:
        return self.app_support / "CombatLogs"

    @property
    def autosaved_logs(self) -> Path:
        return self.combat_logs / "AutoSaved"

    @property
    def my_matches(self) -> Path:
        return self.opbounty / "my_matches"

    @property
    def opbounty_logs(self) -> Path:
        return self.opbounty / "logs"

    def version_dir(self) -> Path | None:
        """Dossier de la version courante du jeu (ex: '1.40a') contenant Cards/Sets/Formats."""
        if not self.app_support.exists():
            return None
        candidates = [
            p for p in self.app_support.iterdir()
            if p.is_dir() and (p / "Formats").is_dir() and (p / "Cards").is_dir()
        ]
        if not candidates:
            return None
        # La plus récemment modifiée = version active.
        return max(candidates, key=lambda p: p.stat().st_mtime)

    @property
    def formats_dir(self) -> Path | None:
        v = self.version_dir()
        return (v / "Formats") if v else None

    @property
    def cards_dir(self) -> Path | None:
        v = self.version_dir()
        return (v / "Cards") if v else None

    @property
    def sets_dir(self) -> Path | None:
        v = self.version_dir()
        return (v / "Sets") if v else None


def _macos_paths() -> GamePaths:
    home = Path.home()
    app_support = home / "Library/Application Support/com.Batsu.OPTCGSim"
    opbounty = home / "Library/Application Support/Godot/app_userdata/OPBounty"
    logs_dir = home / "Library/Logs/Batsu/OPTCGSim"
    data = Path("/Applications/OPTCGSim.app/Contents/Resources/Data")
    assets = data / "resources.assets"
    images = data / "StreamingAssets/Cards"
    return GamePaths(
        app_support=app_support,
        opbounty=opbounty,
        player_log=logs_dir / "Player.log",
        player_log_prev=logs_dir / "Player-prev.log",
        resources_assets=assets if assets.exists() else None,
        card_images=images if images.exists() else None,
    )


def _linux_paths() -> GamePaths:
    home = Path.home()
    xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    # Unity sous Linux : ~/.config/unity3d/<Company>/<Product>/Player.log
    logs_dir = xdg_config / "unity3d/Batsu/OPTCGSim"
    return GamePaths(
        app_support=xdg_data / "com.Batsu.OPTCGSim",
        opbounty=xdg_data / "godot/app_userdata/OPBounty",
        player_log=logs_dir / "Player.log",
        player_log_prev=logs_dir / "Player-prev.log",
    )


def _windows_paths() -> GamePaths:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    locallow = Path(os.environ.get("USERPROFILE", Path.home())) / "AppData/LocalLow"
    logs_dir = locallow / "Batsu/OPTCGSim"
    return GamePaths(
        app_support=appdata / "com.Batsu.OPTCGSim",
        opbounty=appdata / "Godot/app_userdata/OPBounty",
        player_log=logs_dir / "Player.log",
        player_log_prev=logs_dir / "Player-prev.log",
    )


def detect_paths() -> GamePaths:
    """Renvoie les chemins adaptés à la plateforme courante."""
    override = os.environ.get("OPTCG_APP_SUPPORT")
    if override:
        # Échappatoire pour tests / installations non standard.
        base = Path(override)
        gp = GamePaths(
            app_support=base,
            opbounty=base.parent / "Godot/app_userdata/OPBounty",
            player_log=base / "Player.log",
            player_log_prev=base / "Player-prev.log",
        )
    elif sys.platform == "darwin":
        gp = _macos_paths()
    elif sys.platform.startswith("linux"):
        gp = _linux_paths()
    elif sys.platform.startswith("win"):
        gp = _windows_paths()
    else:
        gp = _macos_paths()

    # Overrides explicites (utiles hors install standard).
    from dataclasses import replace
    ra = os.environ.get("OPTCG_RESOURCES_ASSETS")
    if ra:
        gp = replace(gp, resources_assets=Path(ra))
    ci = os.environ.get("OPTCG_CARD_IMAGES")
    if ci:
        gp = replace(gp, card_images=Path(ci))
    return gp
