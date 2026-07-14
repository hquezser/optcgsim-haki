"""Overlay natif (HUD transparent au-dessus du jeu).

Sous-package optionnel (extra ``overlay``) : encapsule le dashboard web dans une fenêtre native
toujours-au-dessus, sans bordure, transparente et click-through (macOS d'abord).

- ``geometry`` : calculs purs (repère écran, frame de l'overlay) — testable sans natif.
- ``macwin``   : intégration Cocoa/Quartz (pyobjc) — importée paresseusement.
- ``app``      : orchestration (serveur + pywebview + sync de position).
"""
