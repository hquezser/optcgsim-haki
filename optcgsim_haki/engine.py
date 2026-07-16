"""LiveEngine : logique métier temps réel (sans rendering HTML).

Contient tout ce qui est indépendant de la présentation :
  - État live (LiveState) + thread de tailing Player.log
  - Prédiction d'archétype adverse
  - Calcul du payload /state (JSON)
  - Calcul du lethal risk
  - Prédiction des menaces au prochain tour
  - Score de main de départ + matchup stats
  - Accès aux decks .txt (paths, mtime)

L'API FastAPI (api/server.py) utilise LiveEngine directement.
"""

from __future__ import annotations

import os
import pathlib
import threading
import time

from . import card_effects
from . import hypergeometric as hg
from .analytics import Analytics
from .deck_match import load_named_decks, match_deck, match_deck_strict
from .deckstats import effect_keys, parse_deck_file
from .archetype import ArchetypeModel
from .cardmeta import CardMeta, build_card_meta, learn_leader_life_from_logs
from .db.store import Store
from .exact_state import ExactStateSource, default_exact_state_path
from .live import LiveState
from .meta import build_meta_timeline
from .sources import Sources
from .watcher import MatchTimer, _persist_log, _Tailer, replay_current_match
from .formats import FormatDetector


# ---------------------------------------------------------------------------
# Helpers module-level (logique pure, pas de HTML).
# ---------------------------------------------------------------------------

def _forecast_next_plays(expected, cost_by_id, type_by_id, opp_deck, don,
                         seen_counts, top=5, min_prob=10,
                         phase=None, phase_play_rates=None):
    """Prédit les cartes que l'adversaire a probablement en main ET peut jouer au prochain tour.

    P(menace) = P(carte dans le deck) × P(≥1 exemplaire déjà pioché) , filtrée par coût ≤ DON!!.
      - P(dans le deck)   = presence% de l'archétype.
      - P(pioché ≥1)      ≈ 1 − (opp_deck/50)^copies_restantes  (approx. hypergéométrique vérifiée).
      - copies_restantes  = avg_copies − exemplaires déjà vus (board+trash). Si 0 → écarté.
      - coût ≤ DON!! estimé du prochain tour, Leaders exclus.

    Affinage contextuel (P1) : si `phase` et `phase_play_rates` sont fournis, le score est
    pondéré par le play-rate réel de la carte à cette phase de partie (early/mid/late).
    Une carte jouable mais rarement déployée à la phase actuelle voit son score réduit,
    car la probabilité qu'elle soit jouée ce tour-ci est plus faible que sa simple présence
    en main ne le suggère. Le play-rate agit comme un facteur de pertinence stratégique.

    score_final = P(présence en main) × play_rate_phase / 100   (si données disponibles)
    Sans données de play-rate pour la carte/phase, on garde P(présence) inchangé (fallback).
    """
    if not expected or opp_deck is None or don is None or opp_deck <= 0:
        return []
    # Cartes que l'adversaire a déjà piochées (deck de 50 au départ -> 50 - restantes).
    cards_drawn = max(0, 50 - opp_deck)
    out = []
    for c in expected:
        cid = c["card_id"]
        if type_by_id.get(cid) == "Leader":
            continue
        cost = cost_by_id.get(cid)
        if cost is None or cost > don:
            continue
        copies_eff = (c.get("avg_copies") or 1) - seen_counts.get(cid, 0)
        if copies_eff <= 0:
            continue
        # P(≥1 des copies_eff exemplaires déjà piochés) — hypergéométrique EXACTE :
        # tirage de `cards_drawn` cartes sans remise dans le deck de départ (50).
        p = (c["presence"] / 100.0) * hg.p_at_least_one(50, copies_eff, cards_drawn)
        prob = round(100 * p)

        # Affinage contextuel : pondération par play-rate à la phase actuelle.
        play_rate_pct = None
        if phase and phase_play_rates:
            rates = phase_play_rates.get(cid)
            if rates:
                play_rate_pct = rates.get(phase)
        if play_rate_pct is not None:
            # Score pondéré : P(main) × play_rate/100. Une carte à 60% de présence en main
            # mais jouée seulement 5% du temps à cette phase → score = 3% (vs 60% brut).
            score = round(prob * play_rate_pct / 100)
        else:
            # Pas de données de play-rate → on garde le score brut (fallback honnête).
            score = prob

        if score >= min_prob:
            out.append({
                "card_id": cid, "name": c.get("name"), "cost": cost,
                "prob": score,
                "raw_prob": prob if play_rate_pct is not None else None,
                "play_rate": play_rate_pct,
            })
    out.sort(key=lambda x: (x["prob"], -x["cost"]), reverse=True)
    return out[:top]


def _build_draw_odds(remaining: dict[str, int], pool: int, card_meta, top: int = 12,
                     name_of=None) -> dict | None:
    """Odds hypergéométriques de pioche (carte par carte) sur MA prochaine pioche.

    `remaining` : {card_id: copies non encore vues} ; `pool` : taille de l'échantillon non vu
    parmi lequel je vais piocher (deck restant, +vies en mode approx). Renvoie pour chaque carte
    P(la piocher dès la prochaine pioche) = `copies/pool`, plus des probas deck-level (≥1 trigger
    / ≥1 counter pioché). None si rien d'exploitable.
    """
    if pool <= 0:
        return None
    triggers = counters = 0
    per_card: list[dict] = []
    for cid, cnt in remaining.items():
        if cnt <= 0:
            continue
        m = card_meta.get(cid)
        if m and "Trigger" in effect_keys(m.description):
            triggers += cnt
        if m and (m.counter or 0) > 0:
            counters += cnt
        # Nom canonique (deck builder) en priorité ; repli sur le pck.
        nm = name_of(cid) if name_of else None
        if not nm or nm == cid:
            nm = m.name if (m and m.name) else cid
        per_card.append({
            "card_id": cid,
            "name": nm,
            "copies": cnt,
            "p_next": round(100 * hg.p_at_least_one(pool, cnt, 1), 1),
        })
    if not per_card:
        return None
    per_card.sort(key=lambda c: (-c["p_next"], c["name"]))
    return {
        "pool": pool,
        "n_cards": len(per_card),
        "truncated": len(per_card) > top,
        "per_card": per_card[:top],
        "deck_level": {
            "trigger_next": round(100 * hg.p_at_least_one(pool, triggers, 1), 1),
            "counter_next": round(100 * hg.p_at_least_one(pool, counters, 1), 1),
        },
    }


# ---------------------------------------------------------------------------
# Solveur de Lethal — allocation optimale de DON!! + plan d'attaque.
# Inspiré d'OPTCGLab : approche gloutonne par tri décroissant des cibles
# et des attaquants. V1 pure (pas de mots-clés Double Attack/Banish/Rush).
# ---------------------------------------------------------------------------

def _don_cost(attacker_power: int, target_power: int) -> int:
    """DON!! requis pour qu'un attaquant atteigne une puissance cible.
    Coût = max(0, ceil((target - power) / 1000)). Les DON ne peuvent pas être négatifs.
    """
    if target_power <= attacker_power:
        return 0
    return -(-(target_power - attacker_power) // 1000)  # ceil division


def _solve_lethal(
    attackers_power: list[int],
    available_don: int,
    def_leader_power: int,
    def_life: int,
    def_blockers: int,
    def_counter_pool: int,
) -> dict | None:
    """Solveur de lethal : trouve l'allocation optimale de DON!! pour passer les défenses.

    Modèle OPTCG :
    - Chaque attaque gagnante (power > défense) = 1 life perdue ou 1 blocker sacrifié.
    - Les blockers absorbent 1 attaque chacun (redirigent le clash, pas de dommage au leader).
    - Les counters s'ajoutent à la power du leader défenseur pour gagner un clash.
    - L'attaquant alloue ses DON!! (+1000 chacun) à ses attaquants pour atteindre les cibles.

    Algorithme glouton :
    1. Équation A (largeur) : N_requis = life + blockers + 1 (forcer + coup de grâce).
       Si N < N_requis → impossible.
    2. Construire les cibles : (life + blockers) attaques à def_leader_power,
       1 attaque finale à def_leader_power + counter_pool restant.
    3. Trier attaquants et cibles par puissance décroissante (matching optimal).
    4. Calculer le coût DON total. Si ≤ available_don → lethal garanti.

    Retourne :
      - is_lethal: bool
      - don_needed: int (DON total requis)
      - don_available: int
      - attack_plan: [{attacker_power, target_power, don_attached, final_power, role}]
      - reason: str si non lethal
    """
    if def_life is None or def_life <= 0:
        return None
    if def_leader_power is None or def_leader_power <= 0:
        return None
    if not attackers_power:
        return None

    # Filtrer les attaquants avec power connue.
    atks = [p for p in attackers_power if p is not None and p > 0]
    if not atks:
        return None

    # Équation A : check de largeur.
    # N_requis = life (vies à prendre) + blockers (à absorber) + 1 (coup de grâce final).
    # Mais si pas de blockers, on a juste life attaques de forcing + 1 finale.
    # En réalité : chaque vie nécessite 1 attaque gagnante, chaque blocker absorbe 1 attaque,
    # et il faut 1 attaque finale qui passe le counter.
    n_forcing = def_life + def_blockers  # attaques pour vider vies + blockers
    n_required = n_forcing + 1  # + coup de grâce

    if len(atks) < n_required:
        return {
            "is_lethal": False,
            "don_needed": 0,
            "don_available": available_don,
            "attack_plan": [],
            "reason": f"Board trop faible : {len(atks)} attaquants, il en faut {n_required} "
                      f"({def_life} vies + {def_blockers} blockers + 1 coup de grâce).",
        }

    # Construire les cibles (targets) : puissance à atteindre pour chaque attaque.
    # Les (life + blockers) premières attaques doivent battre le leader (def_leader_power).
    # La dernière attaque (coup de grâce) doit battre leader + counter_pool.
    targets = [def_leader_power] * n_forcing
    targets.append(def_leader_power + def_counter_pool)

    # Tri décroissant : associer les plus gros attaquants aux plus grosses cibles.
    targets_sorted = sorted(targets, reverse=True)
    atks_sorted = sorted(atks, reverse=True)

    # On ne garde que les N_required premiers attaquants (les plus puissants).
    atks_used = atks_sorted[:n_required]

    don_needed = 0
    attack_plan = []
    for i in range(n_required):
        a_pow = atks_used[i]
        t_pow = targets_sorted[i]
        don = _don_cost(a_pow, t_pow)
        don_needed += don
        final_pow = a_pow + don * 1000
        # Après tri décroissant, la cible la plus élevée (leader + counter) est en position 0.
        # C'est le coup de grâce. Ensuite les blockers, puis les vies.
        if i == 0 and def_counter_pool > 0:
            role = "coup_de_grace"
        elif i < def_blockers + (1 if def_counter_pool > 0 else 0):
            role = "blocker"
        else:
            role = "life"
        attack_plan.append({
            "attacker_power": a_pow,
            "target_power": t_pow,
            "don_attached": don,
            "final_power": final_pow,
            "role": role,
        })

    if don_needed <= available_don:
        return {
            "is_lethal": True,
            "don_needed": don_needed,
            "don_available": available_don,
            "attack_plan": attack_plan,
            "reason": None,
        }
    else:
        return {
            "is_lethal": False,
            "don_needed": don_needed,
            "don_available": available_don,
            "attack_plan": attack_plan,
            "reason": f"Il manque {don_needed - available_don} DON!! pour un lethal garanti "
                      f"({don_needed} requis, {available_don} disponibles).",
        }


def _compute_lethal(
    atk_leader_power: int | None,
    atk_board: list[tuple[int | None, bool]],  # [(power, dbl_atk), ...]
    def_life: int | None,
    def_leader_power: int | None,
    def_blockers: int,
    def_counter_pool: int,
) -> dict | None:
    """Évalue si l'attaquant peut infliger un lethal (tuer le défenseur ce tour-ci).

    Modèle OPTCG simplifié mais fidèle aux règles de clash :
    - Chaque attaque gagnante (power > défense du clash) = 1 life perdue.
    - Le leader attaque toujours ; chaque personnage du board attaque (conservatif : on
      ignore l'état rested — on ne le traque pas en RZ1). Double Attack = 2 attaques.
    - Défense : blockers (chacun absorbe 1 attaque, redirige le clash, pas de dommage au
      leader quel que soit l'issue) + counters (s'ajoutent à la power du leader pour gagner
      un clash précis — pool partagé).
    - Algorithme glouton : trier les attaques par power décroissante, bloquer les plus
      fortes, puis contrer les suivantes (en dépensant le minimum de counters), compter les
      attaques qui passent → si ≥ life, lethal.

    Retourne None si les données sont insuffisantes (leader inconnu, vie inconnue).
    """
    if def_life is None or def_life <= 0:
        return None
    if atk_leader_power is None:
        return None

    # Construit la liste des puissances d'attaque.
    attacks = [atk_leader_power]
    for power, dbl in atk_board:
        if power is not None:
            attacks.append(power)
            if dbl:
                attacks.append(power)  # Double Attack = 2 attaques

    attacks.sort(reverse=True)  # plus dangereux d'abord

    # Défense gloutonne : blockers d'abord sur les attaques les plus fortes.
    blockers_left = def_blockers
    counter_pool = def_counter_pool
    leader_p = def_leader_power or 0
    lives_lost = 0
    counter_to_hold = 0  # counter TOTAL pour ne perdre aucune vie (blockers déjà déduits)
    for atk in attacks:
        if blockers_left > 0:
            blockers_left -= 1
            continue  # bloqué → pas de dommage au leader
        # Counters requis pour SURVIVRE au clash. Règle OPTCG : l'attaque réussit si
        # power >= défense — l'égalité favorise l'ATTAQUANT. Il faut donc dépasser
        # strictement, par pas de 1000 (granularité des counters).
        needed = 0 if atk < leader_p else ((atk - leader_p) // 1000 + 1) * 1000
        counter_to_hold += needed
        if counter_pool >= needed:
            counter_pool -= needed
            continue  # contré → pas de dommage
        lives_lost += 1  # attaque qui passe → 1 life perdue

    return {
        "can_lethal": lives_lost >= def_life,
        "total_power": sum(attacks),
        "n_attacks": len(attacks),
        "lives_dealt": lives_lost,
        "defender_life": def_life,
        "defender_blockers": def_blockers,
        "defender_counter_pool": def_counter_pool,
        # Besoin exact pour tenir TOUTES les vies ce tour (indépendant du pool fourni).
        "counter_to_hold": counter_to_hold,
    }


# ---------------------------------------------------------------------------
# LiveEngine : logique métier temps réel (sans rendering HTML).
# ---------------------------------------------------------------------------

class LiveEngine:
    """Logique métier temps réel pour OPTCGSim Haki.

    Gère :
      - L'état live (LiveState) + thread de tailing Player.log
      - La prédiction d'archétype adverse
      - Le calcul du payload /state (JSON pur)
      - Le calcul du lethal risk
      - Les prédictions de menaces, score de main, matchup stats
      - L'accès aux decks .txt

    LiveServer (legacy) hérite de cette classe et ajoute le rendering HTML.
    L'API FastAPI utilise LiveEngine directement (pas de HTML).
    """

    def __init__(self, db_path: str, reveal_all: bool = False, poll: float = 0.5):
        self.reveal_all = reveal_all
        self.poll = poll
        self.sources = Sources()
        self.state = LiveState()
        self.lock = threading.Lock()
        # Modèle d'archétype chargé une fois (autonome / thread-safe).
        with Store(db_path) as st:
            self.archetype = ArchetypeModel(st)
        self.db_path = db_path
        # Métadonnées de cartes (pour le Deck Breakdown), avec cache.
        self.card_meta = build_card_meta(self.sources.paths,
                                         pathlib.Path(db_path + ".cardmeta.json"))
        # Repli vie des leaders : les sets récents (ex. OP16) ne sont pas encore dans
        # l'OPBounty.pck -> leur vie manque à card_meta, ce qui casse la vie adverse live +
        # le lethal. On la déduit des logs AutoSaved (« Leader is » + « Life: »). Power leader
        # = 5000 (constante OPTCG) pour alimenter le solveur de Lethal.
        for lid, life in learn_leader_life_from_logs(
                self.sources.paths.autosaved_logs,
                pathlib.Path(db_path + ".leaderlife.json")).items():
            m = self.card_meta.get(lid)
            if m is None:
                self.card_meta[lid] = CardMeta(card_id=lid, life=life,
                                               card_type="Leader", power=5000)
            elif m.life is None:
                m.life = life
        # Timeline des metas (Stats : Meta -> Leader).
        self.meta_timeline = build_meta_timeline(self.sources.paths,
                                                 pathlib.Path(db_path + ".metas.json"))
        self._stop = threading.Event()
        # Caches pour _state_payload (évite de recalculer chaque seconde).
        self._hand_score_key: tuple = ()          # (leader, *hand_ids)
        self._hand_score_val: dict | None = None
        self._matchup_key: tuple = ()             # (me_leader, opp_leader)
        self._matchup_val: dict | None = None
        # Source d'état exact (mod BepInEx). Auto-détection : si le fichier
        # live_exact_state.json existe, on l'utilise en priorité sur le log.
        # Désactivable via OPTCG_EXACT_STATE=0.
        exact_path = default_exact_state_path(self.sources.paths.app_support)
        exact_env = os.environ.get("OPTCG_EXACT_STATE")
        self.exact = ExactStateSource(exact_path)
        self.exact_enabled = exact_env != "0"  # auto-activé si fichier présent
        self._history_val: list = []
        self._history_ts: float = 0.0
        # Cache pour opp_play_rate_by_phase (invalide quand de nouvelles parties sont ingérées).
        self._phase_rates_key: str | None = None
        self._phase_rates_val: dict = {}
        self._phase_rates_ts: float = 0.0

    # --- Helpers DB ---

    @staticmethod
    def _leader_id_by_name(st, name: str) -> str | None:
        # Un nom peut correspondre à plusieurs ids : on prend un leader effectivement joué.
        rows = st.query(
            "SELECT my_leader AS id FROM matches WHERE my_leader IN "
            "(SELECT card_id FROM cards WHERE name=?) LIMIT 1", (name,))
        return rows[0]["id"] if rows else None

    def _get_phase_play_rates(self, opp_leader: str) -> dict:
        """Récupère les play-rates par phase pour un leader adverse, avec cache de 30s.

        Les play-rates ne changent pas à chaque seconde — un cache de 30s suffit pour
        limiter les requêtes SQL tout en restant frais pendant une session de jeu.
        """
        import time as _time
        now = _time.monotonic()
        if (opp_leader == self._phase_rates_key
                and now - self._phase_rates_ts < 30.0):
            return self._phase_rates_val
        try:
            with Store(self.db_path) as st:
                rates = Analytics(st).opp_play_rate_by_phase(opp_leader)
        except Exception:
            rates = {}
        self._phase_rates_key = opp_leader
        self._phase_rates_val = rates
        self._phase_rates_ts = now
        return rates

    # --- Decks (Deck Breakdown live) ---

    def _deck_paths(self) -> list[pathlib.Path]:
        d = self.sources.paths.app_support
        return sorted(d.glob("*.txt")) if d.exists() else []

    def _resolve_deck(self, name: str | None) -> pathlib.Path | None:
        decks = self._deck_paths()
        if not decks:
            return None
        if name:
            for p in decks:
                if name.lower() in p.stem.lower():
                    return p
            return None
        # défaut : le deck le plus récemment modifié (= celui en cours d'édition).
        return max(decks, key=lambda p: p.stat().st_mtime)

    def _deck_mtime(self, name: str | None) -> dict:
        p = self._resolve_deck(name)
        return {"mtime": p.stat().st_mtime if p else None,
                "name": p.stem if p else None}

    # --- Lethal Risk ---

    def _card_combat_stats(self, ids: list[str]):
        """(power, blocker, dbl_atk, counter) par card_id depuis la table cards, ou None."""
        ids = sorted({i for i in ids if i})
        if not ids:
            return None
        try:
            with Store(self.db_path) as st:
                ph = ",".join("?" * len(ids))
                rows = st.query(
                    f"SELECT card_id, power, has_blocker, has_dbl_atk, counter "
                    f"FROM cards WHERE card_id IN ({ph})",
                    tuple(ids),
                )
        except Exception:
            return None
        return (
            {r["card_id"]: r["power"] for r in rows},
            {r["card_id"]: r["has_blocker"] for r in rows},
            {r["card_id"]: r["has_dbl_atk"] for r in rows},
            {r["card_id"]: (r["counter"] or 0) for r in rows},
        )

    def _build_defense_payload(
        self,
        me_hand_ids: list[str], me_board_ids: list[str], me_life: int | None,
        opp_leader: str | None, opp_board_ids: list[str], opp_don: int | None,
        live_state: object | None = None,
    ) -> dict | None:
        """Panneau « défense » : 100 % exact/public, disponible dès le tour 0.

        Contrairement au lethal, n'exige PAS le leader adverse (jamais loggé en live,
        seulement inféré) : mes ressources (main/board/vie = mes snapshots) et le board
        adverse VISIBLE suffisent. `opp_leader_known` dit si la puissance du leader adverse
        est comptée dans opp_power/opp_attacks.
        """
        combat = self._card_combat_stats(
            me_hand_ids + me_board_ids + opp_board_ids
            + ([opp_leader] if opp_leader else []))
        if combat is None:
            return None
        power_by_id, blocker_by_id, dbl_atk_by_id, counter_by_id = combat

        def _pow(cid: str) -> int | None:
            base = power_by_id.get(cid)
            if base is None or live_state is None:
                return base
            return live_state.get_current_power(live_state.opp, cid, base)

        opp_attackers: list[int] = []
        if opp_leader:
            p = _pow(opp_leader)
            if p:
                opp_attackers.append(p)
        for cid in opp_board_ids:
            p = _pow(cid)
            if p:
                opp_attackers.append(p)
                if dbl_atk_by_id.get(cid):
                    opp_attackers.append(p)  # Double Attack = 2 attaques

        return {
            "my_life": me_life,
            "my_blockers": sum(1 for c in me_board_ids if blocker_by_id.get(c)),
            "my_counter_pool": sum(counter_by_id.get(c, 0) for c in me_hand_ids
                                   if counter_by_id.get(c, 0) > 0),
            "opp_attacks": len(opp_attackers) or None,
            "opp_power": sum(opp_attackers) or None,
            "opp_don": opp_don or 0,
            "opp_leader_known": opp_leader is not None,
        }

    def _build_lethal_payload(
        self,
        me_leader: str, opp_leader: str,
        me_board_ids: list[str], opp_board_ids: list[str],
        me_hand_ids: list[str],
        me_life: int | None, opp_life: int | None,
        opp_avg_counter: int | None,
        opp_hand_count: int | None,
        me_don: int | None = None,
        opp_don: int | None = None,
        trigger_risk_pct: int | None = None,
        opp_unknown_cards: int | None = None,
        opp_remaining_triggers: int | None = None,
        live_state: object | None = None,
        opp_leader_inferred: bool = False,
    ) -> dict | None:
        """Construit le payload `lethal` en interrogeant la table cards pour power/blocker/
        dbl_atk/counter, puis en appelant _solve_lethal dans les deux sens.

        Sens 1 — opp peut-il me tuer au prochain tour ? (attaque adverse vs ma défense)
        Sens 2 — puis-je tuer l'adversaire ce tour ? (mon attaque vs sa défense estimée)

        Utilise le solveur _solve_lethal qui alloue optimalement les DON!! et produit
        un plan d'attaque détaillé. La probabilité de lethal intègre le risque de trigger
        adverse (chaque vie retournée peut révéler un trigger qui ruine le plan).

        Si ``live_state`` (un LiveState) est fourni, la puissance des entités est ajustée
        avec les modificateurs temporaires (buffs/debuffs) via ``get_current_power``.
        """
        # Collecte tous les IDs pertinents : leaders + boards + ma main.
        all_ids = sorted(set(
            [me_leader, opp_leader] + me_board_ids + opp_board_ids + me_hand_ids
        ))
        combat = self._card_combat_stats(all_ids)
        if combat is None:
            return None
        power_by_id, blocker_by_id, dbl_atk_by_id, counter_by_id = combat

        # --- Modifier Engine : ajuste la power avec les buffs temporaires ---
        # Si live_state est fourni, on remplace la power statique par la power effective.
        def _pow(cid: str, side: str) -> int | None:
            """Power effective d'une entité, en tenant compte des modificateurs."""
            base = power_by_id.get(cid)
            if base is None:
                return None
            if live_state is None:
                return base
            player = live_state.me if side == "me" else live_state.opp
            return live_state.get_current_power(player, cid, base)

        # --- Sens 1 : opp peut-il me lethal ? ---
        # L'adversaire attaque avec son leader + board. DON adverse = opp_don (sur terrain).
        opp_attackers = []
        opp_leader_pow = _pow(opp_leader, "opp")
        if opp_leader_pow:
            opp_attackers.append(opp_leader_pow)
        for cid in opp_board_ids:
            p = _pow(cid, "opp")
            if p:
                opp_attackers.append(p)
                if dbl_atk_by_id.get(cid):
                    opp_attackers.append(p)  # Double Attack = 2 attaques

        my_blockers = sum(1 for cid in me_board_ids if blocker_by_id.get(cid))
        my_counter_pool = sum(counter_by_id.get(cid, 0) for cid in me_hand_ids if counter_by_id.get(cid, 0) > 0)
        opp_don_available = opp_don or 0

        # _compute_lethal : simulation du combat pour compter les vies à risque (métrique).
        opp_atk_board = [
            (_pow(cid, "opp"), bool(dbl_atk_by_id.get(cid)))
            for cid in opp_board_ids
        ]
        me_leader_pow = _pow(me_leader, "me")
        opp_sim = _compute_lethal(
            atk_leader_power=opp_leader_pow,
            atk_board=opp_atk_board,
            def_life=me_life,
            def_leader_power=me_leader_pow,
            def_blockers=my_blockers,
            def_counter_pool=my_counter_pool,
        )
        # _solve_lethal : solveur d'allocation DON + plan d'attaque.
        opp_lethal = _solve_lethal(
            attackers_power=opp_attackers,
            available_don=opp_don_available,
            def_leader_power=me_leader_pow or 0,
            def_life=me_life or 0,
            def_blockers=my_blockers,
            def_counter_pool=my_counter_pool,
        )

        # --- Sens 2 : puis-je lethal l'adversaire ? ---
        me_attackers = []
        me_leader_pow = _pow(me_leader, "me")
        if me_leader_pow:
            me_attackers.append(me_leader_pow)
        for cid in me_board_ids:
            p = _pow(cid, "me")
            if p:
                me_attackers.append(p)
                if dbl_atk_by_id.get(cid):
                    me_attackers.append(p)  # Double Attack = 2 attaques

        opp_blockers = sum(1 for cid in opp_board_ids if blocker_by_id.get(cid))
        # Estimation du pool de counters adverse : main × avg_counter de l'archétype (inférée).
        opp_counter_est = 0
        if opp_avg_counter and opp_hand_count and opp_hand_count > 0:
            opp_counter_est = opp_avg_counter * opp_hand_count
        # PIRE CAS (décision produit) : chaque carte en main adverse = un counter 2K. C'est la
        # borne fiable — un lethal « garanti » doit passer même contre ça. None si le compte de
        # main adverse est inconnu (on ne peut alors pas garantir). Max counter/carte = 2000.
        opp_hand_n = opp_hand_count if (isinstance(opp_hand_count, int) and opp_hand_count >= 0) else None
        opp_counter_worst = opp_hand_n * 2000 if opp_hand_n is not None else None
        me_don_available = me_don or 0

        # _compute_lethal : simulation pour les vies infligeables.
        me_atk_board = [
            (_pow(cid, "me"), bool(dbl_atk_by_id.get(cid)))
            for cid in me_board_ids
        ]
        opp_leader_pow = _pow(opp_leader, "opp")
        me_sim = _compute_lethal(
            atk_leader_power=me_leader_pow,
            atk_board=me_atk_board,
            def_life=opp_life,
            def_leader_power=opp_leader_pow,
            def_blockers=opp_blockers,
            def_counter_pool=opp_counter_est,
        )
        # _solve_lethal : solveur d'allocation DON + plan d'attaque. Le pool de counters adverse
        # est une ESTIMATION (main cachée) -> on le paramètre pour mesurer la sensibilité.
        def _solve_me(counter_pool: int):
            return _solve_lethal(
                attackers_power=me_attackers,
                available_don=me_don_available,
                def_leader_power=opp_leader_pow or 0,
                def_life=opp_life or 0,
                def_blockers=opp_blockers,
                def_counter_pool=counter_pool,
            )
        me_lethal = _solve_me(opp_counter_est)

        # Seuil de counter ABSOLU : jusqu'à combien de counters adverses le lethal tient-il ?
        # Métrique exacte, indépendante de toute estimation : on balaie depuis 0. « Tu gagnes
        # sauf si l'adversaire a ≥ (seuil + 1000) en counters. » Basé sur le lethal SANS counter
        # (best case) pour découpler du modèle d'estimation.
        me_lethal_base = _solve_me(0)
        me_counter_threshold = None
        if me_lethal_base and me_lethal_base["is_lethal"]:
            pool = 0
            cap = 20000  # borne : au-delà, l'incertitude n'est plus actionnable
            while pool < cap:
                nxt = _solve_me(pool + 1000)
                if not (nxt and nxt["is_lethal"]):
                    break
                pool += 1000
            me_counter_threshold = pool
        # Lethal GARANTI (fiable) : tient même dans le pire cas 2K de la main adverse. C'est
        # l'annonce par défaut demandée ; sinon le lethal reste conditionnel (« tient si ≤ seuil »).
        me_lethal_guaranteed = (me_counter_threshold is not None
                                and opp_counter_worst is not None
                                and me_counter_threshold >= opp_counter_worst)

        # --- Probabilité de lethal (mode probabiliste) ---
        # Intègre le risque de trigger : chaque vie adverse retournée peut révéler un trigger
        # qui ruine le plan (ex: +1000 power, pioche, blocker gratuit).
        # P(pas de trigger sur les N vies) = (1 - trigger_risk_pct/100)^N
        me_lethal_prob = None
        if me_lethal and me_lethal["is_lethal"] and opp_life and opp_life > 0:
            if trigger_risk_pct is not None and trigger_risk_pct > 0:
                # P(lethal réussi) = P(pas de trigger sur toutes les vies prises)
                p_no_trigger = (1 - trigger_risk_pct / 100) ** opp_life
                me_lethal_prob = round(p_no_trigger * 100)
            else:
                me_lethal_prob = 100  # lethal garanti sans trigger risk

        # --- Confiance : un lethal offensif empile des inférences (counters/vie/leader adverses
        # cachés ou déduits). On expose le niveau + les facteurs au lieu d'un binaire trompeur.
        def _me_confidence() -> dict | None:
            if not (me_lethal and me_lethal["is_lethal"]):
                return None
            factors = []
            # Dépendance aux counters (main adverse cachée) : le facteur dominant.
            if opp_hand_count == 0:
                pass  # aucune carte en main -> aucun counter possible (fiable)
            elif opp_hand_count is None:
                factors.append("main adverse inconnue")
            else:
                factors.append(f"counters adverses estimés (~{opp_counter_est} sur {opp_hand_count} cartes)")
            if opp_leader_inferred:
                factors.append("leader adverse déduit")
            if me_lethal_prob is not None and me_lethal_prob < 100:
                factors.append(f"{me_lethal_prob}% après risque de trigger")
            margin = ((me_counter_threshold - opp_counter_est)
                      if me_counter_threshold is not None else None)
            if margin is not None and margin < 2000:
                factors.append("marge de counter faible")
            # Niveau : certain seulement si l'adversaire ne peut PAS counter (main vide) et
            # leader connu. Sinon medium ; rabaissé à low si leader déduit, trigger marqué,
            # ou marge de counter mince.
            certain_counters = (opp_hand_count == 0)
            if certain_counters and not opp_leader_inferred and (me_lethal_prob is None or me_lethal_prob >= 90):
                level = "high"
            elif (opp_leader_inferred or (me_lethal_prob is not None and me_lethal_prob < 50)
                  or (margin is not None and margin < 2000)):
                level = "low"
            else:
                level = "medium"
            return {"level": level, "factors": factors,
                    "counter_threshold": me_counter_threshold}

        # Côté danger (l'adversaire me tue) : plus fiable — ses attaquants sont VISIBLES (board)
        # et mes counters/vie sont connus exactement. Reste l'incertitude d'un rush/buff caché.
        def _opp_confidence() -> dict | None:
            if not (opp_sim and opp_sim["can_lethal"]):
                return None
            factors = ["menaces cachées en main adverse (rush/buff) non comptées"]
            if opp_leader_inferred:
                factors.append("leader adverse déduit")
            level = "low" if opp_leader_inferred else "medium"
            return {"level": level, "factors": factors}

        if not opp_lethal and not me_lethal and not opp_sim and not me_sim:
            return None
        return {
            # opp_can_lethal : utilise la simulation (_compute_lethal) qui modélise
            # la distribution optimale des counters par le défenseur.
            "opp_can_lethal": opp_sim["can_lethal"] if opp_sim else False,
            "opp_power": sum(opp_attackers) if opp_attackers else None,
            "opp_attacks": len(opp_attackers) if opp_attackers else None,
            "lives_at_risk": opp_sim["lives_dealt"] if opp_sim else 0,
            "counter_to_hold": opp_sim.get("counter_to_hold") if opp_sim else None,
            "my_life": me_life,
            "my_blockers": my_blockers,
            "my_counter_pool": my_counter_pool,
            # me_can_lethal : utilise le solveur (_solve_lethal) qui optimise
            # l'allocation de DON!! par l'attaquant + plan d'attaque.
            "me_can_lethal": me_lethal["is_lethal"] if me_lethal else False,
            "me_power": sum(me_attackers) if me_attackers else None,
            "me_attacks": len(me_attackers) if me_attackers else None,
            "lives_i_can_deal": me_sim["lives_dealt"] if me_sim else 0,
            "opp_life": opp_life,
            "opp_blockers": opp_blockers,
            "opp_counter_est": opp_counter_est,
            # Modèle pire-cas (produit) : counter adverse maximal (main × 2K) + lethal garanti.
            "opp_counter_worst": opp_counter_worst,
            "opp_hand_count": opp_hand_count,
            "me_lethal_guaranteed": me_lethal_guaranteed,
            # --- Nouveaux champs : solveur + probabilité + confiance ---
            "me_lethal_prob": me_lethal_prob,
            "me_counter_threshold": me_counter_threshold,
            "me_lethal_confidence": _me_confidence(),
            "opp_lethal_confidence": _opp_confidence(),
            "me_don_available": me_don_available,
            "me_don_needed": me_lethal["don_needed"] if me_lethal else None,
            "me_attack_plan": me_lethal["attack_plan"] if me_lethal else [],
            "me_lethal_reason": me_lethal["reason"] if me_lethal else None,
            "opp_don_available": opp_don_available,
            "opp_don_needed": opp_lethal["don_needed"] if opp_lethal else None,
            "opp_attack_plan": opp_lethal["attack_plan"] if opp_lethal else [],
            "opp_lethal_reason": opp_lethal["reason"] if opp_lethal else None,
            "trigger_risk_pct": trigger_risk_pct,
        }

    # --- State payload (core) ---

    def _named_decks(self):
        """Decks nommés du joueur (.txt du jeu), chargés une fois et mis en cache."""
        decks = getattr(self, "_named_decks_cache", None)
        if decks is None:
            decks = load_named_decks(self.sources)
            self._named_decks_cache = decks
        return decks

    def _my_deck_leader(self) -> str | None:
        """Leader EXACT de mon deck, via la ligne 'Playing with deck: <name>' du Player.log
        (le fichier <app_support>/<name>.txt est ma decklist)."""
        me = self.state.me
        seen = (set(me.hand_ids) | set(me.board_ids) | set(me.trash_ids)) if me else set()
        d = self._logged_named_deck(seen)
        return d.leader if d else None

    def _logged_named_deck(self, my_seen: set[str]):
        """Deck nommé désigné par 'Playing with deck', SI cohérent avec mes cartes vues.

        La ligne peut décrire une sélection PRÉCÉDENTE (le log survit entre parties —
        constaté en Solo vs Self : deck Sanji loggé, partie Bonney/Ace). On ne fait foi
        que si aucune carte vue de mon camp ne contredit la decklist."""
        name = self.state.my_deck_name
        if not name:
            return None
        for d in self._named_decks():
            if d.name == name:
                extra = {c for c in my_seen if c and c != d.leader} - d.cards
                return d if not extra else None
        return None

    def _observed_opp_leader(self, me_leader: str | None) -> str | None:
        """Leader adverse OBSERVÉ : id de type leader (CardMeta.life non nul) vu dans les
        actions V3 ('Start Using V3 Action'), différent du mien. Exact et public. None si
        aucun ou ambigu (>1 candidat — ne devrait pas arriver dans une partie).

        GARDE : exige que MON leader soit connu. Sinon impossible d'exclure le mien — bug
        constaté sur un vrai log online (session restaurée sans ligne de deck) : MON leader,
        seul id de type leader dans mes actions V3, était attribué à l'ADVERSAIRE."""
        if not me_leader:
            return None
        cands = set()
        for cid in self.state.v3_action_ids:
            if cid == me_leader:
                continue
            meta = self.card_meta.get(cid)
            if meta is not None and meta.life is not None:
                cands.add(cid)
        return cands.pop() if len(cands) == 1 else None

    def _draw_odds_log(self, me, leader: str, deck_remaining: int, life) -> dict | None:
        """Odds de pioche en mode LOG : decklist devinée + pool non vu (deck + vies).

        Les copies non vues d'une carte sont réparties (face cachée) entre le deck et les vies,
        toutes issues du deck. Par échangeabilité, ma prochaine pioche est une carte uniforme
        parmi ce pool non vu `U = deck_remaining + vies_restantes`. Approximatif (decklist
        rapprochée par overlap, comme le watcher) -> None si le deck n'est pas identifiable.
        """
        from collections import Counter
        hand = list(me.hand_ids) if me.hand_count_known else []
        seen = Counter(hand) + Counter(me.board_ids) + Counter(me.trash_ids)
        # Ma decklist LOGGÉE ("Playing with deck") prime : identité exacte, fiable dès T0 —
        # sous garde de cohérence (la ligne peut décrire une sélection précédente).
        logged_deck = self._logged_named_deck(set(seen))
        if logged_deck is not None:
            name, logged = logged_deck.name, logged_deck.name
        else:
            name = match_deck(set(seen) | {leader}, leader, self._named_decks(), full=False)
            logged = None
        if not name:
            return None
        path = self.sources.paths.app_support / f"{name}.txt"
        if not path.exists():
            return None
        decklist = parse_deck_file(path).cards  # {card_id: qty}, hors leader
        remaining = {cid: qty - seen.get(cid, 0)
                     for cid, qty in decklist.items() if qty - seen.get(cid, 0) > 0}
        # Vies restantes : compteur de vie connu, sinon vie de base du leader, sinon 5.
        if isinstance(life, int) and life > 0:
            life_n = life
        else:
            lm = self.card_meta.get(leader)
            life_n = lm.life if (lm and isinstance(lm.life, int) and lm.life > 0) else 5
        odds = _build_draw_odds(remaining, deck_remaining + life_n, self.card_meta,
                                name_of=self.archetype._name)
        if odds is not None:
            odds["mode"] = "approx"
            odds["deck_name"] = name
            # FIABLE si la decklist est loggée ("Playing with deck") ou identifiée strictement
            # (toutes mes cartes vues n'existent que dans ce deck sauvegardé).
            odds["reliable"] = bool(logged) or (
                match_deck_strict(set(seen) | {leader}, leader,
                                  self._named_decks()) == name)
        return odds

    def _state_payload(self) -> dict:
        # Priorité : état exact (mod BepInEx) si disponible, sinon repli sur le log.
        if self.exact_enabled and self.exact.available() and self.exact.is_fresh():
            raw = self.exact.read()
            if raw:
                payload = self.exact.to_payload(raw, self.reveal_all)
                return self._apply_feature_gating(
                    self._augment_exact_payload(payload), exact=True)
        return self._apply_feature_gating(
            self._state_payload_from_log(), exact=False)

    def _apply_feature_gating(self, payload: dict, exact: bool) -> dict:
        """Masque les champs approximatifs selon les feature flags.

        En mode EXACT, les panneaux live sont fiables -> forcés ON.
        En mode LOG (inférence), on ne garde que ce que les flags autorisent.
        """
        from .features import all_features
        feats = all_features()
        # En mode EXACT, les panneaux live sont fiables -> forcés ON.
        if exact:
            for k in ("live_opp_hand", "live_opp_life", "live_lethal",
                      "live_menaces", "live_trigger_risk", "live_archetype",
                      "live_draw_odds", "live_defense", "live_opp_seen", "live_opp_known_hand"):
                feats[k] = True
        payload["features"] = feats
        # Retirer les champs approximatifs dont le flag est OFF. La défense (fiable, construite
        # par _build_defense_payload dans les deux chemins) n'est retirée que sur opt-out.
        if not feats.get("live_defense"):
            payload.pop("defense", None)
        if not feats.get("live_opp_seen"):
            payload.pop("opp_seen", None)
        if not feats.get("live_opp_known_hand"):
            payload.pop("opp_known_hand", None)
        if not feats["live_lethal"]:
            payload.pop("lethal", None)
        if not feats["live_menaces"]:
            payload.pop("next_plays", None)
            payload.pop("next_plays_phase", None)
            payload.pop("next_plays_turn", None)
        if not feats["live_trigger_risk"]:
            payload.pop("trigger_risk", None)
        if not feats["live_archetype"]:
            payload.pop("archetype", None)
        if not feats["live_draw_odds"]:
            # Exception fiable : odds sur MON deck identifié STRICTEMENT (ou mode exact).
            do = payload.get("draw_odds")
            if not (do and do.get("reliable")):
                payload.pop("draw_odds", None)
        if not feats["live_opp_hand"] and payload.get("opp"):
            payload["opp"]["hand"] = None
        if not feats["live_opp_life"] and payload.get("opp"):
            payload["opp"]["life"] = None
        return payload

    def _augment_exact_payload(self, payload: dict) -> dict:
        """Enrichit le payload exact avec lethal, archétype, menaces, etc.

        Les données de base (leader, vie, board, main, deck) viennent du mod et sont EXACTES.
        On réutilise les modules existants (archétype, lethal, hand_score, matchup_stats)
        sur ces données exactes — plus besoin d'inférence.
        """
        me = payload.get("me")
        opp = payload.get("opp")
        if not me or not opp:
            return payload

        # Odds de pioche EXACTES : le mod fournit MON deck restant (ordonné, mais on traite
        # l'ordre comme inconnu pour des probas franches). On retire deck_ids du payload final
        # (gros, inutile côté UI une fois les odds calculées).
        me_deck_ids = me.pop("deck_ids", None)
        if me_deck_ids:
            from collections import Counter
            odds = _build_draw_odds(dict(Counter(me_deck_ids)), len(me_deck_ids), self.card_meta,
                                    name_of=self.archetype._name)
            if odds is not None:
                odds["mode"] = "exact"
                odds["reliable"] = True  # decklist connue du mod
                payload["draw_odds"] = odds

        me_leader = me.get("leader")
        opp_leader = opp.get("leader")
        me_hand_ids = [c["id"] for c in (me.get("hand") or []) if c.get("id")]
        me_board_ids = [c["id"] for c in (me.get("board") or []) if c.get("id")]
        opp_board_ids = [c["id"] for c in (opp.get("board") or []) if c.get("id")]

        # Noms des leaders via card_meta.
        if me_leader:
            me["leader_name"] = me.get("leader_name") or self.archetype._name(me_leader)
            meta = self.card_meta.get(me_leader)
            me["leader_meta_missing"] = meta is None or meta.life is None
        if opp_leader:
            opp["leader_name"] = opp.get("leader_name") or self.archetype._name(opp_leader)
            meta = self.card_meta.get(opp_leader)
            opp["leader_meta_missing"] = meta is None or meta.life is None

        # Archétype adverse (prédiction sur cartes publiques = board + trash).
        revealed = sorted(set(opp_board_ids) | set(c["id"] for c in (opp.get("trash") or [])))
        pred = None
        if opp_leader:
            pred = self.archetype.predict(opp_leader, set(revealed))
            if pred:
                payload["archetype"] = {
                    "leader_name": pred.leader_name,
                    "leader_inferred": False,  # leader exact, pas inféré
                    "n_historical": pred.n_historical,
                    "nearest_overlap": pred.nearest_overlap,
                    "expected_cards": pred.expected_cards,
                    "revealed": revealed,
                }

        # Lethal : utilise l'état exact (vie, power, counters, DON).
        me_life = me.get("life")
        opp_life = opp.get("life")
        me_don = me.get("don_on_field")
        opp_don = opp.get("don_on_field")
        if me_leader and opp_leader:
            tr = payload.get("trigger_risk") or {}
            lethal = self._build_lethal_payload(
                me_leader, opp_leader,
                me_board_ids, opp_board_ids,
                me_hand_ids,
                me_life, opp_life,
                (payload.get("counter_analysis") or {}).get("avg_counter"),
                opp.get("hand_count"),
                me_don=me_don,
                opp_don=opp_don,
                trigger_risk_pct=tr.get("pct"),
                opp_unknown_cards=tr.get("unknown"),
                opp_remaining_triggers=tr.get("remaining"),
                live_state=None,  # pas de LiveState pour les modifiers (état exact direct)
            )
            if lethal:
                payload["lethal"] = lethal

        # Défense (fiable) : ne dépend pas du couple de leaders, contrairement au lethal.
        defense = self._build_defense_payload(
            me_hand_ids, me_board_ids, me_life,
            opp_leader, opp_board_ids, opp_don)
        if defense:
            self._merge_defense_sim(defense, payload.get("lethal"))
            payload["defense"] = defense

        return payload

    @staticmethod
    def _merge_defense_sim(defense: dict, lethal: dict | None) -> None:
        """Enrichit la défense avec la simulation complète quand le lethal a pu être calculé
        (leaders connus) : vies à risque et alerte lethal-au-board."""
        if lethal:
            defense["lives_at_risk"] = lethal.get("lives_at_risk", 0)
            defense["opp_can_lethal"] = lethal.get("opp_can_lethal", False)
            defense["counter_to_hold"] = lethal.get("counter_to_hold")

    def _state_payload_from_log(self) -> dict:
        """Payload reconstruit depuis Player.log (comportement historique)."""
        import time as _time
        with self.lock:
            payload = self.state.to_dict(self.reveal_all)
            opp = self.state.opp
            me = self.state.me
            revealed = sorted(self.state.public_revealed("opp")) if opp else []
            opp_leader = opp.leader if opp else None
            opp_board_ids = list(opp.board_ids) if opp else []
            opp_life = opp.life if opp else None
            opp_deck = opp.deck_remaining if opp else None
            opp_don = opp.don_on_field if opp else None
            me_leader = me.leader if me else None
            me_deck = me.deck_remaining if me else None
            me_don = me.don_on_field if me else None
            me_hand_ids = list(me.hand_ids) if (me and me.hand_count_known) else []
            me_cards = set(self.state.public_revealed("me")) | set(me_hand_ids) if me else set()
        # --- Leaders : OBSERVATION exacte d'abord, inférence en dernier recours. ---
        # MON leader : "Playing with deck: <name>" (Player.log) -> decklist .txt -> leader.
        # Exact, pas une inférence.
        me_inferred = False
        if not me_leader:
            me_leader = self._my_deck_leader()
        # Secours EXACT (pas de ligne de deck, ex. vieux log sans "Load LUD") : identification
        # stricte sans leader connu — si toutes mes cartes vues (≥5, même seuil que
        # match_deck_strict) n'existent que dans UN deck sauvegardé, son leader est le mien.
        if not me_leader and len({c for c in me_cards if c}) >= 5:
            seen = {c for c in me_cards if c}
            hits = [dk for dk in self._named_decks()
                    if dk.cards and (seen - {dk.leader}) <= dk.cards]
            if len(hits) == 1:
                me_leader = hits[0].leader
        # Leader ADVERSE : il apparaît dans "Start Using V3 Action [...]" quand il attaque ou
        # active son effet. Un id de type leader (CardMeta.life non nul) ≠ le mien = observé
        # exactement — prime sur l'inférence d'archétype (qui peut se tromper, cf. Luffy vs Ace).
        inferred = False
        if not opp_leader:
            opp_leader = self._observed_opp_leader(me_leader)
        # Dernier recours : inférence depuis les cartes publiques vues (marquée -> « ≈ » UI).
        if not opp_leader and revealed:
            opp_leader, score = self.archetype.infer_leader(set(revealed))
            inferred = opp_leader is not None and score >= 0.3
            if not inferred:
                opp_leader = None
        if not me_leader and me_cards:
            ml, msc = self.archetype.infer_leader(me_cards)
            if ml and msc >= 0.3:
                me_leader = ml
                me_inferred = True
        pred = None
        if opp_leader:
            pred = self.archetype.predict(opp_leader, set(revealed))
            if pred:
                payload["archetype"] = {
                    "leader_name": pred.leader_name,
                    "leader_inferred": inferred,
                    "n_historical": pred.n_historical,
                    "nearest_overlap": pred.nearest_overlap,
                    "expected_cards": pred.expected_cards,
                    "revealed": revealed,
                }
        # Renseigne id + nom des leaders dans le payload. En live, Player.log ne loggue pas
        # "Leader is" : sans ça, payload[side]["leader"] resterait None alors qu'on connaît
        # (ou déduit) le leader -> en-têtes "MOI — ?", image/lien leader cassés, contrat /state
        # incohérent. On marque `leader_inferred` (déduit vs loggé) et `leader_meta_missing`
        # (carte absente du .pck : set trop récent -> vie/lethal indisponibles, pour l'UI).
        def _set_leader(side_key: str, leader_id: str | None,
                        name: str | None, was_inferred: bool) -> None:
            pl = payload.get(side_key)
            if not leader_id or pl is None:
                return
            pl["leader"] = pl.get("leader") or leader_id
            pl["leader_name"] = (pl.get("leader_name") or name
                                 or self.archetype._name(leader_id))
            pl["leader_inferred"] = was_inferred
            meta = self.card_meta.get(leader_id)
            pl["leader_meta_missing"] = meta is None or meta.life is None

        _set_leader("opp", opp_leader, pred.leader_name if pred else None, inferred)
        _set_leader("me", me_leader, None, me_inferred)

        # Vie en live : Player.log n'écrit pas de snapshot adverse (Life:/Hand:/Board:), donc
        # opp.life est None. On la reconstruit = vie de base du leader (CardMeta.life) - dégâts
        # cumulés sur ce leader (lignes "hit for N damage", suivies dans LiveState par card_id).
        # Garde-fou : vie négative -> None (on ne devine pas). En mode AutoSaved, le snapshot
        # texte prime (opp.life déjà renseigné) -> on n'écrase pas.
        # Pertes de vies ADVERSES : source la plus informée entre les lignes "hit for"
        # (AutoSaved, absentes en live) et la dérivation live des "life added to hand"
        # (total − MES pertes, connues par snapshot). Sert à la vie ET au compte de main
        # (chaque vie perdue = 1 carte entrée en main, non émise dans le flux RZ1).
        opp_lives_lost = 0
        if opp_leader:
            mm = self.card_meta.get(me_leader) if me_leader else None
            my_life_v = (payload.get("me") or {}).get("life")
            my_lost = (max(0, mm.life - my_life_v)
                       if (mm and mm.life is not None and my_life_v is not None) else 0)
            opp_lives_lost = max(self.state.leader_damage(opp_leader),
                                 max(0, self.state._life_to_hand - my_lost))

        def _apply_life(side_key: str, leader: str | None) -> None:
            if not leader or payload.get(side_key) is None:
                return
            if payload[side_key].get("life") is not None:
                return  # snapshot texte (AutoSaved) -> fait foi
            meta = self.card_meta.get(leader)
            if not meta or meta.life is None:
                return
            damage = (opp_lives_lost if side_key == "opp"
                      else self.state.leader_damage(leader))
            life = meta.life - damage
            payload[side_key]["life"] = life if life >= 0 else None

        _apply_life("opp", opp_leader)
        _apply_life("me", me_leader)

        # Compte de main adverse en live : Player.log n'a pas de snapshot "Hand:" adverse.
        # Net RZ1 (draws/plays/counters) + correction des life→main via opp_lives_lost.
        # BUG CORRIGÉ (constaté en partie réelle) : l'ancienne correction utilisait
        # leader_damage ("hit for", TOUJOURS 0 en live) -> main sous-comptée du nombre de
        # vies prises -> pire cas de counter sous-estimé -> « Lethal GARANTI » non fiable.
        # Approximatif (≈) : quelques effets rares peuvent encore induire ±1-2.
        # Garde-fou : résultat négatif -> None (on ne devine pas).
        opp_p = payload.get("opp")
        if (opp_p is not None and opp_p.get("hand_count_approx")
                and opp_leader is not None):
            net = self.state.opp.hand_count_rz1 if self.state.opp else None
            if net is not None:
                corrected = net + opp_lives_lost
                opp_p["hand_count"] = corrected if corrected >= 0 else None
                if opp_p["hand_count"] is None:
                    opp_p["hand_count_approx"] = False

        # Reveal-all : la main adverse reconstruite depuis RZ1 (identités piochées) est exacte
        # tant qu'il n'y a que pioches/plays, mais DÉRIVE dès qu'un effet manipule la main
        # (prendre une life en main, mettre une carte sur le deck, tutor, défausse par effet) —
        # ces mouvements sont en texte seul, souvent SANS identité. On ne peut donc pas garantir
        # l'exactitude. On réconcilie au compte de main fiable (pad de cartes inconnues "?" si
        # sous-compté) et on marque la main approximative pour ne pas induire en erreur.
        if (self.reveal_all and opp_p is not None and self.state.opp is not None
                and not self.state.opp.hand_count_known):
            known = opp_p.get("hand") or []
            count = opp_p.get("hand_count")
            if isinstance(count, int) and count > len(known):
                known = known + [{"id": None, "name": "?"}] * (count - len(known))
            opp_p["hand"] = known
            opp_p["hand_approx"] = True

        # DON!! au T+1 = DON sur le terrain + 2 (capped 10).
        # Source fiable : flux RZ1 (action 4 = placement depuis le DON-deck, DON sur terrain =
        # 10 - restants). Repli sur le proxy "44 - deck" si le flux RZ1 n'a pas encore émis de
        # placement Don (début de partie ou log sans RZ1) — proxy faussé par les pioches
        # supplémentaires mais reste une borne haute acceptable.
        if opp_don is not None:
            payload["opp_don_est"] = min(10, opp_don + 2)
        elif opp_deck is not None:
            payload["opp_don_est"] = min(10, max(0, 44 - opp_deck) * 2 + 2)
        if me_don is not None:
            payload["me_don_est"] = min(10, me_don + 2)
        elif me_deck is not None:
            payload["me_don_est"] = min(10, max(0, 44 - me_deck) * 2 + 2)

        # Counter analysis : +2000 counter cards in opp trash + defense estimate from archetype.
        opp_trash_ids = list(opp.trash_ids) if opp else []
        arch_ids = [c["card_id"] for c in (pred.expected_cards if pred else [])]
        all_ids = list(set(opp_trash_ids + arch_ids))
        if all_ids:
            try:
                with Store(self.db_path) as st:
                    ph = ",".join("?" * len(all_ids))
                    rows = st.query(
                        f"SELECT card_id, counter, has_trigger, cost, card_type "
                        f"FROM cards WHERE card_id IN ({ph})",
                        tuple(all_ids),
                    )
                counter_by_id = {r["card_id"]: (r["counter"] or 0) for r in rows}
                trigger_by_id = {r["card_id"]: r["has_trigger"] for r in rows}
                cost_by_id    = {r["card_id"]: r["cost"] for r in rows}
                type_by_id    = {r["card_id"]: r["card_type"] for r in rows}
            except Exception:
                counter_by_id = {}
            plus2k_in_trash = sum(
                1 for cid in opp_trash_ids if counter_by_id.get(cid, 0) >= 2000
            )
            plus2k_expected = None
            avg_counter = None
            if pred and pred.expected_cards:
                plus2k_expected = sum(
                    round(c["avg_copies"] * c["presence"] / 100)
                    for c in pred.expected_cards
                    if counter_by_id.get(c["card_id"], 0) >= 2000
                )
                total_weighted_ctr = sum(
                    counter_by_id.get(c["card_id"], 0) * c["avg_copies"] * c["presence"] / 100
                    for c in pred.expected_cards
                )
                total_weighted_cop = sum(
                    c["avg_copies"] * c["presence"] / 100 for c in pred.expected_cards
                )
                if total_weighted_cop:
                    avg_counter = round(total_weighted_ctr / total_weighted_cop)
            payload["counter_analysis"] = {
                "plus2k_in_trash": plus2k_in_trash,
                "plus2k_expected": plus2k_expected,
                "avg_counter": avg_counter,
            }

            # Enrich archetype cards with cost/type for the DON!! filter.
            if payload.get("archetype") and pred:
                payload["archetype"]["expected_cards"] = [
                    {**c,
                     "cost":      cost_by_id.get(c["card_id"]),
                     "card_type": type_by_id.get(c["card_id"])}
                    for c in pred.expected_cards
                ]

            # Trigger probability : P(la prochaine life flip soit un trigger).
            # Les life cards sont un sous-ensemble ALÉATOIRE du deck (posées du dessus au setup) :
            # P ≈ (triggers encore non vus) / (cartes encore non vues). Le pool non-vu = 50 - vues
            # (deck + main + life), PAS seulement deck+life — sinon on gonfle le % (bug "100%").
            revealed_ids = list(set(opp_trash_ids) | set(opp_board_ids))
            revealed_triggers = sum(1 for cid in revealed_ids if trigger_by_id.get(cid) == 1)
            if pred and pred.expected_cards:
                total_triggers = sum(
                    round(c["avg_copies"] * c["presence"] / 100)
                    for c in pred.expected_cards
                    if trigger_by_id.get(c["card_id"]) == 1
                )
                remaining = max(0, total_triggers - revealed_triggers)
                pool = max(0, 50 - len(revealed_ids))   # cartes encore non vues
                if pool > 0:
                    payload["trigger_risk"] = {
                        "pct": min(100, round(100 * remaining / pool)),
                        "remaining": remaining,
                        "total_expected": total_triggers,
                        "revealed": revealed_triggers,
                        "unknown": pool,
                    }

            # Menaces probables au prochain tour (modèle proba : présence × P(pioché) × coût≤DON).
            # Affinage contextuel P1 : pondération par le play-rate réel à la phase actuelle.
            if pred and pred.expected_cards:
                seen_counts: dict[str, int] = {}
                for cid in (opp_board_ids + opp_trash_ids):
                    seen_counts[cid] = seen_counts.get(cid, 0) + 1

                # Phase actuelle (early/mid/late) déduite du DON adverse sur le terrain.
                # Proxy : au tour T, le joueur a T+1 DON. opp_don = DON actuel → tour ≈ opp_don - 1.
                # Si opp_don inconnu, on utilise opp_don_est (T+1) → tour ≈ opp_don_est - 3.
                current_turn = None
                if opp_don is not None:
                    current_turn = opp_don - 1
                elif payload.get("opp_don_est") is not None:
                    current_turn = payload["opp_don_est"] - 3
                if current_turn is not None and current_turn < 1:
                    current_turn = 1
                phase = ("early" if (current_turn or 1) <= 3
                         else "mid" if (current_turn or 1) <= 6
                         else "late")

                # Play-rate adverse par phase pour ce leader (cacheé pour éviter les re-requêtes).
                phase_play_rates = self._get_phase_play_rates(opp_leader)

                forecast = _forecast_next_plays(
                    pred.expected_cards, cost_by_id, type_by_id,
                    opp_deck, payload.get("opp_don_est"), seen_counts,
                    phase=phase, phase_play_rates=phase_play_rates,
                )
                if forecast:
                    payload["next_plays"] = forecast
                    payload["next_plays_phase"] = phase
                    payload["next_plays_turn"] = current_turn

        # --- Lethal Risk : l'adversaire peut-il me tuer au prochain tour ? Puis-je le tuer ?
        # Solveur glouton : allocation optimale de DON!! + plan d'attaque détaillé.
        # Conservatif : on suppose tous les personnages du board aptes à attaquer
        # (l'état rested n'est pas traqué en RZ1).
        me_p = payload.get("me")
        opp_p = payload.get("opp")
        if me_p and opp_p and me_leader and opp_leader:
            tr = payload.get("trigger_risk") or {}
            lethal = self._build_lethal_payload(
                me_leader, opp_leader,
                list(me.board_ids) if me else [],
                list(opp.board_ids) if opp else [],
                list(me_hand_ids),
                me_p.get("life"), opp_p.get("life"),
                (payload.get("counter_analysis") or {}).get("avg_counter"),
                opp_p.get("hand_count"),
                me_don=me_don,
                opp_don=opp_don,
                trigger_risk_pct=tr.get("pct"),
                opp_unknown_cards=tr.get("unknown"),
                opp_remaining_triggers=tr.get("remaining"),
                live_state=self.state,
                opp_leader_inferred=inferred,
            )
            if lethal:
                payload["lethal"] = lethal

        # Défense (fiable) : dès que MON état existe — le leader adverse n'est PAS requis
        # (jamais loggé en live, seulement inféré ; la garde du lethal ci-dessus le prouve).
        if me_p:
            defense = self._build_defense_payload(
                list(me_hand_ids), list(me.board_ids) if me else [],
                me_p.get("life"),
                opp_leader, list(opp.board_ids) if opp else [], opp_don,
                live_state=self.state)
            if defense:
                self._merge_defense_sim(defense, payload.get("lethal"))
                payload["defense"] = defense

        # Exemplaires adverses vus (« 2/4 ») : comptage exact d'événements publics (cartes
        # jouées depuis la main adverse, suivi RZ1). Fiable — aucune inférence.
        played = self.state.opp_played_counts()
        if played:
            payload["opp_seen"] = [
                {"card_id": cid, "name": self.archetype._name(cid), "count": n}
                for cid, n in sorted(played.items(), key=lambda kv: (-kv[1], kv[0]))
            ]

        # Cartes CONNUES en main adverse via révélation publique ("Reveal and Draw") : borne
        # basse exacte de sa main. Fiable/public — jamais la main cachée reconstruite.
        known = self.state.opp_known_hand()
        if known:
            payload["opp_known_hand"] = [
                {"card_id": cid, "name": self.archetype._name(cid), "count": n}
                for cid, n in sorted(known.items(), key=lambda kv: (-kv[1], kv[0]))
            ]

        # A — Score de la main de départ (recalcul uniquement si la main change).
        # Modèle v2 : seuils relatifs (vs moyenne du deck) + Curve Penalty + Dead-in-Hand.
        if me_leader and me_hand_ids:
            hkey = (me_leader,) + tuple(me_hand_ids)
            if hkey != self._hand_score_key:
                try:
                    with Store(self.db_path) as st:
                        reco = Analytics(st).mulligan_reco(me_leader, meta=None)
                        # Récupère les coûts des cartes pour le Curve Penalty.
                        ph = ",".join("?" * len(set(me_hand_ids)))
                        cost_rows = st.query(
                            f"SELECT card_id, cost FROM cards WHERE card_id IN ({ph})",
                            tuple(set(me_hand_ids)),
                        )
                        card_costs = {r["card_id"]: r["cost"] for r in cost_rows}
                    score = Analytics.score_hand(me_hand_ids, reco["scored"], card_costs)
                    # Seuils relatifs : compare à la moyenne du deck au lieu de ±5 absolus.
                    avg_hand = reco.get("avg_hand_score")
                    if avg_hand is not None:
                        # Garder si score > moyenne + 3, Mulligan si score < moyenne - 3.
                        verdict = ("Garder" if score >= avg_hand + 3
                                   else "Mulligan" if score <= avg_hand - 3
                                   else "Neutre")
                    else:
                        # Fallback : seuils absolus si pas assez d'historique.
                        verdict = "Garder" if score >= 5 else "Mulligan" if score <= -5 else "Neutre"
                    self._hand_score_key = hkey
                    self._hand_score_val = {
                        "score": round(score, 1),
                        "verdict": verdict,
                        "avg_hand_score": avg_hand,
                    }
                except Exception:
                    pass
            if self._hand_score_val:
                payload["hand_score"] = self._hand_score_val

        # B — Statistiques matchup (recalcul uniquement si la paire leader change).
        if me_leader and opp_leader:
            mkey = (me_leader, opp_leader)
            if mkey != self._matchup_key:
                try:
                    with Store(self.db_path) as st:
                        rows = st.query(
                            "SELECT result FROM matches "
                            "WHERE my_leader=? AND opp_leader=? AND result IN ('win','loss')",
                            (me_leader, opp_leader),
                        )
                    wins = sum(1 for r in rows if r["result"] == "win")
                    n = len(rows)
                    self._matchup_key = mkey
                    self._matchup_val = {
                        "wr": round(100 * wins / n) if n else None,
                        "wins": wins,
                        "n": n,
                    }
                except Exception:
                    pass
            if self._matchup_val:
                payload["matchup_stats"] = self._matchup_val

        # D — Historique des 5 dernières parties (cache 5 s pour limiter les requêtes).
        now = _time.monotonic()
        if now - self._history_ts > 5.0:
            try:
                with Store(self.db_path) as st:
                    rows = st.query(
                        "SELECT m.result, m.opp_leader, c.name AS opp_name "
                        "FROM matches m LEFT JOIN cards c ON m.opp_leader=c.card_id "
                        "WHERE m.result IN ('win','loss') "
                        "ORDER BY m.played_at DESC LIMIT 5",
                    )
                self._history_val = [
                    {"result": r["result"],
                     "opp_leader": r["opp_leader"],
                     "opp_name": r["opp_name"] or r["opp_leader"]}
                    for r in rows
                ]
                self._history_ts = now
            except Exception:
                pass
        if self._history_val:
            payload["recent_matches"] = self._history_val

        # Odds de pioche : fiables si decklist loggée/stricte (traversent le gating),
        # sinon approximatives (decklist devinée, gated live_draw_odds).
        if me is not None and me_leader and me_deck and me_deck > 0:
            odds = self._draw_odds_log(me, me_leader, me_deck,
                                       me_p.get("life") if me_p else None)
            if odds:
                payload["draw_odds"] = odds

        return payload

    # --- Match lifecycle ---

    def _apply_finished_result(self, rec) -> None:
        """Marque l'état live comme terminé d'après le MatchRecord AutoSaved fraîchement parsé.

        Corrélé au match courant par les leaders quand ils sont connus (sécurité anti-décalage),
        sinon appliqué tel quel (un nouvel AutoSaved en cours de session = la partie qui finit).
        result : 'win'/'loss' du point de vue du joueur local ; win_reason précise (concede…).
        """
        if not rec or rec.result not in ("win", "loss"):
            return
        with self.lock:
            st = self.state
            if not st.players or st.result is not None:
                return  # pas de match affiché, ou résultat déjà connu
            live_leaders = {st.me.leader if st.me else None,
                            st.opp.leader if st.opp else None} - {None}
            rec_leaders = {rec.me.leader, rec.opp.leader} - {None}
            if live_leaders and rec_leaders and not (live_leaders & rec_leaders):
                return  # leaders incompatibles -> autre partie, on n'applique pas
            st.result = rec.result          # 'win' | 'loss'
            st.win_reason = rec.win_reason   # 'concede' | 'damage' | 'inferred' | ...
            st.active = False

    def _tail_loop(self) -> None:
        detector = FormatDetector(self.sources)
        store = Store(self.db_path)  # connexion propre à ce thread
        card_effects.warm()  # précharge la classification d'effets hors partie (évite un hoquet)
        autosaved = self.sources.paths.autosaved_logs
        seen = {p.name for p in autosaved.glob("*.log")} if autosaved.exists() else set()
        tailer = _Tailer(self.sources.player_log)
        timer = MatchTimer()
        # Rattrape une partie déjà en cours quand le dashboard démarre en plein match.
        with self.lock:
            pos = replay_current_match(self.state, self.sources.player_log)
        if pos is not None:
            tailer.pos = pos
        try:
            while not self._stop.is_set():
                if autosaved.exists():
                    for p in autosaved.glob("*.log"):
                        if p.name not in seen:
                            seen.add(p.name)
                            rec = _persist_log(store, detector, p,
                                               duration_override=timer.take_duration())
                            # Player.log (live) n'écrit PAS de ligne de fin propre ("Concedes!"/
                            # "Wins!") : elle n'existe que dans l'AutoSaved écrit en fin de partie.
                            # Ce nouvel AutoSaved EST donc le signal de fin -> on réinjecte son
                            # résultat dans l'état live pour que l'overlay l'affiche.
                            if rec is not None:
                                self._apply_finished_result(rec)
                lines = tailer.read_new()
                if lines:
                    with self.lock:
                        for line in lines:
                            self.state.feed_line(line)
                timer.on_state(self.state.active, self.state.result is not None)
                time.sleep(self.poll)
        finally:
            store.close()
