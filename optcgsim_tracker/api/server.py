"""Serveur FastAPI pour OPTCGSim Tracker.

Expose en JSON pur :
  - GET /api/state            → payload live (jeu en cours)
  - GET /api/card?id=&size=   → image de carte (binaire)
  - GET /api/stats            → metas avec winrates
  - GET /api/stats?meta=X     → leaders + decks du meta
  - GET /api/stats?meta=X&leader=Y → détail leader (tous les KPIs)
  - GET /api/stats?meta=X&leader=Y&opp=Z → matchup
  - GET /api/stats?meta=X&deck=Y → détail deck
  - GET /api/stats?meta=X&deck=Y&opp=Z → matchup deck
  - GET /api/decks            → liste des decks .txt
  - GET /api/decks/{name}     → détail d'un deck (composition + stats)
  - GET /api/decks/{name}/mtime → mtime pour auto-reload

Le frontend Next.js (frontend/) consomme ces endpoints.
"""

from __future__ import annotations

import pathlib
import urllib.parse
from typing import Any

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ..analytics import Analytics
from ..cardimages import resolve_image, content_type
from ..db.store import Store
from ..deckstats import compute_stats, opening_odds, parse_deck_file
from ..engine import LiveEngine
from ..features import feature, all_features
from ..stats import Row


def _row_to_dict(r: Row) -> dict:
    return {"label": r.label, "wins": r.wins, "losses": r.losses,
            "total": r.total, "winrate": round(r.winrate, 1)}


def _rows_to_list(rows: list[Row]) -> list[dict]:
    return [_row_to_dict(r) for r in rows]


def _leader_life(leader_id: str | None, meta: dict) -> int:
    """Nombre de vies du leader : meta[leader].life si connu et > 0, sinon 5."""
    if leader_id and leader_id in meta:
        life = getattr(meta[leader_id], "life", None)
        if isinstance(life, int) and life > 0:
            return life
    return 5


def _detect_highlights(snapshots: list[dict], events: list[dict], match: dict) -> list[dict]:
    """Détecte automatiquement les moments clés d'une partie pour la timeline interactive.

    Types de highlights :
    - life_drop : perte de vie significative (≥2 life en un tour)
    - critical_life : vie ≤ 2 (zone de danger)
    - big_deploy : déploiement d'une carte à coût élevé (≥7)
    - counter_play : contre-attaque avec counter
    - leader_attack : attaque directe sur le leader
    - hand_surge : pic de cartes en main (≥8)
    - turn_point : tour charnière (changement de momentum)
    """
    highlights: list[dict] = []

    # Index snapshots par (turn, side) pour comparer.
    life_by_turn: dict[str, dict[int, int]] = {"me": {}, "opp": {}}
    hand_by_turn: dict[str, dict[int, int]] = {"me": {}, "opp": {}}
    for s in snapshots:
        side = s["side"]
        turn = s["turn"]
        if s["life"] is not None:
            # Garde la dernière valeur du tour (snapshot le plus récent).
            life_by_turn[side][turn] = s["life"]
        if s["hand_count"] is not None:
            hand_by_turn[side][turn] = s["hand_count"]

    # life_drop : compare la vie entre tours consécutifs.
    for side in ("me", "opp"):
        turns = sorted(life_by_turn[side].keys())
        for i in range(1, len(turns)):
            prev_life = life_by_turn[side][turns[i - 1]]
            curr_life = life_by_turn[side][turns[i]]
            drop = prev_life - curr_life
            if drop >= 2:
                highlights.append({
                    "turn": turns[i],
                    "side": side,
                    "type": "life_drop",
                    "icon": "💥" if side == "me" else "🗡️",
                    "label": f"{'Tu' if side == 'me' else 'Adversaire'} perd {drop} life"
                             f" ({prev_life}→{curr_life})",
                })
        # critical_life : vie ≤ 2.
        for t in turns:
            life = life_by_turn[side][t]
            if life is not None and life <= 2:
                highlights.append({
                    "turn": t,
                    "side": side,
                    "type": "critical_life",
                    "icon": "❤️" if side == "me" else "🔥",
                    "label": f"{'Tu es' if side == 'me' else 'Adversaire est'} à {life} life"
                             + (" — zone critique" if life <= 1 else ""),
                })

    # hand_surge : pic de cartes en main (≥8).
    for side in ("me", "opp"):
        turns = sorted(hand_by_turn[side].keys())
        for t in turns:
            hc = hand_by_turn[side][t]
            if hc is not None and hc >= 8:
                highlights.append({
                    "turn": t,
                    "side": side,
                    "type": "hand_surge",
                    "icon": "🃏",
                    "label": f"{'Tu as' if side == 'me' else 'Adversaire a'} {hc} cartes en main",
                })

    # big_deploy : déploiement d'une carte coûteuse (≥7).
    # On a besoin du coût — il n'est pas dans les events, on l'infère via card_id.
    # Pour simplifier, on compte le nombre de deploys par tour par côté.
    deploys_by_turn: dict[tuple[int, str], int] = {}
    for e in events:
        if e["type"] == "deploy":
            key = (e["turn"], e["side"])
            deploys_by_turn[key] = deploys_by_turn.get(key, 0) + 1

    # leader_attack : attaque directe sur le leader adverse.
    for e in events:
        if e["type"] == "attack" and e["target_id"]:
            # target_id = leader_id → attaque sur le leader.
            if e["target_id"] == match.get("opp_leader") or e["target_id"] == match.get("my_leader"):
                is_my_attack = e["side"] == "me"
                target_is_opp = e["target_id"] == match.get("opp_leader")
                if is_my_attack and target_is_opp:
                    highlights.append({
                        "turn": e["turn"],
                        "side": "me",
                        "type": "leader_attack",
                        "icon": "⚔️",
                        "label": f"Attaque sur le leader adverse"
                                 + (f" avec {e['card_name']}" if e.get("card_name") else ""),
                    })

    # counter_play : utilisation de counter.
    counter_turns: set[tuple[int, str]] = set()
    for e in events:
        if e["type"] in ("counter", "counter_event"):
            key = (e["turn"], e["side"])
            if key not in counter_turns:
                counter_turns.add(key)
                highlights.append({
                    "turn": e["turn"],
                    "side": e["side"],
                    "type": "counter_play",
                    "icon": "🛡️",
                    "label": f"{'Tu contreras' if e['side'] == 'me' else 'Adversaire contrera'}"
                             + (f" avec {e['card_name']}" if e.get("card_name") else ""),
                })

    # Déduplication : garde le highlight le plus important par (turn, side, type).
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for h in sorted(highlights, key=lambda x: (x["turn"], x["side"], x["type"])):
        key = (h["turn"], h["side"], h["type"])
        if key not in seen:
            seen.add(key)
            deduped.append(h)

    return deduped


def create_app(db_path: str = "optcg.db", reveal_all: bool = False) -> FastAPI:
    """Crée l'application FastAPI. Un seul LiveEngine partagé (thread-safe via lock)."""
    app = FastAPI(title="OPTCGSim Tracker API", version="0.2.0")

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

    # --- Stats (multi-level navigation) ---
    @app.get("/api/stats/filters")
    def get_stats_filters() -> dict:
        """Liste des modes et formats disponibles pour les filtres de stats."""
        with Store(db_path) as st:
            modes = [r["mode"] for r in st.query(
                "SELECT DISTINCT mode FROM matches WHERE mode IS NOT NULL ORDER BY mode")]
            formats = [r["format"] for r in st.query(
                """SELECT DISTINCT format FROM matches
                   WHERE format IS NOT NULL AND format != 'Indéterminé'
                   ORDER BY format""")]
        # Normalise les formats : on extrait le préfixe (Standard, Extra Regulation, …)
        fmt_options = sorted({f.split(" (")[0].split(" —")[0] for f in formats})
        return {"modes": modes, "formats": fmt_options}

    @app.get("/api/value-stats")
    def get_value_stats(
        leader: str | None = Query(None),
        meta: str | None = Query(None),
        opp: str | None = Query(None),
        deck: str | None = Query(None),
        mode: str | None = Query(None),
        format: str | None = Query(None),
        min_games: int = Query(3, ge=1, le=50),
    ) -> list[dict]:
        """Value Score par carte : impact réel mesuré par State Diffing.

        Retourne [{card_id, name, n, avg_value, avg_value_win, avg_value_loss, avg_cost}]
        trié par avg_value décroissant.
        """
        with Store(db_path) as st:
            a = Analytics(st)
            return a.value_score_per_card(
                leader=leader, meta=meta, opp=opp, mode=mode,
                min_games=min_games, deck=deck, fmt=format)

    @app.get("/api/stats")
    def get_stats(
        meta: str | None = Query(None),
        leader: str | None = Query(None),
        opp: str | None = Query(None),
        deck: str | None = Query(None),
        mode: str | None = Query(None),
        format: str | None = Query(None),
    ) -> dict:
        with Store(db_path) as st:
            a = Analytics(st)
            tl = live.meta_timeline

            # Niveau 0 : liste des metas
            if not meta:
                return {"level": "metas",
                        "metas": _rows_to_list(a.by_meta(tl, mode, format)),
                        "features": all_features()}

            # Niveau DECK
            if deck:
                lid = a.deck_leader(deck, meta)
                if not opp:
                    return _stats_detail_data(a, st, live, meta, lid, deck, deck, mode, format)
                return _stats_matchup_data(a, st, live, meta, lid, deck, opp, deck, mode, format)

            # Niveau META : leaders + decks
            if not leader:
                return {
                    "level": "meta",
                    "meta": meta,
                    "leaders": _rows_to_list(a.leaders_in_meta(tl, meta, mode, having_min=1, fmt=format)),
                    "decks": _rows_to_list(a.decks_in_meta(meta, mode, having_min=1, fmt=format)),
                    "features": all_features(),
                }

            # Niveau LEADER
            lid = _leader_id_by_name(st, leader)
            if not opp:
                return _stats_detail_data(a, st, live, meta, lid, leader, None, mode, format)
            return _stats_matchup_data(a, st, live, meta, lid, leader, opp, None, mode, format)

    # --- Decks (list + detail) ---
    @app.get("/api/decks")
    def get_decks() -> dict:
        decks = live._deck_paths()
        out = []
        for p in decks:
            try:
                d = parse_deck_file(p)
                s = compute_stats(d, live.card_meta)
                out.append({
                    "name": p.stem,
                    "leader": d.leader,
                    "leader_name": live.card_meta.get(d.leader, type(next(iter(live.card_meta.values()), None))()).name if d.leader in live.card_meta else d.leader,
                    "total": s.total,
                    "counter_1000": s.counter_1000,
                    "counter_2000": s.counter_2000,
                })
            except Exception:
                out.append({"name": p.stem, "error": True})
        return {"decks": out}

    @app.get("/api/decks/{name}")
    def get_deck_detail(name: str) -> dict:
        p = live._resolve_deck(name)
        if not p:
            raise HTTPException(404, "Deck not found")
        d = parse_deck_file(p)
        s = compute_stats(d, live.card_meta)

        def _disp(cid: str | None) -> str | None:
            """Nom d'affichage CANONIQUE (deck builder), pas l'intitulé promo du pck.

            Le pck contient plusieurs impressions par numéro (alt-art / promo) -> card_meta.name
            peut être un sous-titre de variante ('Uta (Welcome Pack Vol. 2)'). On préfère le nom
            canonique de resources.assets (DB cards.name, via archetype), repli sur le pck.
            """
            if not cid:
                return cid
            n = live.archetype._name(cid)
            if n and n != cid:
                return n
            m = live.card_meta.get(cid)
            return m.name if (m and m.name) else cid

        odds = opening_odds(d, live.card_meta,
                            leader_life=_leader_life(d.leader, live.card_meta))
        for c in odds["per_card"]:
            c["name"] = _disp(c["card_id"])

        return {
            "name": p.stem,
            "leader": d.leader,
            "leader_name": _disp(d.leader),
            "stats": {
                "total": s.total,
                "curve": s.curve,
                "counters": s.counters,
                "counter_total": s.counter_total,
                "counter_1000": s.counter_1000,
                "counter_2000": s.counter_2000,
                "colors": s.colors,
                "types": s.types,
                "subtypes": s.subtypes,
                "power": s.power,
                "rarities": s.rarities,
                "attributes": s.attributes,
                "effect_keys": s.effect_keys,
                "effects_total": s.effects_total,
                "triggers_total": s.triggers_total,
                "unknown": s.unknown,
            },
            "cards": [
                {"card_id": cid, "qty": qty, "name": _disp(cid)}
                for cid, qty in d.cards.items()
            ],
            "odds": odds,
        }

    @app.get("/api/decks/{name}/mtime")
    def get_deck_mtime(name: str) -> dict:
        return live._deck_mtime(name)

    @app.get("/api/decks/{name}/meta-check")
    def get_deck_meta_check(name: str) -> dict:
        """Meta-Check : compare le deck du joueur à l'archétype moyen du même leader.

        Croise trois sources :
          - decklist du joueur (fichier .txt) ;
          - archétype moyen inféré (ArchetypeModel.predict) depuis les decks adverses
            historiques de ce leader → identifie les "staples" (haute présence) ;
          - played_impact (Analytics) → identifie les cartes sous-performantes.

        Retourne les staples manquantes, les staples présentes (validation), les cartes
        "tech" (rares dans la meta), et les cartes sous-performantes / top-performers.
        """
        p = live._resolve_deck(name)
        if not p:
            raise HTTPException(404, "Deck not found")
        d = parse_deck_file(p)
        leader = d.leader
        deck_cards = set(d.cards.keys())

        # Archétype moyen du leader (depuis les decks adverses historiques).
        pred = live.archetype.predict(leader) if leader else None
        expected = pred.expected_cards if pred else []
        n_historical = pred.n_historical if pred else 0

        # Joué_impact : performances réelles des cartes déployées avec ce leader.
        with Store(db_path) as st:
            a = Analytics(st)
            _, _, played = a.played_impact(leader=leader, min_games=3)
        played_by_id = {c["card_id"]: c for c in played}

        STAPLE_PRESENCE = 50.0
        TECH_PRESENCE = 25.0
        UNDERPERFORM_LIFT = -5.0
        TOP_LIFT = 5.0

        def _enrich(card_id: str, presence: float | None = None,
                    avg_copies: float | None = None) -> dict:
            """Carte avec nom + méta played_impact si dispo."""
            cm = live.card_meta.get(card_id)
            name = cm.name if cm else card_id
            cost = cm.cost if cm else None
            card_type = cm.card_type if cm else None
            entry = {
                "card_id": card_id, "name": name, "cost": cost, "card_type": card_type,
            }
            if presence is not None:
                entry["presence"] = round(presence, 1)
            if avg_copies is not None:
                entry["avg_copies"] = round(avg_copies, 2)
            pi = played_by_id.get(card_id)
            if pi:
                entry["lift"] = round(pi["lift"], 1)
                entry["n"] = pi["n"]
                entry["winrate"] = round(pi["winrate"], 1)
            return entry

        # Staples (présence ≥ 50%) : manquantes vs présentes.
        staples_missing = []
        staples_present = []
        for c in expected:
            if c["presence"] < STAPLE_PRESENCE:
                continue
            entry = _enrich(c["card_id"], c["presence"], c["avg_copies"])
            if c["card_id"] in deck_cards:
                staples_present.append(entry)
            else:
                staples_missing.append(entry)

        # Cartes du deck rares dans la meta (présence < 25% ou absentes) = tech picks.
        presence_by_id = {c["card_id"]: c["presence"] for c in expected}
        extra_cards = []
        for cid in deck_cards:
            pres = presence_by_id.get(cid)
            if pres is None or pres < TECH_PRESENCE:
                extra_cards.append(_enrich(cid, pres))

        # Sous-performantes / top-performers : cartes du deck avec played_impact significatif.
        underperforming = []
        top_performers = []
        for cid in deck_cards:
            pi = played_by_id.get(cid)
            if not pi or pi["n"] < 3:
                continue
            entry = _enrich(cid)
            if pi["lift"] <= UNDERPERFORM_LIFT:
                underperforming.append(entry)
            elif pi["lift"] >= TOP_LIFT:
                top_performers.append(entry)

        # Tri par pertinence.
        staples_missing.sort(key=lambda e: e.get("presence", 0), reverse=True)
        staples_present.sort(key=lambda e: e.get("presence", 0), reverse=True)
        extra_cards.sort(key=lambda e: e.get("presence", 999), reverse=True)
        underperforming.sort(key=lambda e: e.get("lift", 0))
        top_performers.sort(key=lambda e: e.get("lift", 0), reverse=True)

        return {
            "deck_name": p.stem,
            "leader": leader,
            "leader_name": (live.card_meta.get(leader).name
                            if leader and leader in live.card_meta else leader),
            "n_historical": n_historical,
            "staples_missing": staples_missing,
            "staples_present": staples_present,
            "extra_cards": extra_cards,
            "underperforming": underperforming,
            "top_performers": top_performers,
        }

    # --- Matches (timeline post-match) ---

    @app.get("/api/matches")
    def list_matches(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
        """Liste des parties récentes avec infos essentielles (pour la page /matches)."""
        with Store(db_path) as st:
            rows = st.query(
                """SELECT m.id, m.played_at, m.result, m.win_reason, m.mode, m.meta,
                          m.my_leader, m.opp_leader, m.duration_s, m.my_deck,
                          m.i_went_first
                   FROM matches m
                   WHERE m.result IN ('win','loss')
                   ORDER BY m.played_at DESC LIMIT ?""", (limit,))
            out = []
            for r in rows:
                out.append({
                    "id": r["id"],
                    "played_at": r["played_at"],
                    "result": r["result"],
                    "win_reason": r["win_reason"],
                    "mode": r["mode"],
                    "meta": r["meta"],
                    "my_leader": r["my_leader"],
                    "my_leader_name": st.card_name(r["my_leader"]) if r["my_leader"] else None,
                    "opp_leader": r["opp_leader"],
                    "opp_leader_name": st.card_name(r["opp_leader"]) if r["opp_leader"] else None,
                    "duration_s": r["duration_s"],
                    "my_deck": r["my_deck"],
                    "went_first": r["i_went_first"],
                })
            return out

    @app.get("/api/matches/{match_id}/timeline")
    def get_match_timeline(match_id: str) -> dict:
        """Timeline post-match : évolution de la vie + events clés par tour.

        Retourne :
          - match : infos générales (leaders, résultat, durée)
          - snapshots : [{turn, side, life, hand_count, deck_remaining}, ...]
          - events : [{turn, side, type, card_id, card_name, target_id, target_name}, ...]
            (uniquement deploy, attack, counter, counter_event — filtrés pour lisibilité)
          - highlights : moments clés détectés automatiquement
        """
        with Store(db_path) as st:
            mrows = st.query("SELECT * FROM matches WHERE id=?", (match_id,))
            if not mrows:
                raise HTTPException(404, "Match not found")
            m = mrows[0]
            match = {
                "id": m["id"],
                "played_at": m["played_at"],
                "result": m["result"],
                "win_reason": m["win_reason"],
                "my_leader": m["my_leader"],
                "my_leader_name": st.card_name(m["my_leader"]) if m["my_leader"] else None,
                "opp_leader": m["opp_leader"],
                "opp_leader_name": st.card_name(m["opp_leader"]) if m["opp_leader"] else None,
                "duration_s": m["duration_s"],
                "went_first": m["i_went_first"],
            }

            snaps = st.query(
                """SELECT turn, side, life, hand_count, deck_remaining
                   FROM turn_snapshots WHERE match_id=?
                   ORDER BY idx""", (match_id,))
            snapshots = [
                {"turn": s["turn"], "side": s["side"],
                 "life": s["life"], "hand_count": s["hand_count"],
                 "deck_remaining": s["deck_remaining"]}
                for s in snaps
            ]

            evs = st.query(
                """SELECT turn, side, type, card_id, target_id
                   FROM events WHERE match_id=?
                     AND type IN ('deploy','attack','counter','counter_event')
                   ORDER BY seq""", (match_id,))
            events = []
            for e in evs:
                events.append({
                    "turn": e["turn"], "side": e["side"], "type": e["type"],
                    "card_id": e["card_id"],
                    "card_name": st.card_name(e["card_id"]) if e["card_id"] else None,
                    "target_id": e["target_id"],
                    "target_name": st.card_name(e["target_id"]) if e["target_id"] else None,
                })

            highlights = _detect_highlights(snapshots, events, match)

            # Value Score par tour (détection de misplays et tours pivots).
            a = Analytics(st)
            value_timeline = a.value_score_per_turn(match_id)

            return {
                "match": match,
                "snapshots": snapshots,
                "events": events,
                "highlights": highlights,
                "value_timeline": value_timeline,
            }

    # --- Frontend statique (build Next.js output: export) ---
    # En prod : FastAPI sert le build statique sur le même port que l'API.
    # Résolution via optcgsim_tracker.resources (supporte pip install ET mode dev).
    from optcgsim_tracker.resources import static_dir
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

def _leader_id_by_name(st: Store, name: str) -> str | None:
    rows = st.query(
        "SELECT my_leader AS id FROM matches WHERE my_leader IN "
        "(SELECT card_id FROM cards WHERE name=?) LIMIT 1", (name,))
    return rows[0]["id"] if rows else None


def _stats_detail_data(
    a: Analytics, st: Store, live: LiveEngine,
    meta: str, lid: str | None, label: str, deck: str | None,
    mode: str | None, fmt: str | None,
) -> dict:
    """Données complètes pour la page de détail d'un leader ou deck (JSON)."""
    mus = a.leader_matchups(meta, lid, mode=mode, having_min=1, deck=deck, fmt=fmt)[:15] if lid else []
    bwr, n, op = a.opening_impact(leader=lid, meta=meta, min_games=15, deck=deck, mode=mode, fmt=fmt)
    _, _, pl = a.played_impact(leader=lid, meta=meta, min_games=5, deck=deck, mode=mode, fmt=fmt)
    _, _, combos = a.winning_combos(leader=lid, meta=meta, min_games=4, top=8, deck=deck, mode=mode, fmt=fmt)
    traj = a.life_trajectory(leader=lid, meta=meta, min_games=5, deck=deck, mode=mode, fmt=fmt)
    dcurve = a.deploy_curve(leader=lid, meta=meta, min_games=5, deck=deck, mode=mode, fmt=fmt)
    dist = a.attack_distribution(leader=lid, meta=meta, min_games=5, deck=deck, mode=mode, fmt=fmt)
    cnt = a.counter_stats(leader=lid, meta=meta, min_games=5, deck=deck, mode=mode, fmt=fmt)
    dwaste = a.don_waste(leader=lid, meta=meta, min_games=5, deck=deck, mode=mode, fmt=fmt)
    # Value Score : calculé uniquement si le feature flag est ON (coût CPU + approximatif).
    if feature("value_score"):
        value_scores = a.value_score_per_card(leader=lid, meta=meta, min_games=3,
                                               deck=deck, mode=mode, fmt=fmt)
    else:
        value_scores = []
    return {
        "level": "detail",
        "meta": meta,
        "leader_id": lid,
        "label": label,
        "deck": deck,
        "matchups": mus,
        "splits": {
            "first_second": _rows_to_list(a.split_first_second(leader=lid, meta=meta, deck=deck, mode=mode, fmt=fmt)),
            "mulligan": _rows_to_list(a.split_mulligan(leader=lid, meta=meta, deck=deck, mode=mode, fmt=fmt)),
            "elo_gap": _rows_to_list(a.split_elo_gap(leader=lid, meta=meta, deck=deck, mode=mode, fmt=fmt)),
        },
        "opening_impact": {
            "baseline_wr": round(bwr, 1) if bwr is not None else None,
            "n": n,
            "cards": op,
        },
        "played_impact": pl,
        "winning_combos": combos,
        "life_trajectory": traj,
        "deploy_curve": dcurve,
        "attack_distribution": dist,
        "counter_stats": cnt,
        "don_waste": dwaste,
        "value_scores": value_scores,
        "features": all_features(),
    }


def _stats_matchup_data(
    a: Analytics, st: Store, live: LiveEngine,
    meta: str, lid: str | None, label: str, opp: str,
    deck: str | None, mode: str | None, fmt: str | None,
) -> dict:
    """Données pour la page matchup (leader vs adversaire spécifique, JSON)."""
    oppname = st.card_name(opp)
    wl = a.leader_matchups(meta, lid, mode=mode, having_min=1, deck=deck, fmt=fmt) if lid else []
    this = next((m for m in wl if m["opp_id"] == opp), None)
    _, _, pl = a.played_impact(leader=lid, meta=meta, opp=opp, min_games=5, deck=deck, mode=mode, fmt=fmt)
    reco = (a.mulligan_reco(lid, meta, opp=opp, deck=deck, mode=mode, fmt=fmt) if lid
            else {"keep": [], "avoid": [], "confidence": "faible",
                  "premier": {}, "second": {}, "scored": []})
    hss = (a.hand_score_stats(lid, meta, opp=opp, min_games=5,
                              scored=reco.get("scored"), deck=deck, mode=mode, fmt=fmt) if lid else None)
    traj = a.life_trajectory(leader=lid, meta=meta, opp=opp, min_games=3, deck=deck, mode=mode, fmt=fmt)
    dcurve = a.deploy_curve(leader=lid, meta=meta, opp=opp, min_games=3, deck=deck, mode=mode, fmt=fmt)
    dist = a.attack_distribution(leader=lid, meta=meta, opp=opp, min_games=3, deck=deck, mode=mode, fmt=fmt)
    cnt = a.counter_stats(leader=lid, meta=meta, opp=opp, min_games=3, deck=deck, mode=mode, fmt=fmt)
    dwaste = a.don_waste(leader=lid, meta=meta, opp=opp, min_games=3, deck=deck, mode=mode, fmt=fmt)
    return {
        "level": "matchup",
        "meta": meta,
        "leader_id": lid,
        "label": label,
        "opp_id": opp,
        "opp_name": oppname,
        "deck": deck,
        "head": (f"{this['wins']}-{this['losses']} · {this['winrate']:.0f}%"
                 if this else "—"),
        "matchup": this,
        "splits": {
            "first_second": _rows_to_list(
                a.split_first_second(leader=lid, meta=meta, opp=opp, deck=deck, mode=mode, fmt=fmt)),
            "elo_gap": _rows_to_list(
                a.split_elo_gap(leader=lid, meta=meta, opp=opp, deck=deck, mode=mode, fmt=fmt)),
        },
        "mulligan_reco": reco,
        "hand_score_stats": hss,
        "played_impact": pl,
        "life_trajectory": traj,
        "deploy_curve": dcurve,
        "attack_distribution": dist,
        "counter_stats": cnt,
        "don_waste": dwaste,
        "features": all_features(),
    }


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

    from optcgsim_tracker.resources import has_frontend
    print(f"OPTCGSim Tracker API → http://127.0.0.1:{port}/api/state")
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
