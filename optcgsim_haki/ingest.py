"""Orchestration : sources -> MatchRecords enrichis -> base SQLite.

Étapes :
  1. Parse les logs AutoSaved (+ manuels) en MatchRecord (events, snapshots, mains).
  2. Détecte le format de chaque match (cartes vues vs banlists).
  3. Croise avec `my_matches` (OPBounty) par leaders + proximité temporelle :
       - match trouvé  -> mode=ranked, enrichi (durée, Elo, deck adverse complet).
       - sinon         -> mode=direct.
  4. Les matchs classés SANS log (historique purgé) sont ajoutés en version "lite"
     (source=opbounty, pas d'events).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .carddb import CardDB
from .formats import FormatDetector
from .meta import build_meta_timeline, resolve_meta, set_release_dates
from .model import MatchRecord, PlayerInfo
from .parser.match import parse_log
from .deck_match import load_named_decks, match_deck, my_cards_from_record
from .parser.my_matches import RankedMatch, detect_local_player, parse_my_matches
from .sources import Sources

# Fenêtre de rapprochement log<->ranked (le log est horodaté à la FIN, le ranked au début).
_MATCH_WINDOW_S = 2 * 3600


def _epoch(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    # Les timestamps ranked (my_matches/OPBounty) sont NAÏFS mais en UTC ; les played_at des
    # logs AutoSaved sont AWARE (UTC). `.timestamp()` sur un naïf l'interprète en heure LOCALE
    # -> décalage du fuseau (ex. +2h en CEST) qui fait échouer le rapprochement log<->ranked
    # (écart réel de ~10 min vu comme ~2h10 > fenêtre). On force donc l'interprétation UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _ranked_key(rm: RankedMatch) -> str:
    base = f"{rm.timestamp}|{rm.me}|{rm.opp}|{rm.my_leader}|{rm.opp_leader}"
    return "rk_" + hashlib.sha256(base.encode()).hexdigest()[:13]


def _apply_format(rec: MatchRecord, detector: FormatDetector, cards: set[str]) -> None:
    if not cards:
        return
    v = detector.detect(cards)
    rec.format = v.verdict
    rec.format_confidence = v.confidence


def _ranked_to_record(rm: RankedMatch, detector: FormatDetector) -> MatchRecord:
    rec = MatchRecord(match_id=_ranked_key(rm), played_at=rm.timestamp, source="opbounty",
                      mode="ranked")
    rec.me = PlayerInfo("me", name=rm.me, leader=rm.my_leader, deck=dict(rm.my_deck),
                        deck_known=True, rating=rm.my_rating, rating_delta=rm.my_delta,
                        opening_hand=list(rm.opening_hand), mulligan=rm.mulligan)
    rec.opp = PlayerInfo("opp", name=rm.opp, leader=rm.opp_leader, deck=dict(rm.opp_deck),
                         deck_known=True, rating=rm.opp_rating)
    rec.result = rm.my_result if rm.my_result in ("win", "loss") else (rm.my_result or "unknown")
    rec.duration_s = rm.duration_s
    cards = set(rm.my_deck) | set(rm.opp_deck)
    rec.cards_seen = cards
    _apply_format(rec, detector, cards)
    return rec


def _enrich_with_ranked(rec: MatchRecord, rm: RankedMatch) -> None:
    rec.mode = "ranked"
    rec.duration_s = rm.duration_s
    rec.me.rating = rm.my_rating
    rec.me.rating_delta = rm.my_delta
    rec.opp.rating = rm.opp_rating
    if rm.my_deck:
        rec.me.deck = dict(rm.my_deck)
        rec.me.deck_known = True
    if rm.opp_deck:
        rec.opp.deck = dict(rm.opp_deck)
        rec.opp.deck_known = True


def ingest_all(sources: Sources | None = None) -> list[MatchRecord]:
    sources = sources or Sources()
    detector = FormatDetector(sources)
    _ = CardDB(sources)  # réservé (métadonnées), non requis ici

    # Matchs classés (point de vue local).
    ranked: list[RankedMatch] = []
    mm = sources.my_matches_raw()
    local = detect_local_player(mm) if mm else None
    if mm:
        ranked = [r for r in parse_my_matches(mm, local) if r.me == local]

    # Index des ranked par leaders pour rapprochement rapide.
    ranked_used: set[int] = set()

    def find_ranked(rec: MatchRecord) -> RankedMatch | None:
        log_epoch = _epoch(rec.played_at)
        best, best_dt = None, None
        for i, rm in enumerate(ranked):
            if i in ranked_used:
                continue
            if rm.my_leader != rec.me.leader or rm.opp_leader != rec.opp.leader:
                continue
            re_ = _epoch(rm.timestamp)
            if log_epoch is None or re_ is None:
                continue
            dt = abs(log_epoch - re_)
            if dt <= _MATCH_WINDOW_S and (best_dt is None or dt < best_dt):
                best, best_dt, best_i = rm, dt, i
        if best is not None:
            ranked_used.add(best_i)
        return best

    records: list[MatchRecord] = []

    # 1) Logs (AutoSaved + manuels).
    for lf in sources.autosaved_logs() + sources.manual_logs():
        text = lf.read_text()
        rec = parse_log(text, match_id=lf.content_hash(), played_at=lf.mtime, source="autosaved")
        _apply_format(rec, detector, rec.cards_seen)
        rm = find_ranked(rec)
        if rm:
            _enrich_with_ranked(rec, rm)
        else:
            rec.mode = "direct"
        records.append(rec)

    # 2) Ranked sans log -> version lite.
    for i, rm in enumerate(ranked):
        if i in ranked_used:
            continue
        records.append(_ranked_to_record(rm, detector))

    # 3) Résolution du meta (date + cartes -> gère les queues anticipées).
    timeline = build_meta_timeline(sources.paths)
    release = set_release_dates(sources.paths.opbounty / "OPBounty.pck")
    for rec in records:
        cards = set(rec.cards_seen) | set(rec.me.deck) | set(rec.opp.deck)
        for lead in (rec.me.leader, rec.opp.leader):
            if lead:
                cards.add(lead)
        date = rec.played_at.isoformat() if rec.played_at else None
        m = resolve_meta(date, cards, timeline, release)
        rec.meta = m.label if m else None

    # 4) Rattachement au deck nommé du joueur (mêmes règles que le watcher).
    named_decks = load_named_decks(sources)
    for rec in records:
        mc, full = my_cards_from_record(rec)
        rec.my_deck = match_deck(mc, rec.me.leader, named_decks, full=full)

    return records
