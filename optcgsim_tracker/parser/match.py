"""Machine à états : un CombatLog complet -> MatchRecord exhaustif.

Le texte est la source de vérité ; le flux RZ1 sert de complément optionnel.
"""

from __future__ import annotations

from datetime import datetime

from ..model import Event, MatchRecord, PlayerInfo, TurnSnapshot
from . import loglines as L
from . import rz1 as RZ


def _identify_me(lines: list[str]) -> str | None:
    """Renvoie le pseudo du joueur local.

    Heuristique principale : seul le joueur local a une ligne 'Hand before Mulligan'.
    Fallbacks : 'X Has Connected', sinon le 2e 'Leader is' (l'adversaire est loggé en 1er).
    """
    leaders_order: list[str] = []
    connected: str | None = None
    for raw in lines:
        m = L.PLAYER_LINE.match(raw)
        if m:
            who = L.clean(m.group("who"))
            rest = m.group("rest")
            if L.RE_HAND_BEFORE_MULL.match(rest):
                return who
            if L.RE_LEADER.match(rest):
                leaders_order.append(who)
        mc = L.RE_CONNECTED.match(raw)
        if mc:
            connected = L.clean(mc.group("who"))
    if connected:
        return connected
    if len(leaders_order) >= 2:
        return leaders_order[1]
    return None


def parse_log(
    text: str,
    *,
    match_id: str,
    played_at: datetime | None = None,
    source: str = "autosaved",
) -> MatchRecord:
    lines = text.splitlines()
    rec = MatchRecord(match_id=match_id, played_at=played_at, source=source)

    me_name = _identify_me(lines)

    def side_of(who: str) -> str:
        return "me" if (me_name and who == me_name) else "opp"

    turn = 1
    seq = 0
    # Buffer pour assembler un snapshot (Hand/Board/Trash/Life arrivent en lignes séparées).
    pending: dict[str, TurnSnapshot] = {}
    # Vie courante par side : snapshots (valeur absolue) + dégâts mid-combat (relatif).
    # Sert à inférer le résultat des logs tronqués (voir _infer_truncated_result).
    cur_life: dict[str, int] = {}

    # --- État RZ1 ---
    rz_deck: dict[str, int] = {}          # side -> cartes restantes (dernier connu)
    rz_player_to_side: dict[int, str] = {}  # n° joueur RZ1 -> "me"/"opp"
    last_text_draw: tuple[str, str] | None = None  # (side, card) de la dernière pioche texte

    def deck_for(side: str) -> int | None:
        return rz_deck.get(side)

    def flush_snapshot(side: str) -> None:
        snap = pending.pop(side, None)
        if snap is not None:
            rec.snapshots.append(snap)

    def note_card(card_id: str, name: str | None = None) -> None:
        rec.cards_seen.add(card_id)
        if name:
            n = L.clean(name)
            if n:
                rec.card_names.setdefault(card_id, n)

    for raw in lines:
        # --- Flux structuré RZ1 ---
        if L.RE_RZ1.match(raw):
            ev = RZ.parse_rz1_line(raw)
            if ev is not None:
                # Apprend le mapping n° joueur RZ1 -> side via corrélation des pioches.
                if RZ.is_draw(ev) and ev.player not in rz_player_to_side and last_text_draw \
                        and last_text_draw[1] == ev.card:
                    rz_player_to_side[ev.player] = last_text_draw[0]
                dr = RZ.deck_remaining(ev)
                if dr is not None and ev.player in rz_player_to_side:
                    rz_deck[rz_player_to_side[ev.player]] = dr
                pmod = RZ.power_modifier(ev)
                if pmod is not None:
                    side = rz_player_to_side.get(ev.player, "?")
                    seq += 1
                    rec.events.append(Event(seq, turn, side, "modifier",
                                            card_id=ev.card if ev.card != "Don" else None,
                                            value=pmod, raw=raw))
            continue

        # --- En-tête (lignes globales) ---
        mc = L.RE_CONNECT.match(raw)
        if mc:
            rec.room_code = mc.group("code")
            continue
        mv = L.RE_VERSION.match(raw)
        if mv:
            rec.engine_version = mv.group("ver")
            continue
        if L.RE_DISCONNECT.search(raw):
            rec.result = "win"
            rec.win_reason = "disconnect"
            continue

        # --- Résolution d'attaque (ligne globale) ---
        mvs = L.RE_VS.match(raw)
        if mvs:
            note_card(mvs.group("att"))
            note_card(mvs.group("def"))
            # rattaché au dernier event d'attaque s'il existe
            continue
        if L.RE_ATTACK_FAILS.match(raw):
            seq += 1
            # Attaque échouée : la défense a gagné le clash. Utile pour le Value Score
            # (counter adverse = CA pour l'attaquant). Side = dernier attaquant.
            last_atk = next((e for e in reversed(rec.events) if e.type == "attack"), None)
            atk_side = last_atk.side if last_atk else "me"
            rec.events.append(Event(seq, turn, atk_side, "attack_fail", raw=raw))
            continue
        # Dégât sur un leader : "<Nom> [<id>] hit for N damage" (ligne globale, sans préfixe).
        # On décrémente la vie courante du camp touché (cross-check de l'inférence de résultat).
        mhit = L.RE_HIT.search(raw)
        if mhit:
            chit = L.CARD_RE.search(raw)
            if chit:
                hid = chit.group(1)
                hside = ("me" if hid == rec.me.leader
                         else "opp" if hid == rec.opp.leader else None)
                if hside is not None and hside in cur_life:
                    cur_life[hside] -= int(mhit.group("dmg"))
                # Stocke l'event de dégât pour le Value Score (Life Advantage).
                seq += 1
                def_side = "opp" if hside == "me" else "me" if hside == "opp" else None
                if def_side:
                    rec.events.append(Event(
                        seq, turn, def_side, "life_damage",
                        target_id=hid, value=int(mhit.group("dmg")), raw=raw))
            continue

        # --- Lignes attribuées à un joueur ---
        m = L.PLAYER_LINE.match(raw)
        if not m:
            continue
        who = L.clean(m.group("who"))
        rest = m.group("rest")
        # On n'attribue qu'aux vrais tags joueur ([You], [ReplaySync], tags Unity ignorés).
        if not L.is_player_tag(who):
            continue
        side = side_of(who)
        player: PlayerInfo = rec.player(side)
        if player.name is None and who:
            player.name = who

        # Leader
        ml = L.RE_LEADER.match(rest)
        if ml:
            player.leader = ml.group("id")
            note_card(ml.group("id"), ml.group("name"))
            continue

        # Main de départ
        mh = L.RE_HAND_BEFORE_MULL.match(rest)
        if mh:
            ids = L.parse_id_list(mh.group("ids"))
            player.opening_hand = ids
            for cid in ids:
                note_card(cid)
            if player.mulligan is None:
                player.mulligan = False  # 'keep' par défaut, écrasé si 'Mulligan' suit
            continue

        # Mulligan
        if L.RE_MULLIGAN.match(rest):
            player.mulligan = True
            continue

        # Ordre du tour
        mo = L.RE_GO_ORDER.match(rest)
        if mo:
            went_first = mo.group("order") == "First"
            rec.i_went_first = went_first if side == "me" else (not went_first)
            continue

        # Snapshots
        msh = L.RE_HAND.match(rest)
        if msh:
            flush_snapshot(side)
            snap = TurnSnapshot(turn=turn, side=side)
            snap.hand_ids = L.parse_id_list(msh.group("ids"))
            for cid in snap.hand_ids:
                note_card(cid)
            pending[side] = snap
            continue
        mb = L.RE_BOARD.match(rest)
        if mb and side in pending:
            pending[side].board_ids = L.parse_id_list(mb.group("ids"))
            for cid in pending[side].board_ids:
                note_card(cid)
            continue
        mt = L.RE_TRASH.match(rest)
        if mt and side in pending:
            pending[side].trash_ids = L.parse_id_list(mt.group("ids"))
            continue
        mlf = L.RE_LIFE.match(rest)
        if mlf and side in pending:
            pending[side].life = int(mlf.group("life"))
            cur_life[side] = int(mlf.group("life"))  # valeur absolue (écrase les dégâts comptés)
            pending[side].deck_remaining = deck_for(side)  # enrichi par RZ1
            flush_snapshot(side)  # Life clôt le bloc
            continue

        # Pioche révélée
        md = L.RE_DREW_REVEAL.match(rest)
        if md:
            seq += 1
            note_card(md.group("id"), md.group("name"))
            last_text_draw = (side, md.group("id"))  # pour corréler avec le RZ1 suivant
            rec.events.append(Event(seq, turn, side, "draw", card_id=md.group("id"), raw=rest))
            continue

        # Pioche / Don génériques
        mg = L.RE_DRAW_GENERIC.match(rest)
        if mg:
            seq += 1
            etype = "don" if mg.group("what") == "Don" else "draw"
            rec.events.append(Event(seq, turn, side, etype, value=int(mg.group("n")), raw=rest))
            continue

        # Déploiement
        mdep = L.RE_DEPLOY.match(rest)
        if mdep:
            seq += 1
            note_card(mdep.group("id"), mdep.group("name"))
            rec.events.append(Event(seq, turn, side, "deploy", card_id=mdep.group("id"), raw=rest))
            continue

        # Don attaché (à un Leader/Character). Type distinct de "don" (placement depuis le
        # DON-deck) pour permettre le calcul du DON Waste : attach = DON engagé durablement.
        mad = L.RE_ATTACH_DON.match(rest)
        if mad:
            seq += 1
            rec.events.append(Event(seq, turn, side, "don_attach",
                                    value=int(mad.group("n")), raw=rest))
            continue

        # Attaque
        ma = L.RE_ATTACK.match(rest)
        if ma:
            seq += 1
            note_card(ma.group("att"))
            note_card(ma.group("def"))
            rec.events.append(
                Event(seq, turn, side, "attack", card_id=ma.group("att"),
                      target_id=ma.group("def"), raw=rest)
            )
            continue

        # Counter
        mcnt = L.RE_COUNTER.match(rest)
        if mcnt:
            seq += 1
            note_card(mcnt.group("id"))
            rec.events.append(
                Event(seq, turn, side, "counter", card_id=mcnt.group("id"),
                      value=int(mcnt.group("val")), raw=rest)
            )
            continue

        # Event [Counter] joué en défense ("<Nom> [id]: Activate Counter").
        # Type distinct de "counter" pour ne pas polluer counter_stats (valeur de coin) ;
        # sert à marquer la carte comme "utilisée" (sinon faux "mort en main" au dernier tour).
        mac = L.RE_ACTIVATE_COUNTER.match(rest)
        if mac:
            seq += 1
            note_card(mac.group("id"), mac.group("name"))
            rec.events.append(
                Event(seq, turn, side, "counter_event", card_id=mac.group("id"), raw=rest)
            )
            continue

        # --- Retraits du board (KO, effets de Trash/Bounce/Deck, trash nu) ---
        # Ces events sont essentiels pour le Value Score (Tempo Advantage).
        # Un counter défaussé depuis la main n'est PAS un retrait de board.
        if not L.RE_DISCARD_COUNTER.match(rest):
            # KO en combat ou par effet : "Card [id] Destroyed".
            # Attribué au propriétaire (préfixe) : side = camp qui perd la carte.
            mdest = L.RE_DESTROYED.match(rest)
            if mdest:
                seq += 1
                note_card(mdest.group("id"))
                rec.events.append(Event(
                    seq, turn, side, "ko", card_id=mdest.group("id"), raw=rest))
                continue
            # Effet de retrait avec source : "Source [sid]: Trash/Return/Send Cible [tid]".
            # Side = camp qui SUBIT le retrait (propriétaire de la cible, = préfixe).
            # card_id = source, target_id = cible, value = verb encodé (1=trash, 2=bounce, 3=deck).
            mrem = L.RE_EFFECT_REMOVE.match(rest)
            if mrem:
                seq += 1
                note_card(mrem.group("src"))
                note_card(mrem.group("id"))
                verb_code = 3 if "Deck" in rest else 2 if "to Hand" in rest else 1
                rec.events.append(Event(
                    seq, turn, side, "effect_remove",
                    card_id=mrem.group("src"), target_id=mrem.group("id"),
                    value=verb_code, raw=rest))
                continue
            # Trash « nu » : remplacement board plein (règle du jeu, pas un effet).
            mbare = L.RE_TRASH_BARE.match(rest)
            if mbare:
                seq += 1
                note_card(mbare.group("id"))
                rec.events.append(Event(
                    seq, turn, side, "trash_bare", card_id=mbare.group("id"), raw=rest))
                continue

        # Fin de tour
        if L.RE_END_TURN.match(rest):
            seq += 1
            rec.events.append(Event(seq, turn, side, "end_turn", raw=rest))
            turn += 1
            continue

        # Concession / victoire
        if L.RE_CONCEDE.match(rest):
            rec.result = "loss" if side == "me" else "win"
            rec.win_reason = "concede"
            continue
        if L.RE_WINS.match(rest):
            rec.result = "win" if side == "me" else "loss"
            rec.win_reason = "damage"
            continue

        # Effets divers : on récupère les cartes référencées SANS leur nom
        # (le texte d'effet pollue les noms ; les noms fiables viennent de
        # Leader/Drew/Deploy).
        for cm in L.CARD_REF.finditer(rest):
            note_card(cm.group("id"))

    # Flush snapshots restants.
    for s in list(pending):
        flush_snapshot(s)

    # Deck restant final (depuis RZ1).
    rec.me.deck_remaining = rz_deck.get("me")
    rec.opp.deck_remaining = rz_deck.get("opp")

    # Récupération des logs tronqués : aucun marqueur de fin parsé -> on tente d'inférer.
    if rec.result is None:
        _infer_truncated_result(rec, cur_life)

    return rec


def _infer_truncated_result(rec: MatchRecord, cur_life: dict[str, int]) -> None:
    """Déduit le résultat d'un log AutoSaved coupé juste avant la ligne finale.

    OPTCGSim écrit parfois le .log avant la ligne 'Wins!'/'Concedes!' (retour rapide au
    menu après le coup gagnant). Sans marqueur, le résultat resterait NULL et la partie
    serait invisible dans les stats (toutes filtrent `result IN ('win','loss')`).

    On n'infère QUE si les preuves sont nettes, sinon on laisse NULL :
      - un seul leader est à 0 vie (vies = derniers snapshots + dégâts mid-combat),
      - l'autre leader est encore en vie,
      - et la dernière attaque sur un leader, dans un tour jamais terminé, visait bien le
        leader à 0 vie (le log se coupe sur l'assaut final = coup de grâce).
    Une partie abandonnée en plein milieu (personne à 0, ou dernière attaque ailleurs)
    reste NULL : on ne devine pas.
    """
    me_l, opp_l = rec.me.leader, rec.opp.leader
    if not me_l or not opp_l:
        return
    dead = [s for s in ("me", "opp")
            if cur_life.get(s) is not None and cur_life[s] <= 0]
    if len(dead) != 1:
        return  # personne (ou les deux) à 0 vie -> ambigu
    loser = dead[0]
    winner = "opp" if loser == "me" else "me"
    if cur_life.get(winner) is not None and cur_life[winner] <= 0:
        return  # sécurité : les deux à 0

    # Dernière cible d'attaque sur un leader, dans le tour final (jamais clôturé par End Turn).
    leader_side = {me_l: "me", opp_l: "opp"}
    final_target: str | None = None
    for e in rec.events:
        if e.type == "end_turn":
            final_target = None  # un tour s'est terminé proprement : pas une troncature létale
        elif e.type == "attack":
            tgt = leader_side.get(e.target_id)
            if tgt is not None:
                final_target = tgt
    if final_target != loser:
        return

    rec.result = "loss" if loser == "me" else "win"
    rec.win_reason = "inferred"
