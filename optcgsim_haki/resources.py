"""Résolution robuste des ressources embarquées (frontend statique, données).

Utilise importlib.resources pour fonctionner après `pip install` (où les fichiers
sont dans site-packages/optcgsim_haki/) ET en développement (où les fichiers
sont à la racine du repo).

Usage :
    from optcgsim_haki.resources import static_dir, has_frontend
    if has_frontend():
        serve_static(static_dir())
"""

from __future__ import annotations

import pathlib
from importlib.resources import files

_PACKAGE = "optcgsim_haki"


def static_dir() -> pathlib.Path | None:
    """Retourne le chemin vers le frontend statique pré-buildé.

    Ordre de résolution :
    1. optcgsim_haki/static/ (dans le package — pip install)
    2. frontend/out/ (racine du repo — mode dev)

    Retourne None si aucun frontend n'est trouvé.
    """
    # 1. Dans le package (pip install ou copie manuelle).
    try:
        p = pathlib.Path(str(files(_PACKAGE) / "static"))
        if p.exists() and (p / "index.html").exists():
            return p
    except Exception:
        pass

    # 2. Racine du repo (mode dev) — remonte depuis optcgsim_haki/ vers le repo.
    try:
        p = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "out"
        if p.exists() and (p / "index.html").exists():
            return p
    except Exception:
        pass

    return None


def has_frontend() -> bool:
    """Indique si un frontend statique est disponible (package ou dev)."""
    return static_dir() is not None
