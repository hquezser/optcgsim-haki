"""Orchestration de l'overlay : serveur (thread) + fenêtre pywebview + sync de position.

macOS d'abord. pywebview occupe le thread principal (exigence Cocoa) ; le serveur FastAPI et la
boucle de synchronisation tournent dans des threads daemon. Toute mutation de NSWindow est
re-dispatchée sur le thread principal via ``AppHelper.callAfter``.
"""

from __future__ import annotations

import os
import sys
import threading

from . import geometry


def run_overlay(db_path: str = "optcg.db", port: int = 8765, owner: str = "OPTCGSim",
                opacity: float = 1.0, autostart_server: bool = True,
                reveal_all: bool = False, advanced: bool = False,
                zone: str | None = None, zone2: str | None = None,
                hud_debug: bool = False) -> int:
    if sys.platform != "darwin":
        print("L'overlay n'est pour l'instant disponible que sur macOS.")
        return 2

    # Fiable par défaut (philosophie v1) : le HUD n'affiche que l'exact/public — défense,
    # statut, odds si decklist connue. --advanced réactive les panneaux inférés (lethal
    # offensif, menaces, vie adverse estimée). En mode exact (mod), l'engine force tout ON
    # car tout devient vrai. Jamais la main adverse : compatible fair-play.
    if advanced and autostart_server:
        os.environ["OPTCG_PROFILE"] = "advanced"

    try:
        import webview  # extra 'overlay'
        from Foundation import NSMakeRect
        from PyObjCTools import AppHelper

        from . import macwin  # importe AppKit
    except ImportError:
        print("L'overlay requiert l'extra optionnel. Installe-le :")
        print("    pip install -e '.[overlay]'")
        return 2

    server = None
    if autostart_server:
        from ..api.server import serve_in_thread
        server, _ = serve_in_thread(db_path, port, reveal_all=reveal_all)

    title = "OPTCGSim Overlay"
    # Zone du HUD (en % de la fenêtre du jeu) et contour de calage -> querystring de la page.
    params = []
    if zone:
        params.append("zone=" + zone)
    if zone2:
        params.append("zone2=" + zone2)
    if hud_debug:
        params.append("debug=1")
    qs = ("?" + "&".join(params)) if params else ""
    url = f"http://127.0.0.1:{port}/overlay{qs}"
    window = webview.create_window(
        title, url=url, frameless=True, transparent=True, on_top=True,
        easy_drag=False, width=380, height=600, x=40, y=80,
    )

    state = {"ns": None, "click_through": True, "visible": True, "status": None}
    stop = threading.Event()
    # Suit la fenêtre du jeu : bouge seulement si elle a bougé, masque quand le sim se ferme
    # (grace = 10 ticks à 0.1 s ≈ 1 s), ré-affiche + recale au restart.
    follower = geometry.WindowFollower(miss_grace=10)

    def _apply_action(action: geometry.FollowAction) -> None:
        ns = state["ns"]
        if ns is None:
            return
        if action.frame is not None:
            r = action.frame
            ns.setFrame_display_(NSMakeRect(r.x, r.y, r.w, r.h), True)
        if action.show is False:
            ns.orderOut_(None)
        elif action.show and state["visible"]:  # ne pas contredire un masquage manuel
            ns.orderFrontRegardless()

    def _sync_once(force: bool = False) -> None:
        if force:
            follower.force_reapply()
        bounds = geometry.find_game_bounds(owner)
        action = follower.tick(bounds, geometry.primary_screen_height())
        if not action.is_noop:
            AppHelper.callAfter(_apply_action, action)

    def _sync_loop() -> None:
        while not stop.is_set():
            try:
                _sync_once()
            except Exception:
                pass  # jamais faire planter la boucle (jeu fermé, perms, etc.)
            stop.wait(0.1)

    def _on_toggle_click_through() -> None:
        state["click_through"] = not state["click_through"]
        if state["ns"] is not None:
            macwin.set_click_through(state["ns"], state["click_through"])

    def _on_toggle_visible() -> None:
        ns = state["ns"]
        if ns is None:
            return
        state["visible"] = not state["visible"]
        if state["visible"]:
            ns.orderFrontRegardless()
        else:
            ns.orderOut_(None)

    def _on_quit() -> None:
        stop.set()
        if server is not None:
            server.should_exit = True
        try:
            window.destroy()
        except Exception:
            pass

    def _setup_native() -> None:
        # DOIT tourner sur le thread principal (NSWindow/NSStatusBar) -> via AppHelper.callAfter.
        ns = macwin.find_overlay_window(title)
        state["ns"] = ns
        if ns is not None:
            macwin.apply_overlay_style(ns, opacity=opacity)
        state["status"] = macwin.install_status_item({
            "toggle_click_through": _on_toggle_click_through,
            "toggle_visible": _on_toggle_visible,
            "recenter": lambda: _sync_once(force=True),
            "quit": _on_quit,
        })
        threading.Thread(target=_sync_loop, daemon=True).start()

    def _on_shown() -> None:
        # pywebview exécute l'event 'shown' sur un thread worker -> on repasse au main thread.
        AppHelper.callAfter(_setup_native)

    window.events.shown += _on_shown
    print(f"Overlay → {url}  (cible fenêtre : « {owner} »)")
    print("Astuce : lance OPTCGSim en fenêtré sans bordure. Menu dans la barre macOS (🎴).")
    webview.start()
    stop.set()
    return 0
