"""État live d'une partie, reconstruit incrémentalement depuis Player.log.

Conception fair-play :
- L'état interne CONTIENT toute l'information présente dans le log (y compris la main cachée de
  l'adversaire et l'ordre des decks), car le jeu l'y écrit.
- Le RENDU décide quoi exposer : par défaut (`reveal_all=False`) on n'affiche que l'information
  publique (cartes jouées/board, life, nombre de cartes en main adverse). `reveal_all=True` lève
  le voile (revue post-match) avec un avertissement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import card_effects
from .parser import loglines as L
from .parser import rz1 as RZ


@dataclass
class LivePlayer:
    tag: str
    side: str = "?"            # me | opp
    leader: str | None = None
    leader_name: str | None = None
    life: int | None = None
    hand_ids: list[str] = field(default_factory=list)   # info complète (peut être cachée)
    board_ids: list[str] = field(default_factory=list)
    trash_ids: list[str] = field(default_factory=list)
    deck_remaining: int | None = None
    don_on_field: int | None = None   # DON actif sur le terrain (flux RZ1, action 4)
    mulligan: bool | None = None
    # En live, l'état adverse vient du flux RZ1 (zones cumulées) : le contenu/compte exact de
    # la main n'est pas fiable -> on l'indique pour ne pas afficher de nombre trompeur.
    hand_count_known: bool = False
    # Compte de main APPROXIMATIF déduit du flux RZ1 (draws/plays/counters). Garde-fou : None
    # si une incohérence est détectée (ex. main négative). Utilisé en live quand hand_count_known
    # est False (pas de snapshot texte adverse dans Player.log).
    hand_count_rz1: int | None = None
    # Counters dépensés ("Discard ... for Counter N") : événement PUBLIC du log, attribué au
    # joueur par son préfixe -> comptage exact (nombre + somme des valeurs).
    counters_spent_count: int = 0
    counters_spent_total: int = 0
    # Modifier Engine : pile de modificateurs de puissance par entité.
    # Clé = card_id (leader ou character), valeur = liste de Modifier.
    # Le leader est identifié par son card_id (p.leader).
    modifiers: dict[str, list["Modifier"]] = field(default_factory=dict)


@dataclass
class Modifier:
    """Modificateur de puissance temporaire appliqué à une entité (leader ou character).

    Types :
      - "ADD" : ajoute value à la power (ex: +2000, -1000). SEUL type émis par le parser :
        le log OPTCGSim émet toujours un delta additif, même pour « base power becomes X »
        (EB04-004 « base becomes 7000 » est loggé « Grant Sanji 2000 », le delta vers 5000).
      - "SET_BASE" : remplace la power de base. Mécanisme conservé dans get_current_power pour
        un réglage manuel/futur, mais jamais produit par feed_line.

    Expiry :
      - "END_OF_CURRENT_TURN" : expire à la fin du tour en cours
      - "END_OF_NEXT_TURN" : expire à la fin du prochain tour (« opponent's next turn »)
      - "END_OF_OWN_NEXT_TURN" : expire à la fin du PROPRE prochain tour du camp applicateur
        (« your next turn ») — ~2 tours plus tard, un tour adverse intercalé
      - "PERMANENT" : ne expire jamais (rare)
    """
    source_id: str
    mod_type: str           # "ADD" | "SET_BASE"
    value: int              # en puissance OPTCG (2000 = +2000)
    expiry: str             # CURRENT | NEXT | OWN_NEXT | PERMANENT (cf. docstring)
    applied_at_turn: int
    applied_by_side: str    # "me" | "opp" — camp qui a appliqué le buff


class LiveState:
    def __init__(self) -> None:
        self.room_code: str | None = None
        self.version: str | None = None
        self.players: dict[str, LivePlayer] = {}
        self.me_tag: str | None = None
        self.opp_tag: str | None = None
        self.card_names: dict[str, str] = {}
        self.result: str | None = None
        self.win_reason: str | None = None
        self.active: bool = False
        self._last_shuffle_tag: str | None = None  # pour détecter "me" dans Player.log
        self._shuffle_order: list[str] = []        # tags vus via "shuffle deck for"
        # RZ1 : mapping n° joueur -> tag, via corrélation des pioches avec la main de mulligan.
        self._rz_draws: dict[int, list[str]] = {}
        self._rz_deck: dict[int, int] = {}
        self._rz_don: dict[int, int] = {}   # n° joueur RZ1 -> DON sur le terrain (10 - restants)
        self._rz_hand: dict[int, int] = {}  # n° joueur RZ1 -> net de main (non corrigé)
        # n° joueur RZ1 -> identités des cartes en main, reconstruites depuis le flux RZ1
        # (le flux révèle l'identité des cartes piochées, y compris celles de l'adversaire).
        # Information CACHÉE : exposée uniquement en mode reveal_all (revue / hors-ligne).
        self._rz_hand_ids: dict[int, list[str]] = {}
        # Dégâts cumulés par leader (card_id) depuis les lignes "hit for N damage" (globales).
        # Sert à calculer la vie en live : base_life(leader) - dommages. Aucune dépendance au
        # tag joueur : la ligne référence l'ID du leader touché, pas un pseudo.
        self._leader_damage: dict[str, int] = {}
        self._player_to_tag: dict[int, str] = {}
        # MON deck, loggé en clair par "Playing with deck:" à la sélection -> decklist et
        # leader EXACTS. Survit à reset_match : la dernière sélection décrit toujours la
        # partie courante/suivante (la ligne précède les shuffles qui déclenchent le reset).
        self.my_deck_name: str | None = None
        # Ids vus dans "Start Using V3 Action [...]" : les leaders y figurent quand ils
        # attaquent/activent. Filtré côté engine (type leader ≠ mon leader -> leader ADVERSE,
        # observé exactement — prime sur l'inférence d'archétype).
        self.v3_action_ids: set[str] = set()
        # Suivi CUMULATIF des zones publiques par flux RZ1 : player_num -> {zone: set(cards)}.
        # zone (col c6) : 1=main, 2=board, 6=trash. La colonne d'index (c7) n'étant pas un
        # identifiant d'exemplaire stable, on ne peut pas suivre chaque carte physiquement ;
        # on retient donc l'ensemble des cartes VUES dans chaque zone (board joué, trash) —
        # robuste et suffisant pour le fair-play (board + trash publics).
        self._seen_zone: dict[int, dict[int, set]] = {}
        # Comptage PUBLIC des exemplaires joués depuis la main, par joueur RZ1 (« 2/4 ») :
        # +1 quand une carte quitte la main vers une zone visible (pose, counter/event),
        # -1 si elle y retourne (bounce) — un re-play ne compte alors pas double.
        self._rz_played: dict[int, dict[str, int]] = {}
        # Cartes retirées du board adverse par un effet EXPLICITE (KO / Destroyed / Trash par
        # effet). On ne se fie PAS à la zone trash du flux RZ1 pour ça : un counter défaussé
        # depuis la main produit le même signal de zone, ce qui retirerait à tort un exemplaire
        # encore en jeu. Seules les lignes texte de retrait (owner-attribuées) font foi.
        self._opp_removed: set[str] = set()
        self._opp_has_snapshot = False  # vrai si des snapshots adverses existent (AutoSaved)
        # Classification d'effets injectable (tests) ; sinon card_effects (card_stats.json).
        self.effect_caps: dict[str, frozenset] | None = None
        # Modifier Engine : suivi du tour courant et du camp actif pour la GC des modificateurs.
        self._turn: int = 1
        self._active_side: str = "?"    # "me" | "opp" — camp dont c'est le tour
        # Vrai dès qu'un gameplay a eu lieu (deploy / fin de tour) : sert à distinguer le 1er
        # shuffle d'une NOUVELLE partie (gameplay avant) des shuffles de setup (aucun gameplay).
        self._played: bool = False
        # Nombre total de "life added to hand" (1 vie perdue par UN des deux joueurs). En live,
        # Player.log n'a ni snapshot de vie adverse ni ligne "hit for N damage" : on dérive la vie
        # adverse = total − mes pertes (connues par MES snapshots). Reset par partie.
        self._life_to_hand: int = 0
        # --- Solo vs Self ---
        # En Solo vs Self, les deux joueurs sont contrôlés localement : les lignes n'ont pas de
        # tag joueur (préfixe "[]"), pas de "Leader is", pas de "Hand before Mulligan". On utilise
        # des tags synthétiques "solo_p1"/"solo_p2" mappés sur les n° joueurs RZ1 (1/2).
        self.is_solo: bool = False
        # N° joueur RZ1 du dernier snapshot [] attribué (pour Board/Trash/Life qui suivent Hand).
        self._solo_snapshot_pnum: int | None = None
        # N° joueur RZ1 dont c'est le tour (via "start action phase for player (N)").
        self._solo_active_pnum: int | None = None

    # --- Helpers ---
    def _player(self, tag: str) -> LivePlayer:
        p = self.players.get(tag)
        if p is None:
            p = LivePlayer(tag=tag)
            self.players[tag] = p
        return p

    def _assign_sides(self) -> None:
        """me = propriétaire de 'Hand before Mulligan' ; opp = l'AUTRE tag ayant mélangé.

        L'adversaire mélange après le mulligan local : opp_tag est résolu dès qu'un tag de
        shuffle différent de me apparaît (pas seulement au moment du mulligan).

        En Solo vs Self : pas de tag joueur — on assigne des tags synthétiques mappés sur les
        n° joueurs RZ1 (1=me, 2=opp).
        """
        if self.is_solo:
            self.me_tag = "solo_p1"
            self.opp_tag = "solo_p2"
            for tag, p in self.players.items():
                p.side = "me" if tag == "solo_p1" else "opp"
            # Map les n° RZ1 -> tags synthétiques si pas déjà fait.
            for pnum in (1, 2):
                tag = f"solo_p{pnum}"
                self._player_to_tag.setdefault(pnum, tag)
                self._player(tag)
            return
        if not self.me_tag:
            return
        if self.opp_tag is None:
            # Live : l'adversaire est identifié par son "shuffle deck for".
            for tag in self._shuffle_order:
                if tag != self.me_tag:
                    self.opp_tag = tag
                    break
        if self.opp_tag is None:
            # AutoSaved : pas de shuffle -> l'adversaire apparaît via "Leader is"/snapshots.
            for tag in self.players:
                if tag != self.me_tag:
                    self.opp_tag = tag
                    break
        for tag, p in self.players.items():
            p.side = "me" if tag == self.me_tag else "opp"
        # Complète le mapping n° joueur RZ1 -> adversaire si le n° local est connu.
        if self.opp_tag:
            me_nums = [n for n, t in self._player_to_tag.items() if t == self.me_tag]
            if me_nums:
                other = 2 if me_nums[0] == 1 else 1
                self._player_to_tag.setdefault(other, self.opp_tag)

    def reset_match(self) -> None:
        self.room_code = None
        self.players.clear()
        self.me_tag = self.opp_tag = None
        self.result = None
        self.win_reason = None
        self.active = True
        self._last_shuffle_tag = None
        self._shuffle_order.clear()
        self._rz_draws.clear()
        self._rz_deck.clear()
        self._rz_don.clear()
        self._rz_hand.clear()
        self._rz_hand_ids.clear()
        self._leader_damage.clear()
        self._player_to_tag.clear()
        self.v3_action_ids.clear()
        # my_deck_name N'EST PAS effacé : "Playing with deck" précède le reset (sélection
        # avant shuffles) et reste valable pour la partie qui démarre.
        self._seen_zone.clear()
        self._rz_played.clear()
        self._opp_removed.clear()
        self._opp_has_snapshot = False
        self._turn = 1
        self._active_side = "?"
        self._played = False
        self._life_to_hand = 0
        self.is_solo = False
        self._solo_snapshot_pnum = None
        self._solo_active_pnum = None

    @property
    def me(self) -> LivePlayer | None:
        return self.players.get(self.me_tag) if self.me_tag else None

    @property
    def opp(self) -> LivePlayer | None:
        return self.players.get(self.opp_tag) if self.opp_tag else None

    # --- Modifier Engine ---
    def get_current_power(self, player: LivePlayer | None, card_id: str | None,
                          base_power: int) -> int:
        """Puissance effective d'une entité à l'instant T (base + modificateurs).

        Ordre de résolution :
        1. Prendre la power originale (base_power).
        2. Appliquer les SET_BASE (le plus récent écrase).
        3. Appliquer les ADD (somme de tous les buffs/malus).
        """
        if not player or not card_id:
            return base_power
        mods = player.modifiers.get(card_id, [])
        if not mods:
            return base_power
        # 1. SET_BASE : le dernier appliqué écrase.
        set_mods = [m for m in mods if m.mod_type == "SET_BASE"]
        power = set_mods[-1].value if set_mods else base_power
        # 2. ADD : somme de tous les buffs/malus continus.
        for m in mods:
            if m.mod_type == "ADD":
                power += m.value
        return power

    def _apply_modifier(self, player: LivePlayer, target_id: str,
                        mod: Modifier) -> None:
        """Ajoute un modificateur à la pile d'une entité."""
        player.modifiers.setdefault(target_id, []).append(mod)

    def _gc_modifiers(self) -> None:
        """Garbage collection : supprime les modificateurs expirés à la fin d'un tour.

        Règle d'expiry :
        - END_OF_CURRENT_TURN : expire si le tour du camp qui l'a appliqué se termine.
        - END_OF_NEXT_TURN : expire au tour SUIVANT le camp qui l'a appliqué.
        - PERMANENT : jamais supprimé.
        """
        ending_side = self._active_side
        for p in self.players.values():
            for cid in list(p.modifiers.keys()):
                p.modifiers[cid] = [
                    m for m in p.modifiers[cid]
                    if not self._is_expired(m, ending_side)
                ]
                if not p.modifiers[cid]:
                    del p.modifiers[cid]

    def _is_expired(self, mod: Modifier, ending_side: str) -> bool:
        """Détermine si un modificateur expire à la fin du tour `ending_side`.

        Repère temporel : `_gc_modifiers` est appelé AVANT l'incrément de `self._turn`, donc
        pendant la GC `self._turn` vaut encore le numéro du tour qui se termine.
        """
        if mod.expiry == "PERMANENT":
            return False
        if mod.expiry == "END_OF_CURRENT_TURN":
            # Expire si le tour du camp qui a appliqué le buff se termine.
            return ending_side == mod.applied_by_side
        if mod.expiry == "END_OF_NEXT_TURN":
            # "opponent's next turn end" : le prochain tour = celui du camp ADVERSE.
            other = "opp" if mod.applied_by_side == "me" else "me"
            return ending_side == other
        if mod.expiry == "END_OF_OWN_NEXT_TURN":
            # "your next turn end" : le PROPRE prochain tour du camp applicateur, soit ~2 tours
            # plus tard (tour adverse intercalé). Expire quand le camp applicateur termine un
            # tour POSTÉRIEUR à celui de l'application (pas la fin du tour courant).
            return ending_side == mod.applied_by_side and self._turn > mod.applied_at_turn
        return False

    @staticmethod
    def _parse_expiry(expiry_text: str, applier_side: str = "me") -> str:
        """Interprète le texte d'expiry du log en constante normalisée.

        La propriété est encodée dans le texte (« your »/« opponent's »), relative au camp
        applicateur — d'où la distinction de durée :
        - "opponent's next turn end" → END_OF_NEXT_TURN (tour adverse = le prochain tour)
        - "your/my next turn end" → END_OF_OWN_NEXT_TURN (propre prochain tour, ~2 tours plus tard)
        - "this turn end" / "during this turn" / "this battle" → END_OF_CURRENT_TURN
        - "next turn" sans propriétaire → END_OF_NEXT_TURN (le tour immédiatement suivant)
        """
        t = expiry_text.lower().strip()
        if "this turn" in t or "this battle" in t or "during this" in t:
            return "END_OF_CURRENT_TURN"
        if "opponent" in t:
            return "END_OF_NEXT_TURN"
        if ("your" in t or "my" in t) and "next turn" in t:
            return "END_OF_OWN_NEXT_TURN"
        if "next turn" in t:
            return "END_OF_NEXT_TURN"
        # Fallback conservateur : on suppose que ça dure jusqu'au prochain tour.
        return "END_OF_NEXT_TURN"

    # --- Ingestion d'une ligne ---
    def _update_deck_counts(self) -> None:
        for pnum, tag in self._player_to_tag.items():
            if pnum in self._rz_deck and tag in self.players:
                self.players[tag].deck_remaining = self._rz_deck[pnum]

    def _update_don_counts(self) -> None:
        for pnum, tag in self._player_to_tag.items():
            if pnum in self._rz_don and tag in self.players:
                self.players[tag].don_on_field = self._rz_don[pnum]

    def _update_hand_counts(self) -> None:
        for pnum, tag in self._player_to_tag.items():
            if tag in self.players and pnum in self._rz_hand:
                self.players[tag].hand_count_rz1 = self._rz_hand[pnum]

    # Zones RZ1 (col c6) -> sémantique.
    _Z_HAND, _Z_BOARD, _Z_TRASH = 1, 2, 6
    _Z_DECK = 0

    # Delta de main par (action, zone) RZ1 — vérifié contre snapshots texte d'un AutoSaved.
    #   act=0 zone=1 : pioche deck->main          (+1)
    #   act=1 zone=2 : main->board (pose)         (-1)
    #   act=1 zone=6 : main->trash (counter/event joué) (-1)
    #   act=1 zone=0 : main->deck (retour mulligan)   (-1)
    #   act=1 zone=1 : effet ->main               (+1)
    #   act=2 zone=6 : board->trash (KO)          (0)
    #   act=2 zone=1 : board/trash->main (bounce) (+1)
    #   act=2 zone=2 : board->board (rejouer)     (0)
    # NB : les life cards prises en dommage ne SONT PAS dans le flux RZ1 (life→main non émis).
    # Le net RZ1 sous-compte donc de `leader_damage` ; la correction est appliquée côté
    # engine (qui connaît le leader adverse via observation/inférence d'archétype).
    _HAND_DELTA: dict[tuple[int, int], int] = {
        (0, 1): +1, (1, 2): -1, (1, 6): -1, (1, 0): -1, (1, 1): +1, (2, 1): +1,
    }

    def _ingest_rz1(self, ev) -> None:
        """Met à jour pioches, deck restant, DON, main et zones publiques (cumulatif)."""
        # Records Don : seul le placement depuis le DON-deck (action 4) donne le compte fiable
        # du DON actif (10 - restants). Les actions 5 (attach) et 9 (power mod) sont ignorées.
        if ev.card == "Don":
            rem = RZ.don_deck_remaining(ev)
            if rem is not None:
                self._rz_don[ev.player] = RZ.DON_DECK_TOTAL - rem
                self._update_don_counts()
            return
        if len(ev.cols) < 4:
            return
        action, deck_after, zone = ev.cols[0], ev.cols[1], ev.cols[2]
        if RZ.is_draw(ev):  # action 0 + carte = pioche
            self._rz_draws.setdefault(ev.player, []).append(ev.card)
            if isinstance(deck_after, int):
                self._rz_deck[ev.player] = deck_after
            self._update_deck_counts()
        # Compte de main approximatif (net RZ1, non corrigé des life→main).
        if isinstance(action, int) and isinstance(zone, int):
            delta = self._HAND_DELTA.get((action, zone), 0)
            if delta:
                self._rz_hand[ev.player] = self._rz_hand.get(ev.player, 0) + delta
                # Suivi des IDENTITÉS en main (pour reveal_all) : +carte si elle entre en main,
                # -carte si elle en sort. Le flux RZ1 révèle l'identité même côté adverse.
                ids = self._rz_hand_ids.setdefault(ev.player, [])
                if delta > 0:
                    ids.append(ev.card)
                elif ev.card in ids:
                    ids.remove(ev.card)
                self._update_hand_counts()
        # Comptage des exemplaires joués depuis la main (« vus 2/4 ») : événements PUBLICS
        # uniquement. Les KO (2→6) ne comptent pas — l'exemplaire a été compté à la pose.
        if isinstance(action, int) and isinstance(zone, int):
            played = self._rz_played.setdefault(ev.player, {})
            if (action, zone) in ((1, 2), (1, 6)):
                played[ev.card] = played.get(ev.card, 0) + 1
            elif (action, zone) == (2, 1) and played.get(ev.card, 0) > 0:
                played[ev.card] -= 1
        # Cumule les cartes VUES dans chaque zone publique (board/trash).
        if isinstance(zone, int):
            self._seen_zone.setdefault(ev.player, {}).setdefault(zone, set()).add(ev.card)
            if zone == self._Z_BOARD:
                # Un play sur le board = GAMEPLAY. C'est le signal fiable en direct : le
                # Player.log n'a pas de ligne texte "End Turn" (seulement le flux RZ1 + "Switch
                # turns"). Sans ça, _played resterait False et le reset de nouvelle partie ne se
                # déclencherait jamais -> les decks de parties successives se mélangeraient.
                self._played = True
                # Re-déploiement : une carte replacée sur le board adverse n'est plus « retirée ».
                if ev.player == self._opp_player_num():
                    self._opp_removed.discard(ev.card)
        self._rebuild_opp_zones()

    def leader_damage(self, leader_id: str | None) -> int:
        """Dégâts cumulés sur un leader (card_id) depuis les lignes 'hit for N damage'."""
        if not leader_id:
            return 0
        return self._leader_damage.get(leader_id, 0)

    def _opp_player_num(self) -> int | None:
        for pnum, tag in self._player_to_tag.items():
            if tag == self.opp_tag:
                return pnum
        return None

    def _rebuild_opp_zones(self) -> None:
        """Reconstruit board (joué) et trash de l'adversaire depuis les zones RZ1 cumulées.

        Player.log n'écrit pas les snapshots adverses : le flux RZ1 est la seule source en live.
        On expose l'ensemble des cartes VUES jouées (board) et en trash — information PUBLIQUE.
        La main reste cachée et son compte n'est pas fiable (-> hand_count_known=False).
        Si des snapshots adverses existent (logs AutoSaved post-partie), on les laisse primer.
        """
        if self._opp_has_snapshot:
            return
        pnum = self._opp_player_num()
        if pnum is None or self.opp is None:
            return
        zones = self._seen_zone.get(pnum, {})
        board_seen = zones.get(self._Z_BOARD, set())
        # Board = cartes vues jouées MOINS celles retirées par un effet explicite (KO / Trash).
        # On NE retranche PAS la zone trash RZ1 : elle inclut aussi les counters défaussés depuis
        # la main, ce qui supprimerait par erreur un exemplaire encore présent sur le board.
        self.opp.board_ids = sorted(board_seen - self._opp_removed)
        self.opp.trash_ids = sorted(zones.get(self._Z_TRASH, set()))
        self.opp.hand_ids = []
        self.opp.hand_count_known = False

    def opp_played_counts(self) -> dict[str, int]:
        """Exemplaires adverses VUS joués depuis la main (public, exact), par card_id.

        Ne compte que ce qui a quitté la main adverse vers une zone visible ; ne révèle
        rien de caché (compatible fair-play). Max 4 par carte selon les règles du jeu."""
        pnum = self._opp_player_num()
        if pnum is None:
            return {}
        return {c: n for c, n in self._rz_played.get(pnum, {}).items() if n > 0}

    def _opp_board_seen(self) -> set:
        pnum = self._opp_player_num()
        if pnum is None:
            return set()
        return self._seen_zone.get(pnum, {}).get(self._Z_BOARD, set())

    def _source_caps(self, cid: str) -> frozenset:
        if self.effect_caps is not None:
            return self.effect_caps.get(cid, frozenset())
        return card_effects.source_caps(cid)

    # --- Solo vs Self : attribution des snapshots [] ---
    def _match_solo_player_by_hand(self, hand_ids: list[str]) -> int | None:
        """Identifie le n° joueur RZ1 dont la main correspond au snapshot [].

        Compare le contenu de la main (set) avec _rz_hand_ids pour chaque joueur RZ1.
        Fallback : meilleur recoupement si aucune correspondance exacte (cartes jouées/piochées
        entre le snapshot RZ1 et le snapshot texte).
        """
        if not hand_ids:
            return None
        hand_set = set(hand_ids)
        # Correspondance exacte (set) en priorité.
        for pnum, rz_ids in self._rz_hand_ids.items():
            if set(rz_ids) == hand_set:
                return pnum
        # Fallback : meilleur recoupement.
        best_pnum, best_score = None, 0
        for pnum, rz_ids in self._rz_hand_ids.items():
            score = len(hand_set & set(rz_ids))
            if score > best_score:
                best_score = score
                best_pnum = pnum
        return best_pnum

    def _handle_solo_snapshot(self, rest: str) -> None:
        """Attribue un snapshot [] (Hand/Board/Trash/Life) au bon joueur en Solo vs Self.

        Les snapshots [] n'ont pas de préfixe joueur. On détermine le joueur à partir de la
        main (matching avec _rz_hand_ids), puis les Board/Trash/Life qui suivent dans le même
        groupe sont attribués au même joueur.
        """
        # Counter défaussé ("[] Discard ... for Counter N") : un counter ne se joue que
        # pendant le tour ADVERSE -> attribution exacte au joueur NON-actif. Sans joueur
        # actif connu, on ne devine pas.
        mdc = L.RE_DISCARD_COUNTER.match(rest)
        if mdc:
            if self._solo_active_pnum in (1, 2):
                other = 2 if self._solo_active_pnum == 1 else 1
                tag = self._player_to_tag.setdefault(other, f"solo_p{other}")
                p = self._player(tag)
                p.counters_spent_count += 1
                if mdc.group("val"):
                    p.counters_spent_total += int(mdc.group("val"))
            return
        msh = L.RE_HAND.match(rest)
        if msh:
            hand_ids = L.parse_id_list(msh.group("ids"))
            pnum = self._match_solo_player_by_hand(hand_ids)
            if pnum is not None:
                self._solo_snapshot_pnum = pnum
                tag = self._player_to_tag.get(pnum) or f"solo_p{pnum}"
                self._player_to_tag.setdefault(pnum, tag)
                p = self._player(tag)
                p.hand_ids = hand_ids
                p.hand_count_known = True
                if p.side == "opp" or pnum == 2:
                    self._opp_has_snapshot = True
            return
        # Board/Trash/Life : utilise le joueur déterminé par le Hand précédent.
        pnum = self._solo_snapshot_pnum
        if pnum is None:
            return
        tag = self._player_to_tag.get(pnum)
        if not tag:
            return
        p = self._player(tag)
        mb = L.RE_BOARD.match(rest)
        if mb:
            p.board_ids = L.parse_id_list(mb.group("ids"))
            if p.side == "opp" or pnum == 2:
                self._opp_has_snapshot = True
            return
        mt = L.RE_TRASH.match(rest)
        if mt:
            p.trash_ids = L.parse_id_list(mt.group("ids"))
            return
        mlf = L.RE_LIFE.match(rest)
        if mlf:
            p.life = int(mlf.group("life"))
            return

    def feed_line(self, raw: str) -> None:
        raw = raw.rstrip("\n")

        # --- Flux RZ1 (peut être préfixé [ReplaySync]) ---
        if L.RE_RZ1.match(raw):
            if "RZ1|HDR" in raw:
                # "RZ1|HDR" N'EST PAS un marqueur fiable de début de partie : le flux
                # [ReplaySync] le ré-émet en cours de partie et au retour menu (resync), et il
                # peut survenir APRÈS le shuffle adverse. On l'ignore pour l'état. La nouvelle
                # partie est détectée sur le 1er "shuffle deck for" qui suit du gameplay (plus bas).
                return
            ev = RZ.parse_rz1_line(raw)
            if ev is not None:
                self._ingest_rz1(ev)
            return

        mc = L.RE_CONNECT.match(raw)
        if mc:
            self.reset_match()
            self.room_code = mc.group("code")
            return
        mv = L.RE_VERSION.match(raw)
        if mv:
            self.version = mv.group("ver")
            return
        if L.RE_DISCONNECT.search(raw):
            self.result = "opponent_disconnect"
            return

        # Une "life card" passe en main = 1 vie perdue par l'un des deux joueurs (signal présent
        # en live, contrairement aux lignes "hit for N damage" réservées aux logs AutoSaved).
        # On compte le TOTAL ; la répartition moi/adversaire se fait côté engine via mes snapshots.
        if "life added to hand" in raw.lower():
            self._life_to_hand += 1
            return

        # Dégât sur un leader : "<Nom> [<id>] hit for N damage" (ligne globale, sans préfixe).
        # On cumule les dégâts par leader (card_id) ; la vie est calculée plus tard par
        # base_life(leader) - dommages (le leader adverse n'est souvent connu qu'après, via
        # inférence d'archétype — d'où le stockage par ID et non par tag).
        mh = L.RE_HIT.search(raw)
        if mh:
            cm = L.CARD_RE.search(raw)
            if cm:
                lid = cm.group(1)
                self._leader_damage[lid] = self._leader_damage.get(lid, 0) + int(mh.group("dmg"))
            return

        # MON deck sélectionné : identité exacte de ma decklist (et donc de mon leader).
        mpd = L.RE_PLAYING_DECK.match(raw)
        if mpd:
            self.my_deck_name = mpd.group("name")
            return

        # Action V3 (attaque/effet) : mémorise l'id — les leaders y apparaissent quand ils
        # agissent, seule trace du leader ADVERSE dans le Player.log live.
        mv3 = L.RE_V3_USING.match(raw)
        if mv3:
            self.v3_action_ids.add(mv3.group("id"))
            return

        # --- Lignes SANS préfixe joueur (spécifiques Player.log) ---
        # "deck filled, do shuffle" n'est PAS un bon point de reset : il concerne MON deck et
        # survient APRÈS le shuffle adverse quand l'adversaire mélange en premier -> le reset y
        # effacerait l'identité adverse déjà vue. On l'ignore comme marqueur.
        msf = L.RE_SHUFFLE_FOR.match(raw)
        if msf:
            # Détection de NOUVELLE partie, robuste à l'ordre des joueurs : le 1er "shuffle deck
            # for" qui suit du GAMEPLAY (deploy/fin de tour) ouvre une nouvelle partie -> reset.
            # Les shuffles groupés du setup (2 joueurs + remulligans) n'ont pas de gameplay entre
            # eux -> pas de reset intempestif, et les DEUX identités sont captées quel que soit
            # l'ordre (adversaire avant ou après moi).
            if self._played:
                self.reset_match()
            self.active = True
            tag = L.clean(msf.group("who"))
            if not tag:
                # Solo vs Self : tag vide. On assigne des tags synthétiques mappés sur les n°
                # joueurs RZ1 (1=me, 2=opp). Pas de shuffle_order (pas de tags réels).
                self.is_solo = True
                self._assign_sides()
                return
            self._last_shuffle_tag = tag
            self._player(tag)
            if tag not in self._shuffle_order:
                self._shuffle_order.append(tag)
            self._assign_sides()      # résout opp dès que son shuffle apparaît
            self._rebuild_opp_zones()
            return
        mhb = L.RE_HAND_BEFORE_MULL_BARE.match(raw)
        if mhb:
            # La main de mulligan loggée sans préfixe appartient au joueur local.
            if self._last_shuffle_tag:
                self.me_tag = self._last_shuffle_tag
                hand = L.parse_id_list(mhb.group("ids"))
                me_p = self._player(self.me_tag)
                me_p.hand_ids = hand
                me_p.hand_count_known = True
                # Corrèle : le n° joueur RZ1 dont les DERNIÈRES pioches == la main = le joueur
                # local (on prend le suffixe pour ignorer les pioches des matchs précédents).
                for pnum, draws in self._rz_draws.items():
                    if hand and draws[-len(hand):] == hand:
                        self._player_to_tag[pnum] = self.me_tag
                        other = 2 if pnum == 1 else 1
                        if self.opp_tag:
                            self._player_to_tag[other] = self.opp_tag
                        break
                self._assign_sides()
                self._update_deck_counts()
            return
        if L.RE_KEEP.match(raw):
            if self.me:
                self.me.mulligan = False
            return

        # --- Solo vs Self : "Hand after Mulligan" (sans préfixe) ---
        # Remplace "Hand before Mulligan" : apparaît après le mulligan, une fois par joueur.
        # On corrèle chaque ligne avec les pioches RZ1 pour identifier le n° joueur.
        mham = L.RE_HAND_AFTER_MULL_BARE.match(raw)
        if mham and self.is_solo:
            hand = L.parse_id_list(mham.group("ids"))
            for pnum, draws in self._rz_draws.items():
                if pnum in self._player_to_tag:
                    continue  # déjà matché
                if hand and len(draws) >= len(hand) and draws[-len(hand):] == hand:
                    tag = f"solo_p{pnum}"
                    self._player_to_tag[pnum] = tag
                    p = self._player(tag)
                    p.hand_ids = hand
                    p.hand_count_known = True
                    break
            self._assign_sides()
            self._update_deck_counts()
            return

        # --- Solo vs Self : "start action phase for player (N)" ---
        # Signal de gameplay + indique le joueur actif (0-indexé -> RZ1 1-indexé).
        msap = L.RE_START_ACTION_PHASE.match(raw)
        if msap and self.is_solo:
            self._played = True
            rz1_pnum = int(msap.group("pnum")) + 1
            self._solo_active_pnum = rz1_pnum
            if rz1_pnum not in self._player_to_tag:
                tag = f"solo_p{rz1_pnum}"
                self._player_to_tag[rz1_pnum] = tag
                self._player(tag)
            return

        m = L.PLAYER_LINE.match(raw)
        if not m:
            return
        who = L.clean(m.group("who"))
        rest = m.group("rest")
        # Solo vs Self : les snapshots ont un préfixe "[]" (tag vide).
        if self.is_solo and L.is_solo_tag(who):
            self._handle_solo_snapshot(rest)
            return
        if not L.is_player_tag(who):  # ignore [You], [ReplaySync], tags Unity...
            return

        # Détection du joueur local.
        if L.RE_HAND_BEFORE_MULL.match(rest):
            self.me_tag = who
            me_p = self._player(who)
            me_p.hand_ids = L.parse_id_list(L.RE_HAND_BEFORE_MULL.match(rest).group("ids"))
            me_p.hand_count_known = True
            self._assign_sides()
            return

        p = self._player(who)

        ml = L.RE_LEADER.match(rest)
        if ml:
            p.leader = ml.group("id")
            p.leader_name = L.clean(ml.group("name"))
            self.card_names.setdefault(ml.group("id"), p.leader_name)
            self._assign_sides()
            return
        if L.RE_MULLIGAN.match(rest):
            p.mulligan = True
            return

        # Snapshots (Hand/Board/Trash/Life). Présents pour les DEUX joueurs dans les logs
        # AutoSaved (post-partie) mais seulement pour le joueur local en live. Quand un
        # snapshot adverse existe, il prime sur la reconstruction par zones RZ1.
        is_opp = self.me_tag is not None and who != self.me_tag
        msh = L.RE_HAND.match(rest)
        if msh:
            p.hand_ids = L.parse_id_list(msh.group("ids"))
            p.hand_count_known = True
            if is_opp:
                self._opp_has_snapshot = True
            return
        mb = L.RE_BOARD.match(rest)
        if mb:
            p.board_ids = L.parse_id_list(mb.group("ids"))
            if is_opp:
                self._opp_has_snapshot = True
            return
        mt = L.RE_TRASH.match(rest)
        if mt:
            p.trash_ids = L.parse_id_list(mt.group("ids"))
            if is_opp:
                self._opp_has_snapshot = True
            return
        mlf = L.RE_LIFE.match(rest)
        if mlf:
            p.life = int(mlf.group("life"))
            return

        # --- Counter défaussé depuis la main ("Discard ... for Counter N") ---
        # Événement PUBLIC : on compte exactement les counters dépensés par joueur. Ce n'est
        # PAS un retrait de board : on l'exclut du bloc retraits ci-dessous pour ne pas
        # confondre avec un exemplaire posé.
        mdc = L.RE_DISCARD_COUNTER.match(rest)
        if mdc:
            p.counters_spent_count += 1
            if mdc.group("val"):
                p.counters_spent_total += int(mdc.group("val"))
        # --- Retraits du board adverse par effet EXPLICITE (KO, Trash, Bottom...) ---
        if not mdc:
            md = L.RE_DESTROYED.match(rest)
            if md:
                # KO attribué au propriétaire (préfixe) : ne retire que du board adverse.
                if who == self.opp_tag:
                    self._opp_removed.add(md.group("id"))
                    self._rebuild_opp_zones()
                return
            mb = L.RE_TRASH_BARE.match(rest)
            if mb:
                # Trash « nu » = remplacement board plein (règle, pas un effet). Attribué au
                # propriétaire ; retrait de board adverse si c'est lui, comme un KO. Le garde de
                # présence évite de retirer une carte qui n'avait jamais été posée.
                if who == self.opp_tag and mb.group("id") in self._opp_board_seen():
                    self._opp_removed.add(mb.group("id"))
                    self._rebuild_opp_zones()
                return
            mr = L.RE_EFFECT_REMOVE.match(rest)
            if mr:
                # Mode strict : on ne retire QUE si l'effet de la carte SOURCE agit réellement sur
                # un Character (bounce/deck/trash d'un perso), d'après son texte (card_effects).
                # Shiryu « Trash 1 card from your hand » -> source sans capacité -> ignoré, même si
                # la cible partage un id avec un exemplaire posé. Filet : présence réelle au board.
                cid, src = mr.group("id"), mr.group("src")
                if "to Hand" in rest:
                    need = "bounce"
                elif "Deck" in rest:        # "to Deck Bottom" / "Top of Deck"
                    need = "deck"
                else:                        # "Trash <cible>"
                    need = "trash_char"
                if need in self._source_caps(src) and cid in self._opp_board_seen():
                    self._opp_removed.add(cid)
                    self._rebuild_opp_zones()
                return

        # --- Modifier Engine : capture des buffs de puissance ---
        # Format : "Source [sid]: Grant/Give Cible [tid] <value> until <expiry>"
        # Le buff est attribué au joueur préfixé (who) ; la cible peut être chez moi ou l'adversaire.
        mg = L.RE_GRANT_POWER.match(rest)
        if mg:
            src_id = mg.group("src")
            tgt_id = mg.group("tgt")
            value = int(mg.group("val"))
            expiry_text = mg.group("expiry")
            applier_side = "me" if who == self.me_tag else "opp"
            expiry = self._parse_expiry(expiry_text, applier_side)
            # Le log émet TOUJOURS un delta additif, jamais une power absolue — y compris pour
            # les cartes « base power becomes X » (preuve : EB04-004 « base power becomes 7000 »
            # est loggé « Grant Sanji 2000 », càd le delta 7000-5000 vers la base de Sanji).
            # On classe donc tout Grant en ADD. L'ancien seuil « >= 5000 -> SET_BASE » était un
            # bug : il écrasait la base avec le delta (un +6000 ponctuel devenait base=6000 au
            # lieu de +6000), sous-évaluant la power et faisant manquer des lethals au solveur.
            mod_type = "ADD"
            mod = Modifier(
                source_id=src_id, mod_type=mod_type, value=value,
                expiry=expiry, applied_at_turn=self._turn,
                applied_by_side=applier_side,
            )
            # La cible peut être chez moi ou l'adversaire. On cherche le joueur qui possède
            # la cible sur son board (ou c'est un leader).
            for p in self.players.values():
                if tgt_id == p.leader or tgt_id in p.board_ids:
                    self._apply_modifier(p, tgt_id, mod)
                    break
            return

        # --- Fin de tour : GC des modificateurs ---
        if L.RE_END_TURN.match(rest):
            self._played = True   # du gameplay a eu lieu -> le prochain shuffle = nouvelle partie
            ending_side = "me" if who == self.me_tag else "opp"
            self._active_side = ending_side
            self._gc_modifiers()
            self._turn += 1
            return

        # Noms de cartes (déploiement/pioche révélée).
        if L.RE_DEPLOY.match(rest):
            self._played = True   # un deploy = gameplay (couvre les parties qui finissent T1)
        for rx in (L.RE_DEPLOY, L.RE_DREW_REVEAL):
            mm = rx.match(rest)
            if mm:
                self.card_names.setdefault(mm.group("id"), L.clean(mm.group("name")))
                break

        if L.RE_CONCEDE.match(rest):
            self.result = f"{'me' if who == self.me_tag else 'opp'}_concede"
            self.active = False
        elif L.RE_WINS.match(rest):
            self.result = f"{'me' if who == self.me_tag else 'opp'}_wins"
            self.active = False

    # --- Export structuré (API) ---
    def _player_dict(self, p: LivePlayer, reveal_all: bool) -> dict:
        name = lambda c: self.card_names.get(c, c) if c else None
        d = {
            "tag": p.tag,
            "side": p.side,
            "leader": p.leader,
            "leader_name": p.leader_name or name(p.leader),
            "life": p.life,
            "deck_remaining": p.deck_remaining,
            "don_on_field": p.don_on_field,
            "board": [{"id": c, "name": name(c)} for c in p.board_ids],
            "trash": [{"id": c, "name": name(c)} for c in p.trash_ids],
            "hand_count": (len(p.hand_ids) if p.hand_count_known
                           else p.hand_count_rz1),
            "hand_count_approx": (not p.hand_count_known
                                  and p.hand_count_rz1 is not None),
            # Counters dépensés (événement public "Discard ... for Counter N") : exact.
            "counters_spent": {"count": p.counters_spent_count,
                               "total": p.counters_spent_total},
            # Modifier Engine : modificateurs actifs par entité (card_id -> liste).
            # Exposé pour que l'UI et le solveur de Lethal puissent afficher la power réelle.
            "modifiers": {
                cid: [
                    {"source": m.source_id, "type": m.mod_type,
                     "value": m.value, "expiry": m.expiry}
                    for m in mods
                ]
                for cid, mods in p.modifiers.items()
            },
        }
        # Fair-play : la main adverse n'est exposée que si reveal_all.
        # En Solo vs Self, les deux joueurs sont locaux -> pas de fair-play.
        if p.side == "me" or reveal_all or self.is_solo:
            ids = p.hand_ids
            # En live, la main adverse n'est pas dans p.hand_ids (pas de snapshot) : on la
            # reconstruit depuis le flux RZ1 (identités piochées). Révélée SEULEMENT en reveal_all.
            if p.side == "opp" and not p.hand_count_known and not self.is_solo:
                ids = self.opp_hand_rz1()
            d["hand"] = [{"id": c, "name": name(c)} for c in ids]
        else:
            d["hand"] = None  # cachée
        return d

    def opp_hand_rz1(self) -> list[str]:
        """Main adverse reconstruite depuis le flux RZ1 (identités piochées moins jouées).

        Information CACHÉE (révélée uniquement en reveal_all). Approximative : les life cards
        prises en dommage entrent en main sans être émises dans RZ1 -> peuvent manquer.
        """
        pnum = self._opp_player_num()
        return list(self._rz_hand_ids.get(pnum, [])) if pnum is not None else []

    def public_revealed(self, side: str) -> set[str]:
        """Cartes d'un joueur connues par information PUBLIQUE (board + trash).

        Sert à la prédiction d'archétype sans utiliser la main cachée (fair-play).
        """
        p = self.players.get(self.opp_tag if side == "opp" else self.me_tag)
        if not p:
            return set()
        return set(p.board_ids) | set(p.trash_ids)

    def to_dict(self, reveal_all: bool = False) -> dict:
        return {
            "active": self.active,
            "room_code": self.room_code,
            "version": self.version,
            "result": self.result,
            "win_reason": self.win_reason,
            "reveal_all": reveal_all,
            "is_solo": self.is_solo,
            # Phase mulligan : partie active, main de départ connue, aucun jeu sur le board
            # encore (self._played passe à True au 1er déploiement). Fenêtre de la décision T0.
            "in_mulligan": self.in_mulligan,
            "me": self._player_dict(self.me, reveal_all) if self.me else None,
            "opp": self._player_dict(self.opp, reveal_all) if self.opp else None,
        }

    @property
    def in_mulligan(self) -> bool:
        """True pendant la fenêtre de mulligan (avant tout jeu sur le board)."""
        return bool(self.active and not self._played
                    and self.me is not None and self.me.hand_ids)

    # --- Rendu ---
    def render(self, reveal_all: bool = False) -> str:
        name = lambda c: self.card_names.get(c, c) if c else "?"
        lines: list[str] = []
        lines.append(f"┌─ Partie en cours {'(salle ' + self.room_code + ')' if self.room_code else ''}")
        if reveal_all:
            lines.append("│ ⚠️  MODE RÉVÉLATION TOTALE — usage hors-ligne / revue uniquement.")

        for label, p in (("MOI", self.me), ("ADVERSAIRE", self.opp)):
            if not p:
                continue
            lead = p.leader_name or name(p.leader) or "?"
            lines.append(f"│ {label} [{lead}]  life={p.life}  deck≈{p.deck_remaining or '?'}")
            board = ", ".join(name(c) for c in p.board_ids) or "—"
            lines.append(f"│   board : {board}")
            is_opp = p.side == "opp"
            if is_opp and not reveal_all:
                # Fair-play : on n'expose que le NOMBRE de cartes en main.
                hc = str(len(p.hand_ids)) if p.hand_count_known else "?"
                lines.append(f"│   main  : {hc} cartes (cachées — mode fair-play)")
            else:
                hand = ", ".join(name(c) for c in p.hand_ids) or "—"
                lines.append(f"│   main  : {hand}")
        if self.result:
            lines.append(f"│ RÉSULTAT : {self.result}")
        lines.append("└" + "─" * 40)
        return "\n".join(lines)
