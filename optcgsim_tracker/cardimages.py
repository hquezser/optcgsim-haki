"""Résolution des fichiers d'image de cartes (StreamingAssets/Cards/<set>/<id>(_small).jpg|png)."""

from __future__ import annotations

from pathlib import Path

from .carddb import set_prefix

_CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def resolve_image(card_images_dir: Path | None, card_id: str, small: bool = True) -> Path | None:
    """Chemin du fichier image d'une carte, ou None. Essaie miniature puis pleine, jpg puis png."""
    if not card_images_dir:
        return None
    set_dir = card_images_dir / set_prefix(card_id)
    if not set_dir.is_dir():
        return None
    suffixes = ["_small", ""] if small else ["", "_small"]
    for suf in suffixes:
        for ext in (".jpg", ".png", ".jpeg"):
            p = set_dir / f"{card_id}{suf}{ext}"
            if p.is_file():
                return p
    return None


def content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
