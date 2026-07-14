"""Intégration native macOS (Cocoa/AppKit via pyobjc) pour l'overlay.

Non testé unitairement (requiert un écran + une session GUI). Importé uniquement au runtime par
``overlay.app`` quand l'extra ``overlay`` est installé. Toute mutation de NSWindow doit se faire sur
le thread principal (voir ``overlay.app`` qui dispatch via AppHelper.callAfter).
"""

from __future__ import annotations

import objc
from AppKit import (
    NSApp,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSMenu,
    NSMenuItem,
    NSStatusWindowLevel,
    NSVariableStatusItemLength,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSStatusBar,
)
from Foundation import NSObject


def find_overlay_window(title: str):
    """Retrouve le NSWindow créé par pywebview via son titre (robuste aux internes pywebview)."""
    for w in (NSApp().windows() if NSApp() else []):
        try:
            if w.title() == title:
                return w
        except Exception:
            continue
    return None


def apply_overlay_style(ns_window, opacity: float = 1.0) -> None:
    """Always-on-top (au-dessus du plein écran), sans ombre, transparent, click-through."""
    ns_window.setLevel_(NSStatusWindowLevel)
    ns_window.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorFullScreenAuxiliary
        | NSWindowCollectionBehaviorStationary
    )
    ns_window.setOpaque_(False)
    ns_window.setBackgroundColor_(NSColor.clearColor())
    ns_window.setHasShadow_(False)
    ns_window.setAlphaValue_(float(opacity))
    ns_window.setIgnoresMouseEvents_(True)  # click-through par défaut
    # Pas d'icône Dock, pas de vol de focus au jeu.
    if NSApp():
        NSApp().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def set_click_through(ns_window, on: bool) -> None:
    ns_window.setIgnoresMouseEvents_(bool(on))


class _MenuTarget(NSObject):
    """Cible Objective-C des items de menu : relaie vers des callbacks Python."""

    def initWithHandlers_(self, handlers):
        self = objc.super(_MenuTarget, self).init()
        if self is None:
            return None
        self._handlers = handlers  # pyobjc autorise les attributs python sur les sous-classes NSObject
        return self

    def toggleClickThrough_(self, sender):
        self._handlers["toggle_click_through"]()

    def toggleVisible_(self, sender):
        self._handlers["toggle_visible"]()

    def recenter_(self, sender):
        self._handlers["recenter"]()

    def quit_(self, sender):
        self._handlers["quit"]()


def install_status_item(handlers: dict):
    """Crée l'item de barre de menu macOS + son menu. Renvoie (status_item, target, menu).

    `handlers` : dict de callables sous les clés toggle_click_through / toggle_visible / recenter / quit.
    On garde des références (sinon le GC objc les libère et le menu devient inerte).
    """
    target = _MenuTarget.alloc().initWithHandlers_(handlers)
    status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    status_item.button().setTitle_("🎴")

    menu = NSMenu.alloc().init()

    def _item(title, sel):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
        it.setTarget_(target)
        menu.addItem_(it)
        return it

    _item("Interactif (clics)", b"toggleClickThrough:")
    _item("Afficher / Masquer", b"toggleVisible:")
    _item("Recaler sur le jeu", b"recenter:")
    menu.addItem_(NSMenuItem.separatorItem())
    _item("Quitter l'overlay", b"quit:")

    status_item.setMenu_(menu)
    return status_item, target, menu
