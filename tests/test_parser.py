"""Tests du parser de match sur la fixture anonymisée."""

from optcgsim_haki.live import LiveState
from optcgsim_haki.parser.match import parse_log
from optcgsim_haki.parser.my_matches import parse_my_matches, detect_local_player
from optcgsim_haki.watcher import replay_current_match


def test_live_new_match_reset_is_gameplay_gated():
    """Nouvelle partie = 1er 'shuffle deck for' APRÈS du gameplay (robuste à l'ordre des joueurs).
    Les shuffles de setup (2 joueurs) ne réinitialisent pas, et un RZ1|HDR de resync non plus —
    même quand l'adversaire mélange EN PREMIER (son identité précède la mienne)."""
    s = LiveState()
    assert s.active is False
    # Partie 1 : l'adversaire mélange d'abord, puis un HDR de resync, puis moi.
    s.feed_line("shuffle deck for Foe#2222")
    s.feed_line("[ReplaySync] RZ1|HDR|1.40a|1|RZ1")          # resync : ne reset pas
    s.feed_line("shuffle deck for Hero#1111")
    s.feed_line("[ReplaySync] RZ1|1|1|OP01-001|0|49|1|0|1|1|0|0|0")
    s.feed_line("Hand before Mulligan: [OP01-001]")
    assert s.active is True
    assert s.me_tag == "Hero#1111" and s.opp_tag == "Foe#2222"
    # Du gameplay a lieu -> le prochain shuffle ouvre une nouvelle partie.
    s.feed_line("[Hero#1111] End Turn")
    s.feed_line("shuffle deck for NewFoe#3333")
    assert s.me_tag is None                                  # reset effectué
    s.feed_line("shuffle deck for Me2#4444")
    s.feed_line("[ReplaySync] RZ1|1|1|OP02-001|0|49|1|0|1|1|0|0|0")
    s.feed_line("Hand before Mulligan: [OP02-001]")
    assert s.me_tag == "Me2#4444" and s.opp_tag == "NewFoe#3333"


def test_live_two_games_do_not_mix_opp_board():
    """Régression : en direct il n'y a pas de ligne texte 'End Turn' — le gameplay se voit via
    le flux RZ1 (play sur le board, zone 2). Sans ce signal, le reset de nouvelle partie ne se
    déclenchait jamais et les decks adverses de parties successives se mélangeaient."""
    s = LiveState()
    # --- Partie 1 (adversaire Foe1) ---
    s.feed_line("shuffle deck for Foe1#1111")
    s.feed_line("shuffle deck for Me#0000")
    s.feed_line("[ReplaySync] RZ1|1|1|OP01-001|0|49|1|0|1|1|0|0|0")   # ma pioche (player 1)
    s.feed_line("Hand before Mulligan: [OP01-001]")
    assert s.me_tag == "Me#0000" and s.opp_tag == "Foe1#1111"
    # L'adversaire (player 2) pose une carte sur le board (zone 2) = gameplay.
    s.feed_line("[ReplaySync] RZ1|2|2|OP09-002|1|2|2|0|1|1|0|0|0")
    assert s.opp.board_ids == ["OP09-002"]
    assert s._played is True

    # --- Partie 2 (nouvel adversaire Foe2) : le 1er shuffle doit réinitialiser ---
    s.feed_line("shuffle deck for Foe2#2222")
    s.feed_line("shuffle deck for Me#0000")
    s.feed_line("[ReplaySync] RZ1|1|1|OP02-002|0|49|1|0|1|1|0|0|0")
    s.feed_line("Hand before Mulligan: [OP02-002]")
    assert s.me_tag == "Me#0000" and s.opp_tag == "Foe2#2222"
    s.feed_line("[ReplaySync] RZ1|2|2|OP14-085|1|2|2|0|1|1|0|0|0")
    # Board adverse = uniquement la partie 2, PAS la carte de la partie 1.
    assert s.opp.board_ids == ["OP14-085"]
    assert "OP09-002" not in s.opp.board_ids


def test_replay_current_match_captures_opp_shuffling_first(tmp_path):
    """replay_current_match reconstruit le DERNIER match et capte le 'shuffle deck for' adverse
    même s'il précède le 'deck filled' (adversaire qui mélange en premier) — sans inclure le
    match précédent (borné par sa ligne préfixée [pseudo])."""
    log = tmp_path / "Player.log"
    log.write_text("\n".join([
        "deck filled, do shuffle",                                # match 1 (à ignorer)
        "shuffle deck for Old#0001",
        "[ReplaySync] RZ1|1|1|OP01-009|0|49|1|0|1|1|0|0|0",
        "Hand before Mulligan: [OP01-009]",
        "shuffle deck for Foe1#0002",
        "[Old#0001] Hand: [OP01-009]",                            # snapshot match 1 -> borne le walk-back
        "shuffle deck for Foe2#2222",                             # match 2 : ADVERSAIRE mélange en 1er
        "deck filled, do shuffle",                                # mon deck (après le shuffle adverse)
        "shuffle deck for Hero#1111",
        "[ReplaySync] RZ1|1|1|OP02-001|0|49|1|0|1|1|0|0|0",
        "Hand before Mulligan: [OP02-001]",
    ]))
    s = LiveState()
    replay_current_match(s, log)
    assert s.me_tag == "Hero#1111" and s.opp_tag == "Foe2#2222"
    assert s.active is True and s.result is None


def test_learn_leader_life_from_logs(tmp_path):
    """La vie d'un leader absent du .pck est déduite des logs AutoSaved (Leader is + Life)."""
    from optcgsim_haki.cardmeta import learn_leader_life_from_logs
    d = tmp_path / "AutoSaved"
    d.mkdir()
    (d / "g1.log").write_text("\n".join([
        '[Alice#0001] Leader is Yamato [<mark><link="OP16-079">OP16-079</link></mark>]',
        '[Bob#0002] Leader is Shanks [<mark><link="OP09-001">OP09-001</link></mark>]',
        "[Alice#0001] Life: 5",
        "[Bob#0002] Life: 5",
        "[Alice#0001] Life: 3",   # plus tard : moins de vie -> on garde le MAX (5)
        "[Bob#0002] Life: 4",
    ]))
    cache = tmp_path / "ll.json"
    life = learn_leader_life_from_logs(d, cache)
    assert life["OP16-079"] == 5      # vie de base = max observé
    assert life["OP09-001"] == 5
    # 2e appel : servi depuis le cache (même signature).
    assert learn_leader_life_from_logs(d, cache)["OP16-079"] == 5


def test_parse_autosaved_match(autosaved_log):
    rec = parse_log(autosaved_log, match_id="test")

    assert rec.room_code == "8BCLK8"
    assert rec.engine_version == "1.40a.60"
    assert rec.me.name == "Alice#0001"
    assert rec.opp.name == "Bob#0002"
    assert rec.me.leader == "PRB01-001"
    assert rec.opp.leader == "OP09-001"

    # Ordre du tour : Alice a choisi de jouer second.
    assert rec.i_went_first is False

    # Mulligan : Alice garde, Bob mulligan.
    assert rec.me.mulligan is False
    assert rec.opp.mulligan is True

    # Main de départ exacte.
    assert rec.me.opening_hand == ["OP09-020", "PRB02-002", "PRB02-003", "OP14-018", "OP09-002"]

    # Résultat : adversaire concède -> victoire.
    assert rec.result == "win"
    assert rec.win_reason == "concede"

    # Données riches présentes.
    assert len(rec.events) > 50
    assert len(rec.snapshots) > 0
    assert rec.card_names["OP09-020"] == "Come on!! We'll fight you!!"
    # Nom de leader propre (pas de texte d'effet).
    assert rec.card_names["PRB01-001"] == "Sanji"


def test_truncated_log_result_is_inferred(truncated_log):
    """Log coupé avant 'Wins!' : le résultat est déduit de la vie + l'assaut final."""
    rec = parse_log(truncated_log, match_id="test")
    # Aucun marqueur de fin dans le log, pourtant l'adversaire (Kaido) est à 0 vie
    # sous une attaque finale -> victoire inférée.
    assert rec.result == "win"
    assert rec.win_reason == "inferred"


def test_inference_stays_null_when_nobody_is_dead(truncated_log):
    """Partie abandonnée sans leader à 0 vie : on ne devine pas, result reste None."""
    # On retire la séquence létale (dégâts + attaque finale) : plus personne à 0.
    safe = "\n".join(
        line for line in truncated_log.splitlines()
        if "hit for" not in line and "attacking" not in line
    )
    rec = parse_log(safe, match_id="test")
    assert rec.result is None


def test_explicit_result_is_not_overridden_by_inference(autosaved_log):
    """La fixture concède explicitement : l'inférence ne doit pas écraser ce résultat."""
    rec = parse_log(autosaved_log, match_id="test")
    assert rec.result == "win"
    assert rec.win_reason == "concede"


def test_hand_size_curve_is_tracked(autosaved_log):
    rec = parse_log(autosaved_log, match_id="test")
    my_snaps = [s for s in rec.snapshots if s.side == "me"]
    assert my_snaps, "des snapshots côté joueur local sont attendus"
    # chaque snapshot expose un compte de main cohérent
    for s in my_snaps:
        assert s.hand_count == len(s.hand_ids)
        assert s.life is None or 0 <= s.life <= 5


def test_rz1_deck_remaining_and_modifiers(autosaved_log):
    rec = parse_log(autosaved_log, match_id="test")
    # Le deck restant est extrait du flux RZ1 (mapping joueur->side par corrélation).
    assert rec.me.deck_remaining is not None
    assert rec.opp.deck_remaining is not None
    assert 0 < rec.me.deck_remaining < 50
    # Les snapshots sont enrichis du deck restant, décroissant dans le temps.
    decks = [s.deck_remaining for s in rec.snapshots if s.side == "me" and s.deck_remaining]
    assert decks and decks == sorted(decks, reverse=True)
    # Les modificateurs de puissance (-1000 etc.) sont captés comme events.
    mods = [e for e in rec.events if e.type == "modifier"]
    assert mods and all(e.value < 0 for e in mods)


def test_don_attach_events_are_distinct_type(autosaved_log):
    """Les events 'Attach N Don' ont le type 'don_attach' (distinct de 'don' = Draw Don).

    Nécessaire pour le calcul du DON Waste : attach = DON engagé durablement, don = gain.
    """
    rec = parse_log(autosaved_log, match_id="test")
    don_draws = [e for e in rec.events if e.type == "don"]
    don_attaches = [e for e in rec.events if e.type == "don_attach"]
    assert don_draws, "au moins un event 'don' (Draw Don) attendu"
    assert don_attaches, "au moins un event 'don_attach' (Attach Don) attendu"
    # Les attaches ont une valeur (nombre de DON attachés).
    for e in don_attaches:
        assert e.value is not None and e.value > 0
    # Les draw don ont aussi une valeur (nombre de DON placés depuis le DON-deck).
    for e in don_draws:
        assert e.value is not None and e.value > 0


def test_rz1_don_deck_remaining_helper():
    """don_deck_remaining lit l'action 4 (placement DON-deck) ; ignore 5 (attach) et 9 (power)."""
    from optcgsim_haki.parser import rz1 as RZ
    place = RZ.parse_rz1_line("RZ1|11|1|Don|4|9|5|0|1|1|0|0|0")
    attach = RZ.parse_rz1_line("RZ1|12|1|Don|5|0|5|0|1|1|1|0|0")
    pmod = RZ.parse_rz1_line("RZ1|44|1|Don|9|9900|5|0|1|1|1|0|0")
    draw = RZ.parse_rz1_line("RZ1|5|1|OP09-002|0|45|1|4|1|1|0|0|0")
    assert RZ.don_deck_remaining(place) == 9      # 9 DON restants -> 1 sur le terrain
    assert RZ.don_deck_remaining(attach) is None  # action 5 = attach, pas un placement
    assert RZ.don_deck_remaining(pmod) is None    # action 9 = power mod (bruit 9900)
    assert RZ.don_deck_remaining(draw) is None    # pas un record Don
    # DON sur terrain = DON_DECK_TOTAL - restants.
    assert RZ.DON_DECK_TOTAL - RZ.don_deck_remaining(place) == 1


def test_live_state_tracks_don_on_field():
    """Le flux RZ1 alimente don_on_field par joueur (10 - DON restants dans le DON-deck).

    Vérifié contre logs réels : premier T1=1/T2=3, second T1=2/T2=4. Ici on rejoue un mini-
    scénario Player.log (mulligan bare -> corrélation des pioches RZ1 -> mapping joueur/side).
    """
    s = LiveState()
    s.feed_line("[ReplaySync] RZ1|HDR|1.40a|1|RZ1")
    s.feed_line("shuffle deck for Hero#1111")
    s.feed_line("[ReplaySync] RZ1|1|1|OP01-001|0|49|1|0|1|1|0|0|0")
    s.feed_line("[ReplaySync] RZ1|2|1|OP01-002|0|48|1|1|1|1|0|0|0")
    s.feed_line("Hand before Mulligan: [OP01-001, OP01-002]")
    s.feed_line("shuffle deck for Foe#2222")
    # Player 1 (me, premier) : 2 placements -> DON sur terrain = 2.
    s.feed_line("[ReplaySync] RZ1|3|1|Don|4|9|5|0|1|1|0|0|0")
    s.feed_line("[ReplaySync] RZ1|4|1|Don|4|8|5|1|1|1|0|0|0")
    # Player 2 (opp, second) : 3 placements -> DON sur terrain = 3.
    s.feed_line("[ReplaySync] RZ1|5|2|Don|4|9|5|0|1|1|0|0|0")
    s.feed_line("[ReplaySync] RZ1|6|2|Don|4|8|5|1|1|1|0|0|0")
    s.feed_line("[ReplaySync] RZ1|7|2|Don|4|7|5|2|1|1|0|0|0")
    # Les actions 5 (attach) ne doivent pas perturber le compte.
    s.feed_line("[ReplaySync] RZ1|8|2|Don|5|0|5|0|1|1|1|0|0")
    assert s.me is not None and s.opp is not None
    assert s.me.don_on_field == 2
    assert s.opp.don_on_field == 3


def test_my_matches_normalization():
    # Le joueur local doit toujours être en position "me" après normalisation.
    data = {"matches": [
        # slot A = local
        ["Local", "Local", 100.0, False, 1, "win", "Foe", "Foe", 90.0, False, 2, "loss",
         0, 0, 300.0, 0, "2026-01-01T10:00:00",
         ["1xLDR-001", "4xC-001"], ["1xLDR-002", "4xC-002"], True,
         "+10", "-10", [["C-001", "C-001"], "keep"], [], 1, 2, 3],
        # slot B = local (perspective inversée)
        ["Foe", "Foe", 90.0, False, 2, "win", "Local", "Local", 100.0, False, 1, "loss",
         0, 0, 300.0, 0, "2026-01-01T11:00:00",
         ["1xLDR-002", "4xC-002"], ["1xLDR-001", "4xC-001"], True,
         "+10", "-10", [["C-002"], "mulligan"], [], 1, 2, 3],
    ]}
    local = detect_local_player(data)
    assert local == "Local"
    rms = parse_my_matches(data, local)
    assert all(r.me == "Local" for r in rms)
    # 1re partie gagnée, 2e perdue (du point de vue local).
    assert rms[0].my_result == "win" and rms[0].my_leader == "LDR-001"
    assert rms[1].my_result == "loss" and rms[1].my_leader == "LDR-001"


def _ref(cid, name="Card"):
    """Construit une référence de carte au format des logs : 'Name [<mark><link=...>]'."""
    return f'{name} [<mark><link="{cid}">{cid}</link></mark>]'


def _live_with_opp(effect_caps=None):
    s = LiveState()
    s.reset_match()
    # Adversaire = joueur RZ1 n°2 (résolution simplifiée pour le test).
    s.opp_tag = "Foe#0001"
    s._player("Foe#0001").side = "opp"
    s._player_to_tag[2] = "Foe#0001"
    # Classification d'effets injectée (découple les tests de card_stats.json).
    s.effect_caps = {k: frozenset(v) for k, v in (effect_caps or {}).items()}
    return s


def test_opp_board_removed_only_by_explicit_ko():
    """Un KO explicite ('Destroyed') retire du board ; pas un counter défaussé de la main."""
    s = _live_with_opp()
    # Deux personnages déployés au board (zone c6=2).
    s.feed_line("RZ1|10|2|OP01-001|1|40|2|0|0|0|0|0|0")
    s.feed_line("RZ1|11|2|OP01-002|1|40|2|0|0|0|0|0|0")
    assert s.opp.board_ids == ["OP01-001", "OP01-002"]

    # L'adversaire DÉFEND avec un exemplaire d'OP01-002 défaussé de la main (counter).
    # Le flux RZ1 émet la même zone trash (6), MAIS la ligne texte est un counter de MAIN :
    # l'exemplaire posé sur le board ne doit PAS disparaître.
    s.feed_line("RZ1|20|2|OP01-002|1|40|6|0|0|0|0|0|0")
    s.feed_line(f"[Foe#0001] Discard {_ref('OP01-002')} for Counter 2000")
    assert s.opp.board_ids == ["OP01-001", "OP01-002"]   # toujours là

    # OP01-001 est réellement KO en combat -> ligne 'Destroyed' attribuée au propriétaire.
    s.feed_line(f"[Foe#0001] {_ref('OP01-001', 'Uta')} Destroyed")
    assert s.opp.board_ids == ["OP01-002"]

    # Re-déploiement d'OP01-001 : il réapparaît (le retrait est annulé).
    s.feed_line("RZ1|30|2|OP01-001|1|40|2|0|0|0|0|0|0")
    assert s.opp.board_ids == ["OP01-001", "OP01-002"]


def test_opp_board_removed_by_effect_trash():
    """Un effet qui trash UN CHARACTER (source classée trash_char) retire la cible du board."""
    # OP05-007 est une carte dont l'effet trash un Character (capacité trash_char).
    s = _live_with_opp({"OP05-007": {"trash_char"}})
    s.feed_line("RZ1|10|2|OP05-100|1|40|2|0|0|0|0|0|0")
    assert s.opp.board_ids == ["OP05-100"]
    s.feed_line(f"[Me#9999] {_ref('OP05-007', 'Law')}: Trash {_ref('OP05-100', 'Hongo')}")
    assert s.opp.board_ids == []


def test_opp_board_removed_by_bounce_and_bottom():
    """Return to Hand (bounce) et Send to Deck Bottom retirent la cible — source classée."""
    s = _live_with_opp({"OP13-031": {"bounce"}, "OP10-060": {"deck"}})
    s.feed_line("RZ1|10|2|OP12-034|1|40|2|0|0|0|0|0|0")  # Perona
    s.feed_line("RZ1|11|2|OP12-015|1|40|2|0|0|0|0|0|0")  # Luffy
    assert s.opp.board_ids == ["OP12-015", "OP12-034"]
    # Bounce vers la main (grammaire réelle : "<Src> [sid]: Return <Cible> [tid] to Hand").
    s.feed_line(f"[Me#9999] {_ref('OP13-031', 'Law')}: Return {_ref('OP12-034', 'Perona')} to Hand")
    assert s.opp.board_ids == ["OP12-015"]
    # Envoi sous le deck.
    s.feed_line(f"[Me#9999] {_ref('OP10-060', 'Bari')}: Send {_ref('OP12-015', 'Luffy')} to Deck Bottom")
    assert s.opp.board_ids == []


def test_effect_remove_ignored_when_source_does_not_move_characters():
    """Source non classée (effet deck/trash/main) -> aucun retrait, même cible sur le board.

    C'est le cas Shiryu : 'Trash 1 card from your hand' n'agit pas sur un Character. Avec le
    mode strict, même un exemplaire posé du MÊME id est préservé (résout l'ambiguïté doublon)."""
    s = _live_with_opp(effect_caps={})  # OP16-108 absent -> aucune capacité
    s.feed_line("RZ1|10|2|OP16-106|1|40|2|0|0|0|0|0|0")  # Sanjuan Wolf posé
    s.feed_line(f"[Foe#0001] {_ref('OP16-108', 'Shiryu')}: Trash {_ref('OP16-106', 'Sanjuan Wolf')}")
    assert s.opp.board_ids == ["OP16-106"]  # Shiryu trash depuis la main -> board intact


def test_add_to_life_is_not_a_board_removal():
    """Shiryu/Gecko Moria ajoutent une carte aux Life depuis le DECK/la TRASH, pas le board.

    Même si un exemplaire du MÊME id est sur le board, il ne doit pas être retiré.
    """
    s = _live_with_opp()
    s.feed_line("RZ1|10|2|OP16-106|1|40|2|0|0|0|0|0|0")  # Sanjuan Wolf posé sur le board
    assert s.opp.board_ids == ["OP16-106"]
    # Shiryu regarde le top du deck et y trouve un AUTRE Sanjuan Wolf qu'il met sous les Life.
    s.feed_line(
        f"[Foe#0001] {_ref('OP16-108', 'Shiryu')}: Add {_ref('OP16-106', 'Sanjuan Wolf')} to top of Life"
    )
    assert s.opp.board_ids == ["OP16-106"]  # l'exemplaire posé reste en jeu
    # "Add card to top of Life from Deck" (sans cible) ne touche pas le board non plus.
    s.feed_line(f"[Foe#0001] {_ref('OP15-113', 'Zoro')}: Add card to top of Life from Deck")
    assert s.opp.board_ids == ["OP16-106"]


def test_opp_board_full_replacement_trashes_replaced_character():
    """Board plein (5) : poser un 6e perso trash un perso existant -> il quitte le board.

    Le jeu loggue un 'Trash <Character> [id]' NU (sans source ni ':'), attribué au propriétaire.
    """
    s = _live_with_opp()
    for i, cid in enumerate(["OP01-001", "OP01-002", "OP01-003", "OP01-004", "OP01-005"]):
        s.feed_line(f"RZ1|{10+i}|2|{cid}|1|40|2|0|0|0|0|0|0")
    assert len(s.opp.board_ids) == 5
    # Remplacement : l'adversaire trash OP01-003 (ligne nue) puis déploie un 6e.
    s.feed_line(f"[Foe#0001] Trash {_ref('OP01-003', 'Donquixote Rosinante')}")
    s.feed_line("RZ1|20|2|OP01-099|1|40|2|0|0|0|0|0|0")
    assert "OP01-003" not in s.opp.board_ids
    assert sorted(s.opp.board_ids) == ["OP01-001", "OP01-002", "OP01-004", "OP01-005", "OP01-099"]


def test_opp_board_ignores_send_life_to_hand():
    """'Send 1 Life to Hand' (sans carte ciblée) ne retire rien du board."""
    s = _live_with_opp()
    s.feed_line("RZ1|10|2|OP16-116|1|40|2|0|0|0|0|0|0")
    s.feed_line(f"[Foe#0001] {_ref('OP16-116', 'Teach')}: Send 1 Life to Hand")
    assert s.opp.board_ids == ["OP16-116"]


# --- Tests des nouveaux events pour le Value Score ---

def test_parser_captures_ko_events(autosaved_log):
    """Le parser capture les KO (Destroyed) comme events de type 'ko'."""
    rec = parse_log(autosaved_log, match_id="test")
    ko_events = [e for e in rec.events if e.type == "ko"]
    assert len(ko_events) >= 3  # au moins 3 KO dans la fixture
    # Chaque KO a un card_id et un side.
    for e in ko_events:
        assert e.card_id is not None
        assert e.side in ("me", "opp")


def test_parser_captures_effect_remove_events(autosaved_log):
    """Le parser capture les effets de retrait (Source: Trash/Return Cible) comme events."""
    rec = parse_log(autosaved_log, match_id="test")
    er_events = [e for e in rec.events if e.type == "effect_remove"]
    assert len(er_events) >= 1
    # Lucky Roux (PRB02-003) trash Benn Beckman (OP09-009).
    lucky = next(e for e in er_events if e.card_id == "PRB02-003")
    assert lucky.target_id == "OP09-009"
    assert lucky.value == 1  # verb_code 1 = trash
    # side = initiateur (Alice = me)
    assert lucky.side == "me"


def test_parser_captures_life_damage_events(autosaved_log):
    """Le parser capture les dégâts de vie (hit for N damage) comme events."""
    rec = parse_log(autosaved_log, match_id="test")
    ld_events = [e for e in rec.events if e.type == "life_damage"]
    assert len(ld_events) >= 5  # au moins 5 hit for N damage
    for e in ld_events:
        assert e.value is not None and e.value > 0
        assert e.target_id is not None  # leader touché
        assert e.side in ("me", "opp")  # camp qui inflige


def test_parser_captures_attack_fail_events(autosaved_log):
    """Le parser capture les attaques échouées (Attack Fails) comme events."""
    rec = parse_log(autosaved_log, match_id="test")
    af_events = [e for e in rec.events if e.type == "attack_fail"]
    assert len(af_events) >= 5  # au moins 5 Attack Fails dans la fixture


def test_parser_effect_remove_verb_codes(autosaved_log):
    """Les verb codes pour effect_remove : 1=trash, 2=bounce, 3=deck."""
    rec = parse_log(autosaved_log, match_id="test")
    er_events = [e for e in rec.events if e.type == "effect_remove"]
    # Au moins un trash (verb=1) dans la fixture.
    trash_events = [e for e in er_events if e.value == 1]
    assert len(trash_events) >= 1
