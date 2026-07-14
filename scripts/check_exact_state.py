#!/usr/bin/env python3
"""Validateur du fichier d'état exact écrit par le mod BepInEx (Partie A).

À lancer PENDANT une partie, le mod chargé. Affiche un résumé lisible et signale les
incohérences (joueurs manquants, index `me` douteux, comptes incohérents). Permet de vérifier
que le mod produit bien l'état attendu — sans dépendre du tracker.

Usage :
    python3 scripts/check_exact_state.py            # une lecture
    python3 scripts/check_exact_state.py --watch    # rafraîchit en continu (Ctrl-C pour stopper)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

DEFAULT = (Path.home() / "Library" / "Application Support"
           / "com.Batsu.OPTCGSim" / "live_exact_state.json")


def _zone(cards):
    return [c.get("cardId") or c.get("card_id") or "?" for c in (cards or [])]


def check(path: Path) -> int:
    if not path.exists():
        print(f"❌ Fichier absent : {path}\n   -> le mod est-il chargé ? (voir BepInEx/LogOutput.log)")
        return 1
    try:
        d = json.loads(path.read_text(errors="ignore"))
    except Exception as e:
        print(f"⚠️  JSON illisible (écriture en cours ?) : {e}")
        return 1

    problems = []
    print(f"schema={d.get('schema')}  turn={d.get('turn')}  active={d.get('active_player')}  me={d.get('me')}")
    players = d.get("players") or {}
    if set(players) < {"0", "1"}:
        problems.append("joueurs manquants (attendu '0' et '1')")
    me_idx = str(d.get("me", 0))
    for idx in ("0", "1"):
        p = players.get(idx)
        if not p:
            continue
        tag = "MOI" if idx == me_idx else "ADV"
        hand, deck = _zone(p.get("hand")), _zone(p.get("deck"))
        board, life = _zone(p.get("board")), p.get("life") or []
        print(f"\n[{tag}] leader={p.get('leader')}  vie={len(life)}  "
              f"deck={len(deck)}  main={len(hand)}  board={len(board)}  "
              f"DON act/rest={p.get('activeDon')}/{p.get('restedDon')}")
        print(f"   main : {hand}")
        print(f"   board: {board}")
        # sanity
        if len(deck) + len(hand) + len(board) + len(life) > 60:
            problems.append(f"joueur {idx}: total cartes > 60 (zones dupliquées ?)")
        if any(c == "?" for c in hand + board):
            problems.append(f"joueur {idx}: cartes sans cardId")

    print()
    if problems:
        print("⚠️  À vérifier :")
        for x in problems:
            print("   -", x)
    else:
        print("✅ Cohérent. Vérifie surtout : la section [MOI] correspond-elle à TA main réelle ?")
        print("   Sinon l'index `me` est inversé (corrige GetLocalPlayerIndex dans le mod).")
    return 0


def main():
    path = DEFAULT
    watch = "--watch" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        path = Path(args[0])
    if not watch:
        return check(path)
    try:
        while True:
            print("\033[2J\033[H", end="")  # clear
            check(path)
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
