"""Serveur FastAPI pour OPTCGSim Haki (assistant de décision in-match).

Expose en JSON pur, focalisé sur la partie en cours :
  - GET /api/state            → payload live (jeu en cours)
  - GET /api/reveal           → bascule reveal-all (revue hors-ligne)
  - GET /api/card?id=&size=   → image de carte (binaire)

Sert aussi le build statique du frontend (overlay + vue live). Les surfaces de stats
long-terme / historique / post-game ont été retirées (recentrage décision, chantier H) :
seule l'aide à la décision en cours de match est exposée.
"""

from __future__ import annotations

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..cardimages import resolve_image, content_type
from ..engine import LiveEngine


def create_app(db_path: str = "optcg.db", reveal_all: bool = False) -> FastAPI:
    """Crée l'application FastAPI. Un seul LiveEngine partagé (thread-safe via lock)."""
    app = FastAPI(title="OPTCGSim Haki API", version="0.2.0")

    # CORS : le frontend Next.js tourne sur un port différent en dev (5173/3000).
    # allow_credentials=False : l'API ne lit jamais de cookies/auth (lecture publique locale),
    # et la combinaison avec allow_origins=["*"] est invalide côté spec (Starlette échoue
    # alors l'origine littérale au lieu de "*" — pas de risque réel ici, mais autant être exact).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # local only — pas de risque
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    live = LiveEngine(db_path, reveal_all=reveal_all)

    # --- Live state ---
    @app.get("/api/state")
    def get_state() -> dict:
        return live._state_payload()

    # --- Reveal-all : bascule à chaud (revue / hors-ligne). ⚠️ Expose la main + l'ordre du
    # deck adverses (reconstruits depuis RZ1) -> à NE PAS utiliser en partie classée en ligne.
    @app.get("/api/reveal")
    def toggle_reveal(on: bool | None = Query(None)) -> dict:
        live.reveal_all = (not live.reveal_all) if on is None else on
        return {"reveal_all": live.reveal_all}

    # --- Card images ---
    @app.get("/api/card")
    def get_card(id: str = Query(...), size: str = Query("small")):
        small = size != "full"
        path = resolve_image(live.sources.paths.card_images, id, small=small)
        if not path:
            raise HTTPException(404, "Card image not found")
        return FileResponse(path, media_type=content_type(path),
                            headers={"Cache-Control": "public, max-age=86400"})

    # --- Frontend statique (build Next.js output: export) ---
    # En prod : FastAPI sert le build statique sur le même port que l'API.
    # Résolution via optcgsim_haki.resources (supporte pip install ET mode dev).
    from optcgsim_haki.resources import static_dir
    frontend_out = static_dir()
    if frontend_out:
        # Les assets _next/ sont servis directement.
        app.mount("/_next", StaticFiles(directory=frontend_out / "_next"), name="next-assets")

        # Fallback : sert index.html pour le client-side routing (SPA).
        @app.get("/{path:path}")
        async def serve_frontend(path: str, request: Request):
            # D'abord, essaie le fichier statique exact.
            candidate = frontend_out / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            # Next.js 16 (output: export) génère <route>.html à la racine (e.g. overlay.html).
            # Indispensable pour les liens DIRECTS (l'overlay charge /overlay sans passer par /).
            page_html = frontend_out / f"{path}.html"
            if path and page_html.is_file():
                return FileResponse(page_html, media_type="text/html")
            # Ensuite, essaie path/index.html (variantes d'export).
            idx = frontend_out / path / "index.html"
            if idx.is_file():
                return FileResponse(idx, media_type="text/html")
            # Fallback SPA : index.html à la racine.
            root_idx = frontend_out / "index.html"
            if root_idx.is_file():
                return FileResponse(root_idx, media_type="text/html")
            raise HTTPException(404, "Frontend not built. Run: cd frontend && npm run build")

    # Stocke la live server pour accès externe (tests, CLI).
    app.state.live = live
    app.state.db_path = db_path
    return app


# --- Helpers : extraction des données stats en JSON ---

def run_api(db_path: str = "optcg.db", port: int = 8765, reveal_all: bool = False) -> int:
    """Lance le serveur FastAPI via uvicorn + le tail loop du LiveEngine.

    En prod (si frontend/out/ existe) : un seul port sert l'API ET le frontend.
    En dev : l'API sur ce port, le frontend sur localhost:3000 (next dev).
    """
    import uvicorn
    import threading

    app = create_app(db_path, reveal_all=reveal_all)
    live: LiveEngine = app.state.live

    # Démarre le tail loop (log watching) en arrière-plan.
    t = threading.Thread(target=live._tail_loop, daemon=True)
    t.start()

    from optcgsim_haki.resources import has_frontend
    print(f"OPTCGSim Haki API → http://127.0.0.1:{port}/api/state")
    if has_frontend():
        print(f"Dashboard             → http://127.0.0.1:{port}/")
    else:
        print(f"Frontend (dev)        → http://localhost:3000 (cd frontend && npm run dev)")
        print(f"  (pour prod: cd frontend && npm run build → servi sur :{port})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def serve_in_thread(db_path: str = "optcg.db", port: int = 8765, reveal_all: bool = False):
    """Démarre l'API (+ tail loop) dans des threads daemon et rend la main aussitôt.

    Pour l'overlay : pywebview doit occuper le thread principal, donc uvicorn tourne ailleurs.
    Les signal handlers sont désactivés (ils ne sont posables que sur le main thread).
    Renvoie (server, thread) — appeler ``server.should_exit = True`` pour arrêter.
    """
    import threading
    import uvicorn

    app = create_app(db_path, reveal_all=reveal_all)
    live: LiveEngine = app.state.live
    threading.Thread(target=live._tail_loop, daemon=True).start()

    class _Server(uvicorn.Server):
        def install_signal_handlers(self) -> None:  # pas sur le main thread
            pass

    server = _Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server, t
