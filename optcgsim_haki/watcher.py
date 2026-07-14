"""Surveillance temps réel.

- AutoSaved/ : à la fin de chaque partie, un nouveau .log apparaît -> on le parse et on le
  persiste (watchdog). C'est ce qui évite la perte des parties (rétention ~9 j côté jeu).
- Player.log : flux live -> on le tail et on alimente LiveState pour l'affichage en direct.

Le rendu live respecte le mode fair-play par défaut (voir live.py).
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import card_effects
from .deck_match import load_named_decks, match_deck, my_cards_from_record
from .db.store import Store
from .formats import FormatDetector
from .live import LiveState
from .parser import loglines as L
from .parser.match import parse_log
from .sources import LogFile, Sources


def replay_current_match(state: LiveState, player_log: Path) -> int | None:
    """Rejoue la partie déjà présente dans Player.log (détection d'une partie EN COURS).

    Le tailer démarre en fin de fichier : sans ça, une partie commencée AVANT le lancement du
    dashboard ne serait jamais reconstruite (le contexte début — connexion, leaders, mulligan,
    mapping RZ1 — est déjà passé). On repère le DERNIER "Attempting to connect" et on réinjecte
    toutes les lignes depuis ce point. Renvoie la position d'octet à donner au tailer pour ne pas
    relire ces lignes (ou None si rien à faire).
    """
    if not player_log.exists():
        return None
    try:
        data = player_log.read_bytes()
    except OSError:
        return None
    lines = data.decode(errors="ignore").splitlines()
    # Repère du dernier match : "deck filled, do shuffle" (1×/partie en direct) ou "Attempting
    # to connect" (AutoSaved). On NE s'ancre PAS sur "RZ1|HDR" (ré-émis par [ReplaySync]).
    def _is_start(ln: str) -> bool:
        return bool(L.RE_DECK_FILLED.match(ln)) or bool(L.RE_CONNECT.match(ln))
    start = next((i for i in range(len(lines) - 1, -1, -1) if _is_start(lines[i])), None)
    if start is None:
        start = next((i for i in range(len(lines) - 1, -1, -1) if "RZ1|HDR" in lines[i]), None)
    # IMPORTANT : "deck filled" concerne MON deck et survient APRÈS le shuffle adverse quand
    # l'adversaire mélange en premier. On remonte donc à travers le cluster de setup (load deck,
    # shuffle, Got shuffle, flux RZ1) pour inclure le "shuffle deck for" adverse pré-marqueur,
    # sinon opp_tag reste non résolu. On s'arrête à la 1re ligne préfixée [pseudo] (= gameplay/
    # snapshot du match précédent). Le reset "gated-gameplay" de feed_line nettoie tout résidu.
    if start is not None:
        j, bound = start - 1, max(0, start - 200)
        while j >= bound:
            pm = L.PLAYER_LINE.match(lines[j])
            if pm and L.is_player_tag(L.clean(pm.group("who"))):
                break
            if L.RE_SHUFFLE_FOR.match(lines[j]):
                start = j
            j -= 1
        for ln in lines[start:]:
            state.feed_line(ln)
    return len(data)


class MatchTimer:
    """Mesure la durée d'une partie depuis le flux live.

    Les logs AutoSaved n'ont aucun timestamp par ligne : pour les parties directes (absentes de
    `my_matches`), c'est la seule source de durée. Le watcher horodate le début (partie active)
    et la fin (résultat connu). L'horloge est injectable pour les tests.
    """

    def __init__(self, clock=time.time):
        self._clock = clock
        self._start: float | None = None
        self._pending: float | None = None  # durée mesurée en attente de persistance

    def on_state(self, active: bool, has_result: bool) -> None:
        if active and self._start is None and not has_result:
            self._start = self._clock()
        if has_result and self._start is not None:
            self._pending = self._clock() - self._start
            self._start = None

    def take_duration(self) -> float | None:
        d, self._pending = self._pending, None
        return d


def _persist_log(store: Store, detector: FormatDetector, path: Path,
                 duration_override: float | None = None):
    """Parse + stocke un fichier de log fraîchement écrit. Renvoie le MatchRecord (ou None)."""
    try:
        lf = LogFile(path, datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
        rec = parse_log(lf.read_text(), match_id=lf.content_hash(),
                        played_at=lf.mtime, source="autosaved")
        if rec.cards_seen:
            v = detector.detect(rec.cards_seen)
            rec.format, rec.format_confidence = v.verdict, v.confidence
        rec.mode = rec.mode or "direct"
        # Durée mesurée en live (les AutoSaved n'en contiennent pas).
        if rec.duration_s is None and duration_override is not None:
            rec.duration_s = round(duration_override, 1)
        # Rattachement au deck nommé du joueur (rechargé à chaque partie : les decklists
        # peuvent évoluer entre deux parties).
        cards, full = my_cards_from_record(rec)
        rec.my_deck = match_deck(cards, rec.me.leader, load_named_decks(), full=full)
        store.upsert_match(rec)
        return rec
    except Exception as e:  # robustesse : un log corrompu ne doit pas tuer le watcher
        print(f"  [watch] échec parsing {path.name}: {e}", file=sys.stderr)
        return None


class _Tailer:
    """Tail robuste d'un fichier appendé (gère la rotation/troncature)."""

    def __init__(self, path: Path):
        self.path = path
        self.pos = path.stat().st_size if path.exists() else 0

    def read_new(self) -> list[str]:
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.pos:  # rotation -> on repart du début
            self.pos = 0
        out: list[str] = []
        with self.path.open("r", errors="ignore") as f:
            f.seek(self.pos)
            data = f.read()
            self.pos = f.tell()
        if data:
            out = data.splitlines()
        return out


def run_watch(db_path: str = "optcg.db", reveal_all: bool = False, poll: float = 0.5) -> int:
    sources = Sources()
    detector = FormatDetector(sources)
    store = Store(db_path)

    autosaved_dir = sources.paths.autosaved_logs
    seen = {p.name for p in autosaved_dir.glob("*.log")} if autosaved_dir.exists() else set()

    player_log = sources.player_log
    if not player_log.exists():
        print(f"Player.log introuvable ({player_log}). Le jeu est-il lancé ?", file=sys.stderr)
    tailer = _Tailer(player_log)
    state = LiveState()
    timer = MatchTimer()
    card_effects.warm()  # précharge la classification d'effets hors partie
    # Rattrape une partie déjà en cours (le tailer démarre sinon en fin de fichier).
    pos = replay_current_match(state, player_log)
    if pos is not None:
        tailer.pos = pos

    if reveal_all:
        print("⚠️  --reveal-all : l'information cachée de l'adversaire sera affichée.")
        print("    N'utilise PAS ceci pendant une partie classée en ligne (= triche).\n")
    print(f"Surveillance active. AutoSaved: {autosaved_dir}\n(Ctrl-C pour arrêter)\n")

    last_render = ""
    try:
        while True:
            # 1) Nouveaux logs terminés -> persistance (avec durée mesurée en live).
            if autosaved_dir.exists():
                for p in autosaved_dir.glob("*.log"):
                    if p.name not in seen:
                        seen.add(p.name)
                        rec = _persist_log(store, detector, p,
                                           duration_override=timer.take_duration())
                        if rec:
                            print(f"\n[watch] partie enregistrée : {p.name} (id {rec.match_id})")

            # 2) Flux live.
            changed = False
            for line in tailer.read_new():
                state.feed_line(line)
                changed = True
            timer.on_state(active=state.active, has_result=state.result is not None)
            if changed and state.players:
                render = state.render(reveal_all=reveal_all)
                if render != last_render:
                    # Efface l'écran et réaffiche le tableau de bord.
                    os.system("cls" if os.name == "nt" else "clear")
                    print(render)
                    last_render = render

            time.sleep(poll)
    except KeyboardInterrupt:
        print("\nArrêt de la surveillance.")
    finally:
        store.close()
    return 0
