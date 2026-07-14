"""Décodeur du flux structuré RZ1 (secondaire — sert de cross-check au parsing texte).

Format observé :
    En-tête : RZ1|HDR|<version>|<n>|RZ1
    Événement : RZ1|seq|player|card|c4|c5|c6|c7|c8|c9|c10|c11|c12

Décodage partiel établi par observation (à affiner ; le texte reste la vérité) :
    seq    = numéro d'événement croissant
    player = 1 ou 2
    card   = cardID ou littéral "Don"
    sur une pioche : c5 décroît = cartes restantes dans le deck ; c7 = position en main
    valeurs négatives (ex. c11 = -1000) = modificateurs de puissance / counter

Ce module ne fait que tokenizer proprement ; l'interprétation fine est laissée optionnelle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RZ1Event:
    seq: int
    player: int
    card: str
    cols: list[int | str]  # colonnes restantes brutes
    raw: str


def parse_rz1_line(line: str) -> RZ1Event | None:
    line = line.strip()
    if line.startswith("[ReplaySync]"):
        line = line[len("[ReplaySync]"):].strip()
    if not line.startswith("RZ1|"):
        return None
    parts = line.split("|")
    # parts[0] == 'RZ1'
    if len(parts) < 4 or parts[1] == "HDR":
        return None
    try:
        seq = int(parts[1])
        player = int(parts[2])
    except ValueError:
        return None
    card = parts[3]
    cols: list[int | str] = []
    for p in parts[4:]:
        try:
            cols.append(int(p))
        except ValueError:
            cols.append(p)
    return RZ1Event(seq=seq, player=player, card=card, cols=cols, raw=line)


# --- Interprétation (uniquement les signaux VÉRIFIÉS contre les snapshots texte) ---
#
# Disposition des colonnes (cols = parts après le cardID) :
#   cols[0] = code d'action/zone (0 = pioche deck->main ; 1 = placement dans une zone ; 4/5/9 = Don)
#   cols[1] = sur une pioche (cols[0]==0) : nombre de cartes RESTANTES dans le deck   ← fiable
#   cols[1] = sur un placement Don (cols[0]==4) : DON restants dans le DON-deck       ← fiable
#   cols[3] = position en main (sur pioche)
#   cols[7] = modificateur de puissance (valeur négative = counter/-power)            ← fiable
# Les zones de board/trash sont partiellement décodées et NON exposées (les snapshots texte
# donnent déjà board/trash/life de façon fiable).

DRAW_ACTION = 0
DON_PLACE_ACTION = 4   # placement d'un DON depuis le DON-deck vers le terrain
DON_DECK_TOTAL = 10    # taille du DON-deck standard


def is_draw(ev: RZ1Event) -> bool:
    return ev.card != "Don" and bool(ev.cols) and ev.cols[0] == DRAW_ACTION


def deck_remaining(ev: RZ1Event) -> int | None:
    """Cartes restantes dans le deck juste après cette pioche, ou None si non applicable."""
    if is_draw(ev) and len(ev.cols) > 1 and isinstance(ev.cols[1], int):
        return ev.cols[1]
    return None


def don_deck_remaining(ev: RZ1Event) -> int | None:
    """DON restants dans le DON-deck après un placement (action 4), ou None.

    Format vérifié contre logs réels : ``RZ1|seq|player|Don|4|N|...`` où N = DON restants
    dans le DON-deck. DON sur le terrain = ``DON_DECK_TOTAL - N`` (10 - N).

    On ne lit QUE l'action 4 (placement depuis le DON-deck) : les actions 5 (attach à une
    carte) et 9 (modificateur de puissance, ex. 9900) sont bruitées et non pertinentes pour
    le compte du DON actif. Prendre la dernière valeur connue par joueur donne le DON sur
    terrain courant (vérifié : premier T1=1/T2=3/T3=5, second T1=2/T2=4/T3=6).
    """
    if ev.card != "Don" or not ev.cols or ev.cols[0] != DON_PLACE_ACTION:
        return None
    if len(ev.cols) > 1 and isinstance(ev.cols[1], int) and 0 <= ev.cols[1] <= DON_DECK_TOTAL:
        return ev.cols[1]
    return None


def power_modifier(ev: RZ1Event) -> int | None:
    """Renvoie le modificateur de puissance (négatif) si présent."""
    for c in ev.cols:
        if isinstance(c, int) and c < 0:
            return c
    return None
