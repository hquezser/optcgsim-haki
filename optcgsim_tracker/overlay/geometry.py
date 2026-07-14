"""Géométrie de l'overlay — partie PURE et testable (aucun import natif au chargement).

Quartz (``CGWindowListCopyWindowInfo``) donne les fenêtres dans un repère **haut-gauche** (origine
en haut de l'écran principal, Y vers le bas). Cocoa/AppKit (``NSWindow setFrame``) utilise un repère
**bas-gauche** (origine en bas, Y vers le haut). La conversion est le piège classique du mac : on
l'isole ici dans des fonctions pures, couvertes par les tests.

``find_game_bounds`` fait l'appel Quartz (import paresseux) ; toute la logique de sélection et de
conversion vit dans ``parse_window_bounds`` / ``compute_overlay_frame``, testables sans pyobjc.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)


def parse_window_bounds(windows: list[dict], owner: str) -> Rect | None:
    """Sélectionne la fenêtre principale de l'app `owner` dans la liste Quartz brute.

    `windows` = sortie de CGWindowListCopyWindowInfo (liste de dicts). On retient les fenêtres de
    couche 0 (fenêtres applicatives normales, pas les overlays/menus système) dont le propriétaire
    correspond à `owner` (insensible à la casse, sous-chaîne), et on renvoie la PLUS GRANDE
    (la fenêtre de jeu, pas une petite fenêtre auxiliaire). None si rien ne correspond.

    Le Rect renvoyé est dans le repère Quartz (haut-gauche).
    """
    owner_l = owner.lower()
    best: Rect | None = None
    for w in windows:
        name = (w.get("kCGWindowOwnerName") or "")
        if owner_l not in name.lower():
            continue
        if w.get("kCGWindowLayer", 0) != 0:
            continue
        b = w.get("kCGWindowBounds") or {}
        try:
            rect = Rect(float(b["X"]), float(b["Y"]), float(b["Width"]), float(b["Height"]))
        except (KeyError, TypeError, ValueError):
            continue
        if rect.area <= 0:
            continue
        if best is None or rect.area > best.area:
            best = rect
    return best


def compute_overlay_frame(game: Rect, screen_h: float, inset: float = 0.0) -> Rect:
    """Convertit le Rect du jeu (Quartz, haut-gauche) en frame Cocoa (bas-gauche) pour NSWindow.

    `screen_h` = hauteur de l'écran principal (points). `inset` rétrécit la frame de N points sur
    chaque bord (utile pour ne pas déborder d'une barre de titre). Voir la dérivation :
        cocoa_bottom = screen_h - quartz_top - hauteur
    """
    x = game.x + inset
    w = game.w - 2 * inset
    h = game.h - 2 * inset
    y = screen_h - game.y - game.h + inset  # bas de la frame, repère Cocoa
    return Rect(x, y, w, h)


@dataclass(frozen=True)
class FollowAction:
    """Décision d'un tick de suivi : frame à appliquer et/ou changement de visibilité."""

    frame: Rect | None = None  # nouvelle frame à appliquer (None = ne pas bouger)
    show: bool | None = None   # True = ré-afficher, False = masquer, None = inchangé

    @property
    def is_noop(self) -> bool:
        return self.frame is None and self.show is None


class WindowFollower:
    """Suit la fenêtre du jeu tick par tick (pur, testable — le natif est dans app.py).

    - Ne demande un déplacement que si la frame a réellement changé (> `epsilon` points),
      au lieu de réappliquer la frame à chaque tick.
    - Masque l'overlay après `miss_grace` ticks consécutifs sans fenêtre de jeu (sim fermé ou
      minimisé) — la tolérance évite de clignoter sur un raté transitoire de Quartz.
    - Ré-affiche et recale dès que la fenêtre réapparaît (restart du sim).
    """

    def __init__(self, miss_grace: int = 10, epsilon: float = 0.5):
        self.miss_grace = miss_grace
        self.epsilon = epsilon
        self._last: Rect | None = None
        self._misses = 0
        self._shown = True

    def force_reapply(self) -> None:
        """Oublie la dernière frame : le prochain tick la réappliquera (menu « Recaler »)."""
        self._last = None

    def tick(self, game: Rect | None, screen_h: float | None) -> FollowAction:
        if game is None or screen_h is None:
            self._misses += 1
            if self._shown and self._misses >= self.miss_grace:
                self._shown = False
                return FollowAction(show=False)
            return FollowAction()
        self._misses = 0
        show = True if not self._shown else None
        self._shown = True
        frame = compute_overlay_frame(game, screen_h)
        last, e = self._last, self.epsilon
        moved = last is None or (
            abs(frame.x - last.x) > e or abs(frame.y - last.y) > e
            or abs(frame.w - last.w) > e or abs(frame.h - last.h) > e
        )
        if moved:
            self._last = frame
            return FollowAction(frame=frame, show=show)
        return FollowAction(show=show)


def find_game_bounds(owner: str = "OPTCGSim") -> Rect | None:
    """Bounds (repère Quartz) de la fenêtre du jeu, ou None. Importe Quartz paresseusement."""
    import Quartz  # type: ignore

    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    return parse_window_bounds(list(windows or []), owner)


def primary_screen_height() -> float:
    """Hauteur (points) de l'écran PRINCIPAL — la référence du repère Quartz.

    Pas ``NSScreen.mainScreen()`` : c'est l'écran qui a le focus clavier, pas le principal —
    faux repère dès que le jeu est sur un autre écran. ``CGDisplayBounds(CGMainDisplayID())``
    est le bon, et appelable hors du main thread (on le relit à chaque tick : gère les
    changements de résolution).
    """
    import Quartz  # type: ignore

    return float(Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size.height)
