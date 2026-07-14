"""Analyses avancées au-dessus de la base : matrice de matchups, courbe Elo, séries.

Complète `stats.py` (agrégats simples) avec des vues plus riches et exploitables.
"""

from __future__ import annotations

from dataclasses import dataclass

from .db.store import Store
from .meta import Meta, meta_of
from .stats import Row

_DECISIVE = "result IN ('win','loss')"
_SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    """Mini-graphe terminal à partir d'une série de valeurs."""
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    out = []
    for v in values:
        if v is None:
            out.append(" ")
        else:
            idx = int((v - lo) / span * (len(_SPARK) - 1))
            out.append(_SPARK[idx])
    return "".join(out)


@dataclass
class MatchupCell:
    opp_leader: str
    opp_name: str
    wins: int
    losses: int

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def winrate(self) -> float:
        return 100 * self.wins / self.total if self.total else 0.0


class Analytics:
    def __init__(self, store: Store):
        self.s = store

    def _mode(self, mode, fmt=None):
        """Clause SQL pour filtrer par mode (ranked/direct) et format (Standard/Extra)."""
        parts, params = [], []
        if mode and mode != "all":
            parts.append("mode = ?"); params.append(mode)
        if fmt and fmt != "all":
            parts.append("format LIKE ?"); params.append(f"{fmt}%")
        if not parts:
            return "", ()
        return " AND " + " AND ".join(parts), tuple(params)

    def matchup_matrix(self, mode: str | None = None, min_games: int = 3
                       ) -> dict[str, list[MatchupCell]]:
        """{leader_name -> [MatchupCell par adversaire]} pour les matchups ≥ min_games."""
        mc, mp = self._mode(mode)
        sql = f"""SELECT my_leader AS a, opp_leader AS b,
                         SUM(result='win') AS w, SUM(result='loss') AS l
                  FROM matches
                  WHERE {_DECISIVE} AND my_leader IS NOT NULL AND opp_leader IS NOT NULL{mc}
                  GROUP BY a, b"""
        out: dict[str, list[MatchupCell]] = {}
        for r in self.s.query(sql, mp):
            cell = MatchupCell(r["b"], self.s.card_name(r["b"]), r["w"] or 0, r["l"] or 0)
            if cell.total >= min_games:
                out.setdefault(self.s.card_name(r["a"]), []).append(cell)
        for cells in out.values():
            cells.sort(key=lambda c: c.total, reverse=True)
        return out

    def elo_curve(self, leader: str | None = None) -> list[tuple[str, float]]:
        """Série (date, rating) des parties classées, ordonnée dans le temps."""
        sql = ("SELECT played_at, my_rating FROM matches "
               "WHERE mode='ranked' AND my_rating IS NOT NULL")
        params: tuple = ()
        if leader:
            sql += " AND my_leader = ?"
            params = (leader,)
        sql += " ORDER BY played_at"
        return [(r["played_at"], r["my_rating"]) for r in self.s.query(sql, params)]

    def streaks(self, mode: str | None = None) -> dict:
        """Plus longue série de victoires/défaites + série en cours."""
        mc, mp = self._mode(mode)
        rows = self.s.query(
            f"SELECT result FROM matches WHERE {_DECISIVE}{mc} ORDER BY played_at", mp)
        results = [r["result"] for r in rows]
        best_w = best_l = cur = 0
        cur_kind = None
        for res in results:
            if res == cur_kind:
                cur += 1
            else:
                cur_kind, cur = res, 1
            if cur_kind == "win":
                best_w = max(best_w, cur)
            else:
                best_l = max(best_l, cur)
        current = (cur_kind, cur) if results else (None, 0)
        return {"best_win_streak": best_w, "best_loss_streak": best_l,
                "current": current, "total": len(results)}

    def mulligan_by_leader(self, mode: str | None = None, min_games: int = 5
                           ) -> list[dict]:
        """Par leader : winrate en gardant vs en mulligan (main du joueur local)."""
        mc, mp = self._mode(mode)
        sql = f"""SELECT m.my_leader AS lead, oh.kept AS kept,
                         SUM(m.result='win') AS w, SUM(m.result='loss') AS l
                  FROM matches m
                  JOIN (SELECT DISTINCT match_id, kept FROM opening_hands WHERE side='me') oh
                    ON oh.match_id = m.id
                  WHERE {_DECISIVE} AND oh.kept IS NOT NULL AND m.my_leader IS NOT NULL{mc}
                  GROUP BY lead, kept"""
        acc: dict[str, dict] = {}
        for r in self.s.query(sql, mp):
            d = acc.setdefault(r["lead"], {"leader": self.s.card_name(r["lead"]),
                                           "kept_w": 0, "kept_l": 0, "mull_w": 0, "mull_l": 0})
            if r["kept"] == 1:
                d["kept_w"], d["kept_l"] = r["w"] or 0, r["l"] or 0
            else:
                d["mull_w"], d["mull_l"] = r["w"] or 0, r["l"] or 0
        out = []
        for d in acc.values():
            d["kept_n"] = d["kept_w"] + d["kept_l"]
            d["mull_n"] = d["mull_w"] + d["mull_l"]
            if d["kept_n"] + d["mull_n"] >= min_games:
                d["kept_wr"] = 100 * d["kept_w"] / d["kept_n"] if d["kept_n"] else None
                d["mull_wr"] = 100 * d["mull_w"] / d["mull_n"] if d["mull_n"] else None
                out.append(d)
        return sorted(out, key=lambda d: d["kept_n"] + d["mull_n"], reverse=True)

    def opening_card_impact(self, leader: str | None = None, min_games: int = 10
                            ) -> list[dict]:
        """Pour chaque carte d'ouverture (côté local) : winrate avec la carte vs baseline.

        Le 'lift' = winrate(avec la carte en main de départ) - winrate global du sous-ensemble.
        Met en évidence les cartes d'ouverture corrélées aux victoires.
        """
        params: list = []
        lead_clause = ""
        if leader:
            lead_clause = " AND m.my_leader = ?"
            params.append(leader)
        # Baseline : winrate sur les matchs ayant une main de départ connue.
        base = self.s.query(
            f"""SELECT SUM(m.result='win') w, SUM(m.result IN ('win','loss')) n
                FROM matches m
                WHERE m.id IN (SELECT match_id FROM opening_hands WHERE side='me'){lead_clause}""",
            tuple(params))[0]
        base_n = base["n"] or 0
        base_wr = 100 * (base["w"] or 0) / base_n if base_n else 0.0

        sql = f"""SELECT oh.card_id AS cid,
                         SUM(m.result='win') AS w,
                         SUM(m.result IN ('win','loss')) AS n
                  FROM opening_hands oh
                  JOIN matches m ON m.id = oh.match_id
                  WHERE oh.side='me'{lead_clause}
                  GROUP BY oh.card_id"""
        out = []
        for r in self.s.query(sql, tuple(params)):
            n = r["n"] or 0
            if n >= min_games:
                wr = 100 * (r["w"] or 0) / n
                out.append({"card_id": r["cid"], "name": self.s.card_name(r["cid"]),
                            "n": n, "winrate": wr, "lift": wr - base_wr})
        return base_wr, sorted(out, key=lambda d: d["lift"], reverse=True)

    def counter_usage(self, mode: str | None = None) -> dict | None:
        """Usage des counters (parties loggées) : counters joués/​partie, victoires vs défaites.

        Basé sur les events (disponibles seulement pour les parties avec log AutoSaved).
        """
        mc, mp = self._mode(mode)
        # Matchs loggés avec au moins un event, et leur résultat.
        matches = self.s.query(
            f"""SELECT m.id AS id, m.result AS result
                FROM matches m
                WHERE {_DECISIVE}{mc} AND EXISTS (SELECT 1 FROM events e WHERE e.match_id=m.id)""",
            mp)
        if not matches:
            return None
        agg = {"win": [0, 0], "loss": [0, 0]}  # result -> [somme counters, nb matchs]
        for row in matches:
            cnt = self.s.query(
                "SELECT COUNT(*) c FROM events WHERE match_id=? AND side='me' AND type='counter'",
                (row["id"],))[0]["c"]
            bucket = agg[row["result"]]
            bucket[0] += cnt
            bucket[1] += 1
        def avg(b):
            return b[0] / b[1] if b[1] else 0.0
        total_n = agg["win"][1] + agg["loss"][1]
        total_c = agg["win"][0] + agg["loss"][0]
        return {
            "n_matches": total_n,
            "avg_counters": total_c / total_n if total_n else 0.0,
            "avg_in_wins": avg(agg["win"]),
            "avg_in_losses": avg(agg["loss"]),
        }

    def by_day(self, mode: str | None = None) -> list[tuple[str, int, int]]:
        """(jour, victoires, défaites) — pour repérer ses bonnes/mauvaises sessions."""
        mc, mp = self._mode(mode)
        sql = f"""SELECT substr(played_at,1,10) AS d,
                         SUM(result='win') AS w, SUM(result='loss') AS l
                  FROM matches WHERE {_DECISIVE} AND played_at IS NOT NULL{mc}
                  GROUP BY d ORDER BY d"""
        return [(r["d"], r["w"] or 0, r["l"] or 0) for r in self.s.query(sql, mp)]

    # --- Meta -> Leader (utilise la colonne matches.meta, résolue date+cartes à l'ingest) ---
    def by_meta(self, timeline: list[Meta], mode: str | None = None,
                fmt: str | None = None) -> list[Row]:
        """Winrate par meta (période), ordonné chronologiquement."""
        mc, mp = self._mode(mode, fmt)
        rows = self.s.query(
            f"""SELECT meta AS g, SUM(result='win') AS w, SUM(result='loss') AS l
                FROM matches WHERE {_DECISIVE} AND meta IS NOT NULL{mc} GROUP BY meta""", mp)
        order = {m.label: i for i, m in enumerate(timeline)}
        out = [Row(r["g"], r["w"] or 0, r["l"] or 0) for r in rows]
        return sorted(out, key=lambda x: order.get(x.label, -1))

    def leaders_in_meta(self, timeline: list[Meta], meta_label: str,
                        mode: str | None = None, having_min: int = 1,
                        fmt: str | None = None) -> list[Row]:
        """Winrate par leader joué, dans un meta donné (le drill-down Meta -> Leader)."""
        mc, mp = self._mode(mode, fmt)
        rows = self.s.query(
            f"""SELECT my_leader AS lead, SUM(result='win') AS w, SUM(result='loss') AS l
                FROM matches WHERE {_DECISIVE} AND meta=? AND my_leader IS NOT NULL{mc}
                GROUP BY my_leader""", (meta_label, *mp))
        out = [Row(self.s.card_name(r["lead"]), r["w"] or 0, r["l"] or 0) for r in rows
               if (r["w"] or 0) + (r["l"] or 0) >= having_min]
        return sorted(out, key=lambda x: x.total, reverse=True)

    def decks_in_meta(self, meta_label: str, mode: str | None = None,
                      having_min: int = 1, fmt: str | None = None) -> list[Row]:
        """Winrate par deck nommé joué dans un meta (drill-down Meta -> Deck).

        NULL (deck non identifié) est exclu : seuls les decks nommés sont navigables.
        """
        mc, mp = self._mode(mode, fmt)
        rows = self.s.query(
            f"""SELECT my_deck AS d, SUM(result='win') AS w, SUM(result='loss') AS l
                FROM matches WHERE {_DECISIVE} AND meta=? AND my_deck IS NOT NULL{mc}
                GROUP BY my_deck""", (meta_label, *mp))
        out = [Row(r["d"], r["w"] or 0, r["l"] or 0) for r in rows
               if (r["w"] or 0) + (r["l"] or 0) >= having_min]
        return sorted(out, key=lambda x: x.total, reverse=True)

    def deck_leader(self, deck: str, meta: str | None = None) -> str | None:
        """Leader (card_id) le plus fréquent pour un deck nommé — pour images/liens."""
        cl = " AND meta=?" if meta else ""
        params = (deck, meta) if meta else (deck,)
        rows = self.s.query(
            f"""SELECT my_leader AS lead, COUNT(*) n FROM matches
                WHERE my_deck=? AND my_leader IS NOT NULL{cl}
                GROUP BY my_leader ORDER BY n DESC LIMIT 1""", params)
        return rows[0]["lead"] if rows else None

    # --- Détail leader / matchup : splits + impact des cartes ---
    def _filter(self, leader=None, meta=None, opp=None, mode=None, deck=None, fmt=None):
        clause, params = "", []
        if leader:
            clause += " AND m.my_leader=?"; params.append(leader)
        if meta:
            clause += " AND m.meta=?"; params.append(meta)
        if opp:
            clause += " AND m.opp_leader=?"; params.append(opp)
        if mode and mode != "all":
            clause += " AND m.mode=?"; params.append(mode)
        if fmt and fmt != "all":
            clause += " AND m.format LIKE ?"; params.append(f"{fmt}%")
        if deck:
            clause += " AND m.my_deck=?"; params.append(deck)
        return clause, params

    def split_first_second(self, leader=None, meta=None, opp=None, mode=None, deck=None, fmt=None) -> list[Row]:
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT i_went_first AS g, SUM(result='win') w, SUM(result='loss') l
                FROM matches m WHERE {_DECISIVE} AND i_went_first IS NOT NULL{cl}
                GROUP BY i_went_first""", tuple(p))
        return [Row("Premier" if r["g"] == 1 else "Second", r["w"] or 0, r["l"] or 0)
                for r in rows]

    def split_mulligan(self, leader=None, meta=None, opp=None, mode=None, deck=None, fmt=None) -> list[Row]:
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT oh.kept AS g, SUM(m.result='win') w, SUM(m.result='loss') l
                FROM matches m JOIN (SELECT DISTINCT match_id, kept FROM opening_hands
                                     WHERE side='me') oh ON oh.match_id=m.id
                WHERE {_DECISIVE} AND oh.kept IS NOT NULL{cl} GROUP BY oh.kept""", tuple(p))
        return [Row("Main gardée" if r["g"] == 1 else "Mulligan", r["w"] or 0, r["l"] or 0)
                for r in rows]

    def split_elo_gap(self, leader=None, meta=None, opp=None, mode=None, deck=None,
                      buckets: tuple[int, int] = (-100, 100), fmt=None) -> list[Row]:
        """Winrate par tranche d'écart d'Elo (my_rating − opp_rating).

        Buckets par défaut : "Underdog (≤−100)" / "Égal (−100..+100)" / "Favori (≥+100)".
        Permet de corriger le biais d'un winrate gonflé par des matchs vs débutants.

        Seules les parties classées avec les deux ratings connus sont comptées.
        """
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        lo, hi = buckets
        rows = self.s.query(
            f"""SELECT
                    CASE
                        WHEN (my_rating - opp_rating) < ?  THEN 'underdog'
                        WHEN (my_rating - opp_rating) > ?  THEN 'favori'
                        ELSE 'egal'
                    END AS bucket,
                    SUM(result='win') AS w, SUM(result='loss') AS l
                FROM matches m
                WHERE {_DECISIVE} AND my_rating IS NOT NULL AND opp_rating IS NOT NULL{cl}
                GROUP BY bucket""", (lo, hi, *p))
        labels = {"underdog": f"Underdog (≤{lo})", "egal": f"Égal ({lo}..{hi})",
                  "favori": f"Favori (≥{hi})"}
        order = ["underdog", "egal", "favori"]
        out = []
        for key in order:
            r = next((row for row in rows if row["bucket"] == key), None)
            if r:
                out.append(Row(labels[key], r["w"] or 0, r["l"] or 0))
        return out

    def opening_impact(self, leader=None, meta=None, opp=None, mode=None, min_games=5,
                       i_went_first: bool | None = None, deck=None, fmt=None):
        """(baseline_wr, n_base, [cartes triées par lift]) sur les mains de départ filtrées.

        `i_went_first=True/False` restreint aux parties où le joueur local est allé Premier/Second.

        Chaque carte expose trois métriques complémentaires :
        - DWR  (Draw Winrate) : WR quand la carte est en main — corrélation brute.
        - PRO  (Play-Rate in Opening) : % de parties où elle a été utilisée (deploy, counter
          ou présente dans trash via effet). Sépare les cartes actives des briques mortes.
        - Dead-in-Hand WR : WR quand la carte n'a jamais été utilisée — détecte les cartes
          portées passivement par une main forte (spurious correlation).
        """
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        if i_went_first is not None:
            cl += " AND m.i_went_first=?"
            p.append(int(i_went_first))
        base = self.s.query(
            f"""SELECT SUM(result='win') w, SUM(result IN ('win','loss')) n FROM matches m
                WHERE m.id IN (SELECT match_id FROM opening_hands WHERE side='me'){cl}""",
            tuple(p))[0]
        n_base = base["n"] or 0
        base_wr = 100 * (base["w"] or 0) / n_base if n_base else 0.0

        # Requête enrichie : pour chaque (carte, partie) on détermine si la carte a été
        # "utilisée" = deployée, jouée comme counter, ou présente dans la défausse (trash).
        rows = self.s.query(
            f"""SELECT oh.card_id cid, m.result res,
                       (EXISTS (
                           SELECT 1 FROM events e
                           WHERE e.match_id = oh.match_id AND e.card_id = oh.card_id
                             AND e.side = 'me'
                             AND e.type IN ('deploy', 'counter', 'counter_event')
                       ) OR EXISTS (
                           SELECT 1 FROM turn_snapshots ts, json_each(ts.trash_ids) je
                           WHERE ts.match_id = oh.match_id AND ts.side = 'me'
                             AND je.value = oh.card_id
                       )) AS used
                FROM opening_hands oh
                JOIN matches m ON m.id = oh.match_id
                WHERE oh.side = 'me' AND m.result IN ('win','loss'){cl}""", tuple(p))

        from collections import defaultdict
        agg = defaultdict(lambda: {"w": 0, "n": 0, "w_used": 0, "n_used": 0,
                                   "w_dead": 0, "n_dead": 0})
        for r in rows:
            win = r["res"] == "win"
            s = agg[r["cid"]]
            s["n"] += 1
            if win:
                s["w"] += 1
            if r["used"]:
                s["n_used"] += 1
                if win:
                    s["w_used"] += 1
            else:
                s["n_dead"] += 1
                if win:
                    s["w_dead"] += 1

        out = []
        for cid, s in agg.items():
            n = s["n"]
            if n < min_games:
                continue
            wr = 100 * s["w"] / n
            pro = 100 * s["n_used"] / n if n else None
            dwr_dead = 100 * s["w_dead"] / s["n_dead"] if s["n_dead"] >= 2 else None
            out.append({
                "card_id": cid, "name": self.s.card_name(cid),
                "n": n, "winrate": wr, "lift": wr - base_wr,
                "pro": pro, "n_used": s["n_used"],
                "dwr_dead": dwr_dead, "n_dead": s["n_dead"],
            })
        return base_wr, n_base, sorted(out, key=lambda d: d["lift"], reverse=True)

    def played_impact(self, leader=None, meta=None, opp=None, mode=None, min_games=4, deck=None, fmt=None):
        """Cartes DÉPLOYÉES corrélées à la victoire — lift conditionné par durée de partie.

        Corrige le biais de survie : le lift d'une carte de mode_turn=T est comparé au WR
        des parties ayant duré au moins T tours (baseline conditionnée, pas globale).
        Tour retenu = MODE du premier déploiement (pas la moyenne).
        """
        from collections import Counter, defaultdict
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)

        # Baseline globale pour contexte d'affichage.
        base = self.s.query(
            f"""SELECT SUM(result='win') w, SUM(result IN ('win','loss')) n FROM matches m
                WHERE m.id IN (SELECT match_id FROM events WHERE type='deploy' AND side='me'){cl}""",
            tuple(p))[0]
        n_base = base["n"] or 0
        base_wr = 100 * (base["w"] or 0) / n_base if n_base else 0.0

        # Durée max par match (proxy : dernier tour avec un event) + résultat.
        match_rows = self.s.query(
            f"""SELECT m.id, m.result, MAX(e.turn) AS max_t
                FROM events e JOIN matches m ON e.match_id=m.id
                WHERE {_DECISIVE}{cl}
                GROUP BY m.id""", tuple(p))
        match_info: dict[str, tuple[str, int]] = {
            r["id"]: (r["result"], r["max_t"] or 0) for r in match_rows}

        # Premier déploiement de chaque carte par match.
        ev_rows = self.s.query(
            f"""SELECT ev.match_id, ev.card_id, ev.first_turn
                FROM (SELECT match_id, card_id, MIN(turn) first_turn FROM events
                      WHERE type='deploy' AND side='me' GROUP BY match_id, card_id) ev
                JOIN matches m ON m.id=ev.match_id
                WHERE {_DECISIVE}{cl}""", tuple(p))

        card_turns: dict[str, list[int]] = defaultdict(list)
        card_wins: dict[str, int] = defaultdict(int)
        card_n: dict[str, int] = defaultdict(int)

        for r in ev_rows:
            cid = r["card_id"]
            t = r["first_turn"] or 1
            res = match_info.get(r["match_id"], ("?", 0))[0]
            card_turns[cid].append(t)
            card_n[cid] += 1
            if res == "win":
                card_wins[cid] += 1

        out = []
        for cid, turns in card_turns.items():
            n = card_n[cid]
            if n < min_games:
                continue

            mode_turn = Counter(turns).most_common(1)[0][0]

            # Baseline conditionnée : WR parmi les parties ayant atteint mode_turn.
            cond = [(res, mx) for res, mx in match_info.values() if mx >= mode_turn]
            cond_n = len(cond)
            cond_w = sum(1 for res, _ in cond if res == "win")
            cond_wr = 100 * cond_w / cond_n if cond_n else base_wr

            wr = 100 * card_wins[cid] / n
            phase = "early" if mode_turn <= 3 else ("mid" if mode_turn <= 6 else "late")

            out.append({
                "card_id": cid, "name": self.s.card_name(cid),
                "n": n, "winrate": wr, "lift": wr - cond_wr,
                "mode_turn": mode_turn, "phase": phase,
                "cond_baseline": round(cond_wr, 1), "cond_n": cond_n,
            })

        return base_wr, n_base, sorted(out, key=lambda d: d["lift"], reverse=True)

    def winning_combos(self, leader=None, meta=None, opp=None, mode=None,
                       min_games=4, top=10, deck=None, fmt=None) -> tuple[float, int, list[dict]]:
        """Paires de cartes DÉPLOYÉES ensemble, corrélées à la victoire (events, parties loggées).

        Retourne (baseline_wr, n_base, [combos triés par lift]). Sparse -> min_games + confiance.
        """
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT ev.match_id mid, ev.card_id cid, m.result res
                FROM (SELECT DISTINCT match_id, card_id FROM events
                      WHERE type='deploy' AND side='me') ev
                JOIN matches m ON m.id=ev.match_id
                WHERE {_DECISIVE}{cl}""", tuple(p))
        per_match: dict[str, list] = {}
        result: dict[str, str] = {}
        for r in rows:
            per_match.setdefault(r["mid"], []).append(r["cid"])
            result[r["mid"]] = r["res"]
        n_base = len(per_match)
        if not n_base:
            return 0.0, 0, []
        base_wr = 100 * sum(v == "win" for v in result.values()) / n_base

        from itertools import combinations
        pair_w: dict[tuple, int] = {}
        pair_n: dict[tuple, int] = {}
        for mid, cards in per_match.items():
            win = result[mid] == "win"
            for a, b in combinations(sorted(set(cards)), 2):
                pair_n[(a, b)] = pair_n.get((a, b), 0) + 1
                if win:
                    pair_w[(a, b)] = pair_w.get((a, b), 0) + 1
        out = []
        for pair, n in pair_n.items():
            if n < min_games:
                continue
            wr = 100 * pair_w.get(pair, 0) / n
            out.append({"a": pair[0], "b": pair[1],
                        "a_name": self.s.card_name(pair[0]), "b_name": self.s.card_name(pair[1]),
                        "n": n, "winrate": wr, "lift": wr - base_wr})
        out.sort(key=lambda d: (d["lift"], d["n"]), reverse=True)
        return base_wr, n_base, out[:top]

    def mulligan_reco(self, leader, meta, opp=None, mode=None, k=20, top=4, deck=None, fmt=None):
        """Recommandation de mulligan avec split Premier / Second.

        Shrinkage : score = (n_mu * lift_mu + k * lift_global) / (n_mu + k)
        Le prior global est lui aussi séparé par ordre de jeu pour respecter les courbes DON!!.
        k=20 par défaut : absorbe la variance du hasard (triggers, mulligans adverses).
        Retourne :
            keep/avoid          : recommandation globale (tous ordres confondus)
            premier/second      : {"keep", "avoid"} spécifiques à l'ordre de jeu
            scored              : liste complète avec scores (pour score_hand)
            confidence          : faible / moyenne / élevée
            avg_hand_score      : score moyen des mains historiques (pour seuils relatifs)
        """
        def _shrinkage_scored(mu_cards, global_cards, k):
            """Applique le shrinkage mu→global, le malus Dead-in-Hand, et trie par score.

            Propage pro/dwr_dead depuis le prior global (plus d'observations que le matchup).
            Malus Dead-in-Hand : si dwr_dead ≈ DWR (carte = passager clandestin), on divise
            le lift par 2. Une carte qui gagne autant sans être jouée ne contribue pas
            activement au winrate.
            """
            def _dead_in_hand_penalty(score, card):
                """Divise le score par 2 si la carte est un passager clandestin."""
                dwr_dead = card.get("dwr_dead")
                n_dead = card.get("n_dead", 0)
                if dwr_dead is not None and n_dead >= 2:
                    dwr_brut = card.get("winrate")
                    if dwr_brut is not None and abs(dwr_dead - dwr_brut) < 3.0:
                        return score / 2.0
                return score

            o_by = {c["card_id"]: c for c in global_cards}
            if not mu_cards:
                s = [{"card_id": c["card_id"], "name": c["name"],
                      "score": _dead_in_hand_penalty(c["lift"], c),
                      "n": c["n"], "n_overall": c["n"],
                      "pro": c.get("pro"), "dwr_dead": c.get("dwr_dead"),
                      "n_dead": c.get("n_dead", 0)} for c in global_cards]
                s.sort(key=lambda d: d["score"], reverse=True)
                return s
            m_by = {c["card_id"]: c for c in mu_cards}
            s = []
            for cid in set(o_by) | set(m_by):
                o, mv = o_by.get(cid), m_by.get(cid)
                lo, no = (o["lift"], o["n"]) if o else (0.0, 0)
                lm, nm = (mv["lift"], mv["n"]) if mv else (0.0, 0)
                if no + nm < 3:
                    continue
                score = (nm * lm + k * lo) / (nm + k)
                # Malus Dead-in-Hand depuis le prior global.
                if o:
                    score = _dead_in_hand_penalty(score, o)
                s.append({"card_id": cid, "name": (o or mv)["name"],
                          "score": score, "n": nm, "n_overall": no,
                          "pro": o.get("pro") if o else None,
                          "dwr_dead": o.get("dwr_dead") if o else None,
                          "n_dead": o.get("n_dead", 0) if o else 0})
            s.sort(key=lambda d: d["score"], reverse=True)
            return s

        def _keep_avoid(scored):
            keep  = [c for c in scored if c["score"] >= 5][:top]
            avoid = [c for c in scored if c["score"] <= -5][-top:][::-1]
            return keep, avoid

        # Priors globaux (tous ordres + séparés Premier / Second).
        _, _, ovr   = self.opening_impact(leader=leader, meta=meta, mode=mode, min_games=6, deck=deck, fmt=fmt)
        _, _, ovr_p = self.opening_impact(leader=leader, meta=meta, mode=mode, min_games=3,
                                          i_went_first=True, deck=deck, fmt=fmt)
        _, _, ovr_s = self.opening_impact(leader=leader, meta=meta, mode=mode, min_games=3,
                                          i_went_first=False, deck=deck, fmt=fmt)

        # Données matchup (si adversaire précisé).
        if opp:
            _, _, mu   = self.opening_impact(leader=leader, meta=meta, opp=opp, mode=mode,
                                             min_games=1, deck=deck, fmt=fmt)
            _, _, mu_p = self.opening_impact(leader=leader, meta=meta, opp=opp, mode=mode,
                                             min_games=1, i_went_first=True, deck=deck, fmt=fmt)
            _, _, mu_s = self.opening_impact(leader=leader, meta=meta, opp=opp, mode=mode,
                                             min_games=1, i_went_first=False, deck=deck, fmt=fmt)
        else:
            mu = mu_p = mu_s = []

        scored   = _shrinkage_scored(mu,   ovr,   k)
        scored_p = _shrinkage_scored(mu_p, ovr_p, k)
        scored_s = _shrinkage_scored(mu_s, ovr_s, k)

        # --- Hybridation avec Avg_Early_Value (Value Score T1-T4) ---
        # Récupère l'early value par carte et l'injecte dans le score.
        # Score_hybrid = α × lift_shrinkage + β × early_value_scaled
        # α=0.6, β=0.4 : la Value corrige le biais "brique" du lift seul.
        early_by_card = self._early_value_map(leader, meta, mode, deck, fmt)
        ALPHA, BETA = 0.6, 0.4
        for scored_list in (scored, scored_p, scored_s):
            for c in scored_list:
                ev = early_by_card.get(c["card_id"])
                c["avg_early_value"] = ev
                if ev is not None:
                    # Scale : l'early value est en "points" (typiquement -3 à +8).
                    # On la ramène à l'échelle du lift (×2) pour qu'elle pèse autant.
                    ev_scaled = ev * 2.0
                    c["score"] = ALPHA * c["score"] + BETA * ev_scaled

        keep,   avoid   = _keep_avoid(scored)
        keep_p, avoid_p = _keep_avoid(scored_p)
        keep_s, avoid_s = _keep_avoid(scored_s)

        n_total = sum(c["n"] for c in scored) if opp else None
        conf = "élevée" if (n_total or 0) >= 25 else "moyenne" if (n_total or 0) >= 12 else "faible"

        # Score moyen des mains historiques (pour seuils relatifs au lieu de ±5 absolus).
        avg_hand = self._avg_hand_score(leader, meta, mode, deck, fmt, scored)

        return {
            "keep": keep, "avoid": avoid,
            "premier": {"keep": keep_p, "avoid": avoid_p},
            "second":  {"keep": keep_s, "avoid": avoid_s},
            "scored": scored,
            "confidence": conf,
            "avg_hand_score": avg_hand,
        }

    def _early_value_map(self, leader, meta, mode, deck, fmt) -> dict[str, float]:
        """Map card_id -> avg_early_value pour ce leader/meta.
        Utilisé par mulligan_reco pour hybrider le score lift."""
        vs = self.value_score_per_card(
            leader=leader, meta=meta, mode=mode, min_games=2, deck=deck, fmt=fmt)
        return {c["card_id"]: c["avg_early_value"] for c in vs if c["avg_early_value"] != 0.0}

    def _avg_hand_score(self, leader, meta, mode, deck, fmt,
                        scored: list[dict] | None = None) -> float | None:
        """Score moyen de toutes les mains historiques pour ce leader.
        Sert de baseline pour les seuils relatifs (Garder/Mulligan)."""
        if scored is None:
            return None
        cl, p = self._filter(leader, meta, None, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT m.id AS mid, oh.card_id AS cid
                FROM matches m JOIN opening_hands oh ON oh.match_id=m.id
                WHERE oh.side='me' AND {_DECISIVE}{cl}
                ORDER BY m.id""", tuple(p))
        hands: dict[str, list[str]] = {}
        for r in rows:
            hands.setdefault(r["mid"], []).append(r["cid"])
        if len(hands) < 3:
            return None
        scores = [Analytics.score_hand(cards, scored) for cards in hands.values()]
        return round(sum(scores) / len(scores), 1)

    @staticmethod
    def score_hand(hand: list[str], scored: list[dict],
                   card_costs: dict[str, int] | None = None) -> float:
        """Score total d'une main de départ.

        Étape 1 — somme des scores individuels des cartes (additif).
        Étape 2 — Curve Penalty : malus si la main contient trop de cartes chères (≥5 cost).
            - 0-2 cartes ≥5 cost → pas de malus
            - 3 cartes ≥5 cost   → -3
            - 4+ cartes ≥5 cost  → -6 (brique injouable)
        Les cartes absentes du modèle comptent 0. Un score positif suggère de garder la main ;
        un score fortement négatif suggère le mulligan.
        """
        by = {c["card_id"]: c["score"] for c in scored}
        base = sum(by.get(cid, 0.0) for cid in hand)

        # Curve Penalty : malus si trop de cartes chères (≥5 cost) dans la main.
        if card_costs:
            expensive = sum(1 for cid in hand if (card_costs.get(cid) or 0) >= 5)
            if expensive >= 4:
                base -= 6
            elif expensive == 3:
                base -= 3

        return base

    def hand_score_stats(self, leader, meta, opp=None, mode=None, min_games=5,
                         scored: list[dict] | None = None, deck=None, fmt=None) -> dict | None:
        """Score moyen des mains historiques (victoires vs défaites).

        `scored` = mulligan_reco(...)["scored"]. Si None, calculé automatiquement.
        Retourne {"avg_win": float, "avg_loss": float, "n_win": int, "n_loss": int,
                  "avg_all": float} ou None si échantillon insuffisant.
        """
        if scored is None:
            reco = self.mulligan_reco(leader, meta, opp=opp, mode=mode, deck=deck, fmt=fmt)
            scored = reco.get("scored", [])
        if not scored:
            return None
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT m.id AS mid, m.result AS res, oh.card_id AS cid
                FROM matches m JOIN opening_hands oh ON oh.match_id=m.id
                WHERE oh.side='me' AND {_DECISIVE}{cl}
                ORDER BY m.id""", tuple(p))
        hands: dict[str, tuple[str, list]] = {}
        for r in rows:
            if r["mid"] not in hands:
                hands[r["mid"]] = (r["res"], [])
            hands[r["mid"]][1].append(r["cid"])
        if len(hands) < min_games:
            return None
        win_s, loss_s, all_s = [], [], []
        for res, cards in hands.values():
            s = Analytics.score_hand(cards, scored)
            all_s.append(s)
            (win_s if res == "win" else loss_s).append(s)
        def avg(lst): return round(sum(lst) / len(lst), 1) if lst else 0.0
        return {"avg_win": avg(win_s), "avg_loss": avg(loss_s),
                "n_win": len(win_s), "n_loss": len(loss_s),
                "avg_all": avg(all_s)}

    def leader_matchups(self, meta_label: str, leader: str, mode=None, having_min=1,
                        deck=None, fmt=None) -> list[dict]:
        """Matchups d'un leader (ou d'un deck) dans un meta, avec l'id adverse (liens web)."""
        cl, p = self._filter(leader, meta_label, None, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT opp_leader opp, SUM(result='win') w, SUM(result='loss') l
                FROM matches m WHERE {_DECISIVE} AND opp_leader IS NOT NULL{cl}
                GROUP BY opp_leader""", tuple(p))
        out = []
        for r in rows:
            w, l = r["w"] or 0, r["l"] or 0
            if w + l >= having_min:
                out.append({"opp_id": r["opp"], "name": self.s.card_name(r["opp"]),
                            "wins": w, "losses": l, "winrate": 100 * w / (w + l)})
        return sorted(out, key=lambda d: d["wins"] + d["losses"], reverse=True)

    # --- KPIs gameplay compétitifs ---

    def life_trajectory(self, leader=None, meta=None, opp=None, mode=None,
                        min_games: int = 5, deck=None, fmt=None) -> dict | None:
        """Courbe de vie par tour (côté 'me'), séparée victoires / défaites.

        Retourne {"win": [(turn, avg_life),...], "loss": [...], "n_win": int, "n_loss": int}
        ou None si pas assez de données.
        """
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT ts.turn, m.result, AVG(ts.life) AS avg_life,
                       COUNT(DISTINCT m.id) AS n
                FROM turn_snapshots ts JOIN matches m ON ts.match_id=m.id
                WHERE ts.side='me' AND ts.life IS NOT NULL AND {_DECISIVE}{cl}
                GROUP BY ts.turn, m.result ORDER BY ts.turn""", tuple(p))
        pts: dict[str, list] = {"win": [], "loss": []}
        counts: dict[str, set] = {"win": set(), "loss": set()}
        # Re-compute n_win/n_loss : COUNT DISTINCT par result
        n_rows = self.s.query(
            f"""SELECT m.result, COUNT(DISTINCT m.id) AS n
                FROM turn_snapshots ts JOIN matches m ON ts.match_id=m.id
                WHERE ts.side='me' AND {_DECISIVE}{cl}
                GROUP BY m.result""", tuple(p))
        n_by = {r["result"]: r["n"] for r in n_rows}
        n_win, n_loss = n_by.get("win", 0), n_by.get("loss", 0)
        if n_win + n_loss < min_games:
            return None
        for r in rows:
            res = r["result"]
            if res in pts:
                pts[res].append((r["turn"], round(r["avg_life"], 2)))
        return {"win": pts["win"], "loss": pts["loss"], "n_win": n_win, "n_loss": n_loss}

    def deploy_curve(self, leader=None, meta=None, opp=None, mode=None,
                     min_games: int = 5, deck=None, fmt=None) -> dict | None:
        """Coût moyen des cartes déployées par tour, séparé victoires / défaites.

        Proxy de la courbe DON!! : une courbe montante rapide = bonne gestion des ressources.
        Retourne {"win": [(turn, avg_cost),...], "loss": [...], "n_win": int, "n_loss": int}.
        """
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT e.turn, m.result, AVG(c.cost) AS avg_cost
                FROM events e
                JOIN matches m ON e.match_id=m.id
                JOIN cards c ON e.card_id=c.card_id
                WHERE e.type='deploy' AND e.side='me'
                      AND c.cost IS NOT NULL AND c.card_type != 'Leader'
                      AND {_DECISIVE}{cl}
                GROUP BY e.turn, m.result ORDER BY e.turn""", tuple(p))
        n_rows = self.s.query(
            f"""SELECT m.result, COUNT(DISTINCT m.id) AS n
                FROM events e JOIN matches m ON e.match_id=m.id
                JOIN cards c ON e.card_id=c.card_id
                WHERE e.type='deploy' AND e.side='me' AND c.cost IS NOT NULL
                      AND {_DECISIVE}{cl}
                GROUP BY m.result""", tuple(p))
        n_by = {r["result"]: r["n"] for r in n_rows}
        n_win, n_loss = n_by.get("win", 0), n_by.get("loss", 0)
        if n_win + n_loss < min_games:
            return None
        pts: dict[str, list] = {"win": [], "loss": []}
        for r in rows:
            res = r["result"]
            if res in pts and r["avg_cost"] is not None:
                pts[res].append((r["turn"], round(r["avg_cost"], 2)))
        return {"win": pts["win"], "loss": pts["loss"], "n_win": n_win, "n_loss": n_loss}

    def attack_distribution(self, leader=None, meta=None, opp=None, mode=None,
                             min_games: int = 5, deck=None, fmt=None) -> dict | None:
        """Ratio d'attaques sur le leader adverse (dommages vie) vs sur les personnages (board).

        Retourne {"win": {"life_pct": float, "n": int}, "loss": {...}, "n_win": int, "n_loss": int}.
        """
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT e.match_id, m.result,
                       SUM(CASE WHEN e.target_id=m.opp_leader THEN 1 ELSE 0 END) AS life_atks,
                       COUNT(*) AS total_atks
                FROM events e JOIN matches m ON e.match_id=m.id
                WHERE e.type='attack' AND e.side='me' AND e.target_id IS NOT NULL
                      AND {_DECISIVE}{cl}
                GROUP BY e.match_id, m.result""", tuple(p))
        agg: dict[str, list] = {"win": [], "loss": []}
        for r in rows:
            res = r["result"]
            if res in agg and r["total_atks"]:
                agg[res].append(100 * (r["life_atks"] or 0) / r["total_atks"])
        n_win, n_loss = len(agg["win"]), len(agg["loss"])
        if n_win + n_loss < min_games:
            return None
        def avg(lst): return sum(lst) / len(lst) if lst else 0.0
        return {
            "win":  {"life_pct": round(avg(agg["win"]), 1),  "n": n_win},
            "loss": {"life_pct": round(avg(agg["loss"]), 1), "n": n_loss},
            "n_win": n_win, "n_loss": n_loss,
        }

    def counter_stats(self, leader=None, meta=None, opp=None, mode=None,
                      min_games: int = 5, deck=None, fmt=None) -> dict | None:
        """Valeur totale et nombre de counters joués par partie, victoires vs défaites.

        Retourne {"win": {"avg_value": float, "avg_count": float}, "loss": {...},
                  "n_win": int, "n_loss": int}.
        """
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT m.id, m.result,
                       SUM(COALESCE(e.value, 0)) AS total_val, COUNT(*) AS cnt
                FROM events e JOIN matches m ON e.match_id=m.id
                WHERE e.type='counter' AND e.side='me' AND {_DECISIVE}{cl}
                GROUP BY m.id, m.result""", tuple(p))
        agg: dict[str, list] = {"win": [], "loss": []}
        for r in rows:
            res = r["result"]
            if res in agg:
                agg[res].append((r["total_val"] or 0, r["cnt"] or 0))
        n_win, n_loss = len(agg["win"]), len(agg["loss"])
        if n_win + n_loss < min_games:
            return None
        def avgs(lst):
            if not lst:
                return {"avg_value": 0.0, "avg_count": 0.0}
            return {"avg_value": round(sum(v for v, _ in lst) / len(lst), 0),
                    "avg_count": round(sum(c for _, c in lst) / len(lst), 1)}
        return {"win": avgs(agg["win"]), "loss": avgs(agg["loss"]),
                "n_win": n_win, "n_loss": n_loss}

    def don_waste(self, leader=None, meta=None, opp=None, mode=None,
                  min_games: int = 5, deck=None, fmt=None) -> dict | None:
        """DON Waste par tour — mesure du DON disponible non utilisé en fin de tour.

        Mécanique OPTCG : on gagne +2 DON par tour (cap 10), qu'on dépense pour poser des
        cartes (coût) ou qu'on attache durablement à un Leader/Character. Le DON "wasté"
        = DON disponible − DON attaché (cumulatif) − coûts de déploiement du tour.

        Un deck avec une courbe de mana bien optimisée minimise le waste, surtout en early
        game. Un waste élevé en mid/late game peut indiquer un deck trop cher ou des mains
        bloquées.

        Retourne :
          - curve  : {win: [(turn, avg_waste)], loss: [...]} — courbe par tour
          - summary: {win: {avg_total, avg_per_turn, n}, loss: {...}} — agrégat par partie
          - n_win, n_loss
        ou None si pas assez de données.
        """
        from collections import defaultdict
        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        rows = self.s.query(
            f"""SELECT e.match_id AS mid, e.turn AS turn, e.type AS etype,
                       e.value AS val, e.card_id AS cid,
                       c.cost AS cost, c.card_type AS ctype,
                       m.result AS res
                FROM events e
                JOIN matches m ON e.match_id = m.id
                LEFT JOIN cards c ON e.card_id = c.card_id
                WHERE e.side = 'me'
                  AND e.type IN ('don', 'don_attach', 'deploy')
                  AND {_DECISIVE}{cl}
                ORDER BY e.match_id, e.turn""", tuple(p))

        if not rows:
            return None

        # Groupe par match : pour chaque tour, accumule don_drawn, don_attached, deploy_cost.
        per_match: dict[str, dict] = {}
        for r in rows:
            mid = r["mid"]
            m = per_match.setdefault(mid, {"res": r["res"], "turns": defaultdict(lambda: {"drawn": 0, "attached": 0, "deploy": 0})})
            t = m["turns"][r["turn"]]
            if r["etype"] == "don":
                t["drawn"] += r["val"] or 0
            elif r["etype"] == "don_attach":
                t["attached"] += r["val"] or 0
            elif r["etype"] == "deploy":
                cost = r["cost"]
                ctype = r["ctype"]
                # On ne compte que les cartes payantes (coût > 0, non-Leader).
                if cost and cost > 0 and ctype != "Leader":
                    t["deploy"] += cost

        # Calcule le waste par tour pour chaque match.
        # DON disponible = somme cumulée des don_drawn, cap 10.
        # DON attaché cumulatif = somme cumulée des don_attach.
        # waste(T) = max(0, don_dispo(T) - don_attaché_cumul(T) - deploy_cost(T))
        curve: dict[str, dict[int, list]] = {"win": defaultdict(list), "loss": defaultdict(list)}
        totals: dict[str, list] = {"win": [], "loss": []}

        for mid, m in per_match.items():
            res = m["res"]
            if res not in ("win", "loss"):
                continue
            don_dispo = 0
            don_attached_cumul = 0
            match_waste = 0
            for turn in sorted(m["turns"]):
                t = m["turns"][turn]
                don_dispo = min(10, don_dispo + t["drawn"])
                don_attached_cumul += t["attached"]
                waste = max(0, don_dispo - don_attached_cumul - t["deploy"])
                curve[res][turn].append(waste)
                match_waste += waste
            totals[res].append(match_waste)

        n_win, n_loss = len(totals["win"]), len(totals["loss"])
        if n_win + n_loss < min_games:
            return None

        def avg_curve(d):
            return [(t, round(sum(v) / len(v), 2)) for t, v in sorted(d.items())]

        def avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else 0.0

        summary = {}
        for res in ("win", "loss"):
            n = len(totals[res])
            avg_total = avg(totals[res])
            # Nombre moyen de tours = moyenne du nombre de tours par match.
            n_turns = sum(len(m["turns"]) for mid, m in per_match.items() if m["res"] == res)
            avg_turns = n_turns / n if n else 0
            summary[res] = {
                "avg_total": avg_total,
                "avg_per_turn": round(avg_total / avg_turns, 2) if avg_turns else 0.0,
                "n": n,
            }

        return {
            "curve": {"win": avg_curve(curve["win"]), "loss": avg_curve(curve["loss"])},
            "summary": summary,
            "n_win": n_win, "n_loss": n_loss,
        }

    def matchups_for_leader(self, timeline: list[Meta], meta_label: str, leader: str,
                            mode: str | None = None, having_min: int = 1) -> list[Row]:
        """Winrate par adversaire pour un leader donné, dans un meta (détail du drill-down)."""
        mc, mp = self._mode(mode)
        rows = self.s.query(
            f"""SELECT opp_leader AS opp, SUM(result='win') AS w, SUM(result='loss') AS l
                FROM matches WHERE {_DECISIVE} AND meta=? AND my_leader=?
                AND opp_leader IS NOT NULL{mc} GROUP BY opp_leader""",
            (meta_label, leader, *mp))
        out = [Row(f"{self.s.card_name(r['opp'])} [{r['opp']}]", r["w"] or 0, r["l"] or 0)
               for r in rows if (r["w"] or 0) + (r["l"] or 0) >= having_min]
        return sorted(out, key=lambda x: x.total, reverse=True)

    def opp_play_rate_by_phase(self, opp_leader: str, meta: str | None = None,
                               min_games: int = 3) -> dict[str, dict]:
        """Play-rate adverse par carte et par phase (early T1-3 / mid T4-6 / late T7+).

        Retourne {card_id: {"early": pct, "mid": pct, "late": pct, "n": int}}.
        Le play-rate par phase = % de parties (vs ce leader) où la carte a été déployée
        durant cette phase. Basé sur les events side='opp' (déploiements adverses réels).

        Utilisé pour pondérer les menaces probables T+1 : une carte jouable (coût ≤ DON)
        mais rarement déployée à la phase actuelle voit son score réduit.
        """
        cl, p = self._filter(leader=None, meta=meta, opp=opp_leader)
        # Nombre total de parties vs ce leader (dénominateur).
        total_rows = self.s.query(
            f"""SELECT COUNT(DISTINCT m.id) AS n
                FROM matches m WHERE {_DECISIVE} AND m.opp_leader=?{cl}""",
            tuple([opp_leader] + p))
        n_total = total_rows[0]["n"] if total_rows else 0
        if n_total < min_games:
            return {}

        # Premier déploiement de chaque carte par match (side='opp').
        rows = self.s.query(
            f"""SELECT ev.card_id, ev.first_turn, ev.match_id
                FROM (SELECT match_id, card_id, MIN(turn) AS first_turn
                      FROM events WHERE type='deploy' AND side='opp'
                      GROUP BY match_id, card_id) ev
                JOIN matches m ON m.id=ev.match_id
                WHERE {_DECISIVE} AND m.opp_leader=?{cl}""",
            tuple([opp_leader] + p))

        # Compte par carte : nombre de parties où elle est jouée dans chaque phase.
        from collections import defaultdict
        phase_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"early": 0, "mid": 0, "late": 0})
        card_matches: dict[str, set] = defaultdict(set)

        for r in rows:
            cid = r["card_id"]
            t = r["first_turn"] or 1
            phase = "early" if t <= 3 else ("mid" if t <= 6 else "late")
            phase_counts[cid][phase] += 1
            card_matches[cid].add(r["match_id"])

        out: dict[str, dict] = {}
        for cid, counts in phase_counts.items():
            n_card = len(card_matches[cid])
            if n_card < min_games:
                continue
            out[cid] = {
                "early": round(100 * counts["early"] / n_total),
                "mid": round(100 * counts["mid"] / n_total),
                "late": round(100 * counts["late"] / n_total),
                "n": n_card,
            }
        return out

    # ------------------------------------------------------------------
    # Value Score — mesure l'impact réel d'une carte à l'instant T (State Diffing).
    # ------------------------------------------------------------------

    # Matrice de conversion : tout est converti en "points" (1 DON!! = 1 point).
    _VALUE_WEIGHTS = {
        "card_drawn": 2,        # +2 par carte piochée (≈ 2000 counter)
        "card_opp_discarded": 2, # +2 par carte adverse défaussée (counter/effet)
        "opp_char_destroyed": 1, # +cost de la carte adverse détruite (1 point par DON de coût)
        "body_on_board": 1,     # +power/1000 par perso posé (corps sur le board)
        "life_damage": 2,       # +2 par vie adverse prise
        "don_invested": -1,     # -1 par DON!! dépensé pour jouer la carte
    }
    # NB : pas de poids "life_heal" — aucun event de soin n'est encore produit par le parser.
    # L'ajouter nécessiterait d'abord un event dédié (RE_HEAL) dans parser/match.py.

    def value_score_per_card(self, leader=None, meta=None, opp=None, mode=None,
                             min_games=3, deck=None, fmt=None) -> list[dict]:
        """Value Score moyen par carte déployée.

        Pour chaque deploy d'une carte, on calcule le diff d'état entre :
        - Snap A : état juste avant le deploy (reconstruit depuis les events du tour)
        - Snap B : état à la fin du tour (turn_snapshot suivant ou events jusqu'au end_turn)

        Le diff capture : cartes piochées, perso adverses détruits, DON investi,
        corps posé sur le board, vies infligées.

        Retourne [{card_id, name, avg_value, n, avg_value_win, avg_value_loss, ...}]
        trié par avg_value décroissant.
        """
        agg, cost_by_id, n_matches = self._value_agg(leader, meta, opp, mode, deck, fmt)
        if n_matches < min_games:
            return []

        import statistics
        out = []
        for cid, data in agg.items():
            vals = data["values"]
            n = len(vals)
            if n < min_games:
                continue
            avg = sum(vals) / n
            avg_win = (sum(data["win_values"]) / len(data["win_values"])
                       if data["win_values"] else None)
            avg_loss = (sum(data["loss_values"]) / len(data["loss_values"])
                        if data["loss_values"] else None)
            avg_early = (sum(data["early_values"]) / len(data["early_values"])
                         if data["early_values"] else 0.0)
            cost = cost_by_id.get(cid, 0)
            vpd = round(avg / cost, 2) if cost > 0 else None
            # Intervalle de confiance à 95 % sur la moyenne (erreur-type × 1.96). Évite
            # d'afficher un Value Score « certain » à n=2 : si l'IC traverse 0, l'effet n'est
            # pas significatif. Marge None si n<2 (variance indéfinie).
            if n >= 2:
                margin = 1.96 * statistics.stdev(vals) / (n ** 0.5)
                ci_low, ci_high = round(avg - margin, 1), round(avg + margin, 1)
                significant = ci_low > 0 or ci_high < 0
            else:
                ci_low = ci_high = None
                significant = False
            out.append({
                "card_id": cid,
                "name": self.s.card_name(cid),
                "n": n,
                "avg_value": round(avg, 1),
                "avg_value_win": round(avg_win, 1) if avg_win is not None else None,
                "avg_value_loss": round(avg_loss, 1) if avg_loss is not None else None,
                "avg_early_value": round(avg_early, 1),
                "avg_cost": cost,
                "vpd": vpd,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "significant": significant,
            })
        out.sort(key=lambda d: d["avg_value"], reverse=True)
        return out

    def _value_agg(self, leader=None, meta=None, opp=None, mode=None, deck=None, fmt=None):
        """Agrégation brute des Value Scores par carte (partie lourde, mémoïsée).

        Indépendant de `min_games` (le filtrage est appliqué par l'appelant) : permet à
        `value_score_per_card` (min_games=3) et `_early_value_map` via `mulligan_reco`
        (min_games=2) de partager le même calcul. Une SEULE requête events (anti N+1).

        Retourne (agg, cost_by_id, n_matches) avec
        agg[card_id] = {"values", "win_values", "loss_values", "early_values"}.
        """
        from collections import defaultdict
        key = (leader, meta, opp, mode, deck, fmt)
        cache = self.__dict__.setdefault("_value_agg_cache", {})
        if key in cache:
            return cache[key]

        cl, p = self._filter(leader, meta, opp, mode, deck, fmt)
        match_rows = self.s.query(
            f"""SELECT DISTINCT m.id AS mid, m.result AS res
                FROM matches m
                WHERE {_DECISIVE}{cl}
                AND EXISTS (SELECT 1 FROM events e WHERE e.match_id=m.id AND e.type='deploy')
                ORDER BY m.id""", tuple(p))
        result_by_mid = {r["mid"]: r["res"] for r in match_rows}

        # Une seule requête : tous les events des matchs filtrés, groupés en Python (anti N+1).
        ev_rows = self.s.query(
            f"""SELECT e.match_id AS mid, e.seq, e.turn, e.side, e.type,
                       e.card_id, e.target_id, e.value
                FROM events e JOIN matches m ON e.match_id=m.id
                WHERE {_DECISIVE}{cl}
                  AND EXISTS (SELECT 1 FROM events d WHERE d.match_id=m.id AND d.type='deploy')
                ORDER BY e.match_id, e.seq""", tuple(p))

        events_by_mid: dict[str, list] = defaultdict(list)
        card_ids: set[str] = set()
        for r in ev_rows:
            events_by_mid[r["mid"]].append(r)
            if r["card_id"]:
                card_ids.add(r["card_id"])
            if r["target_id"]:
                card_ids.add(r["target_id"])

        cost_by_id, power_by_id = {}, {}
        if card_ids:
            ph = ",".join("?" * len(card_ids))
            for r in self.s.query(
                    f"SELECT card_id, cost, power FROM cards WHERE card_id IN ({ph})",
                    tuple(card_ids)):
                cost_by_id[r["card_id"]] = r["cost"] or 0
                power_by_id[r["card_id"]] = r["power"] or 0

        agg = defaultdict(lambda: {
            "values": [], "win_values": [], "loss_values": [], "early_values": []})
        for mid, res in result_by_mid.items():
            value = self._compute_match_value(
                events_by_mid.get(mid, []), mid, res, cost_by_id, power_by_id)
            for cid, turn_values in value.items():
                for turn, vs in turn_values:
                    agg[cid]["values"].append(vs)
                    if turn <= 4:
                        agg[cid]["early_values"].append(vs)
                    (agg[cid]["win_values"] if res == "win"
                     else agg[cid]["loss_values"]).append(vs)

        out = (dict(agg), cost_by_id, len(result_by_mid))
        cache[key] = out
        return out

    def value_score_per_turn(self, match_id: str) -> list[dict]:
        """Value Score par tour pour un match spécifique (timeline post-match).

        Pour chaque tour, calcule le Value Score cumulé de tous les deploys "me".
        Permet de détecter les misplays (tour négatif) et les tours pivots (très positif).

        Retourne [{turn, value, cumulative, deploys: [{card_id, name, value}]}].
        """
        events = self.s.query(
            "SELECT seq, turn, side, type, card_id, target_id, value "
            "FROM events WHERE match_id=? ORDER BY seq", (match_id,))
        if not events:
            return []

        # Cache des coûts/power.
        card_ids = {e["card_id"] for e in events if e["card_id"]}
        card_ids |= {e["target_id"] for e in events if e["target_id"]}
        cost_by_id, power_by_id = {}, {}
        if card_ids:
            ph = ",".join("?" * len(card_ids))
            meta_rows = self.s.query(
                f"SELECT card_id, cost, power FROM cards WHERE card_id IN ({ph})",
                tuple(card_ids))
            cost_by_id = {r["card_id"]: r["cost"] or 0 for r in meta_rows}
            power_by_id = {r["card_id"]: r["power"] or 0 for r in meta_rows}

        per_card = self._compute_match_value(events, match_id, "", cost_by_id, power_by_id)
        # per_card: {card_id: [(turn, value), ...]}

        # Agrège par tour.
        from collections import defaultdict
        by_turn: dict[int, list[tuple[str, str, float]]] = defaultdict(list)  # turn -> [(card_id, name, value)]
        for cid, turn_values in per_card.items():
            name = self.s.card_name(cid)
            for turn, vs in turn_values:
                by_turn[turn].append((cid, name, vs))

        out = []
        cumulative = 0.0
        for turn in sorted(by_turn):
            deploys = by_turn[turn]
            turn_value = sum(v for _, _, v in deploys)
            cumulative += turn_value
            out.append({
                "turn": turn,
                "value": round(turn_value, 1),
                "cumulative": round(cumulative, 1),
                "deploys": [
                    {"card_id": cid, "name": name, "value": round(vs, 1)}
                    for cid, name, vs in deploys
                ],
            })
        return out

    def _compute_match_value(self, events: list, mid: str, result: str,
                             cost_by_id: dict, power_by_id: dict) -> dict[str, list[tuple[int, float]]]:
        """Calcule le Value Score de chaque deploy dans un match.

        Pour chaque deploy de carte X par le camp "me" :
        1. Reconstruit l'état (main, board, DON) juste avant le deploy.
        2. Identifie tous les events causés par X jusqu'au end_turn suivant.
        3. Calcule le diff = value score de X pour ce tour.

        Retourne {card_id: [(turn, value_score), ...]}.
        """
        # Reconstruit l'état progressif depuis les events.
        # On suit : main (draw/counter/deploy), board (deploy/ko/effect_remove/trash_bare),
        # DON investi (don_attach), vies (life_damage).
        state = {"me": {"hand": 0, "board": 0, "don": 0, "life_dmg_dealt": 0},
                 "opp": {"hand": 0, "board": 0, "don": 0, "life_dmg_dealt": 0}}

        # Pour calculer le diff, on snapshot l'état avant chaque deploy "me".
        results: dict[str, list[float]] = {}

        pending_deploy = None  # (card_id, turn, state_snapshot)

        for e in events:
            side = e["side"] if isinstance(e, dict) else e["side"]
            etype = e["type"]
            eid = e["card_id"]
            etgt = e["target_id"]
            eval_ = e["value"]

            # --- Snapshot avant deploy "me" ---
            if etype == "deploy" and side == "me":
                # Si un deploy précédent était en attente, on le clôture avec le diff.
                if pending_deploy:
                    vs = self._diff_value(pending_deploy, state, cost_by_id, power_by_id)
                    results.setdefault(pending_deploy["card_id"], []).append(
                        (pending_deploy["turn"], vs))
                # Ouvre un nouveau pending deploy.
                pending_deploy = {
                    "card_id": eid,
                    "turn": e["turn"],
                    "state_before": {s: dict(state[s]) for s in state},
                    "effects": [],     # events causés par cette carte
                    "saw_attack": False,  # une attaque "me" a-t-elle eu lieu dans la fenêtre ?
                    "self_removed": False,  # la carte déployée a-t-elle été retirée du board ?
                }
                # Le deploy lui-même : investit du DON (coût de la carte) et pose un corps.
                cost = cost_by_id.get(eid, 0)
                state["me"]["don"] += cost
                state["me"]["board"] += 1
                continue

            # --- Attribution causale : une attaque "me" ferme la fenêtre d'effets "OnPlay" ---
            # Au-delà d'une attaque, les KO/trash relèvent du COMBAT (corps déjà en jeu),
            # pas de l'effet de la carte fraîchement posée -> on ne les lui attribue plus.
            if pending_deploy and etype == "attack" and side == "me":
                pending_deploy["saw_attack"] = True

            # --- La carte déployée est-elle elle-même retirée dans sa fenêtre ? ---
            # Pour ko/trash_bare/effect_remove, side = propriétaire de la carte retirée (victime).
            # Ma carte (dcid) retirée -> victime = moi -> side='me'. Pour effect_remove, ma carte
            # est la CIBLE (etgt == dcid). Jouée dans un removal = aucun corps durable -> pas de body.
            if pending_deploy:
                dcid = pending_deploy["card_id"]
                if ((etype == "ko" and eid == dcid and side == "me")
                        or (etype == "trash_bare" and eid == dcid and side == "me")
                        or (etype == "effect_remove" and etgt == dcid and side == "me")):
                    pending_deploy["self_removed"] = True

            # --- Events qui contribuent au pending deploy ---
            if pending_deploy and etype in ("ko", "effect_remove", "trash_bare",
                                             "life_damage", "draw", "counter"):
                pending_deploy["effects"].append({
                    "type": etype, "side": side, "card_id": eid,
                    "target_id": etgt, "value": eval_,
                    # Stamp l'état d'attaque AU MOMENT de l'effet (et non en fin de fenêtre) :
                    # un KO avant la 1re attaque = OnPlay (créditable), après = combat.
                    "after_attack": pending_deploy["saw_attack"],
                })

            # --- Mise à jour de l'état global ---
            if etype == "draw" and side == "me":
                state["me"]["hand"] += 1
            elif etype == "draw" and side == "opp":
                state["opp"]["hand"] += 1
            elif etype == "counter" and side == "me":
                state["me"]["hand"] -= 1
            elif etype == "counter" and side == "opp":
                state["opp"]["hand"] -= 1
            elif etype == "deploy" and side == "opp":
                state["opp"]["board"] += 1
            elif etype == "ko":
                # side = propriétaire de la carte détruite.
                state[side]["board"] = max(0, state[side]["board"] - 1)
            elif etype == "effect_remove":
                # side = INITIATEUR de l'effet. La cible appartient à l'adversaire.
                target_side = "opp" if side == "me" else "me"
                state[target_side]["board"] = max(0, state[target_side]["board"] - 1)
            elif etype == "trash_bare":
                state[side]["board"] = max(0, state[side]["board"] - 1)
            elif etype == "life_damage":
                # side = camp qui INFLIGE les dégâts (attaquant).
                state[side]["life_dmg_dealt"] += eval_ or 0
            elif etype == "end_turn":
                # Clôture le pending deploy à la fin du tour.
                if pending_deploy:
                    vs = self._diff_value(pending_deploy, state, cost_by_id, power_by_id)
                    results.setdefault(pending_deploy["card_id"], []).append(
                        (pending_deploy["turn"], vs))
                    pending_deploy = None

        # Clôture le dernier deploy si pas d'end_turn.
        if pending_deploy:
            vs = self._diff_value(pending_deploy, state, cost_by_id, power_by_id)
            results.setdefault(pending_deploy["card_id"], []).append(
                (pending_deploy["turn"], vs))

        # Retourne {card_id: [(turn, value), ...]} — le caller agrège.
        return results

    def _diff_value(self, deploy: dict, state_after: dict,
                    cost_by_id: dict, power_by_id: dict) -> float:
        """Calcule le Value Score d'un deploy à partir du diff d'état et des effets.

        Value = +2 × (cartes piochées par moi)
              +2 × (cartes adverses défaussées via counter)
              +cost_adverse × (perso adverse détruit)
              +power/1000 × (corps posé)
              +2 × (vies infligées)
              -cost × (DON investi)
        """
        w = self._VALUE_WEIGHTS
        score = 0.0
        before = deploy["state_before"]

        # Diff de main : cartes piochées par moi.
        hand_diff = state_after["me"]["hand"] - before["me"]["hand"]
        if hand_diff > 0:
            score += w["card_drawn"] * hand_diff

        # Corps posé sur le board (power/1000).
        # Une carte retirée dans sa propre fenêtre (KO/bounce/trash le tour même) n'a laissé
        # aucun corps durable : pas de crédit body (mesure d'impact RÉEL, pas théorique).
        card_id = deploy["card_id"]
        if not deploy.get("self_removed"):
            power = power_by_id.get(card_id, 0)
            score += w["body_on_board"] * (power / 1000)

        # DON investi (coût de la carte).
        cost = cost_by_id.get(card_id, 0)
        score += w["don_invested"] * cost

        # Effets directs : KO adverses, counters adverses, vies infligées.
        # Sémantique de `side`, VÉRIFIÉE sur un log AutoSaved réel (la carte retirée atterrit
        # dans le trash du joueur préfixé) : pour ko/trash_bare/effect_remove, side = propriétaire
        # de la carte retirée (la VICTIME), jamais l'agresseur. On ne crédite donc un retrait que
        # si la victime est l'adversaire (side == "opp").
        #   counter     : side = joueur qui défausse (défenseur)
        #   life_damage : side = attaquant qui inflige les dégâts
        for eff in deploy["effects"]:
            if eff["type"] == "ko" and eff["side"] == "opp" and not eff.get("after_attack"):
                # Perso adverse détruit PAR EFFET (avant toute attaque) : +cost du perso adverse.
                # Après une attaque, le KO relève du combat, pas de la carte posée -> non crédité.
                destroyed_cost = cost_by_id.get(eff["card_id"], 0)
                score += w["opp_char_destroyed"] * destroyed_cost
            elif (eff["type"] == "effect_remove" and eff["side"] == "opp"
                  and eff["card_id"] == card_id):
                # Carte ADVERSE retirée (victime = opp) par MA carte déployée (source == carte).
                # side == "opp" exclut le self-trash de coût (Lucky Roux qui trashe son propre
                # Character : side == "me") qui n'est PAS un gain de tempo. source == carte évite
                # de créditer un retrait d'une autre carte tombé par hasard dans la fenêtre.
                target_cost = cost_by_id.get(eff["target_id"], 0)
                score += w["opp_char_destroyed"] * target_cost
            elif (eff["type"] == "trash_bare" and eff["side"] == "opp"
                  and not eff.get("after_attack")):
                target_cost = cost_by_id.get(eff["card_id"], 0)
                score += w["opp_char_destroyed"] * target_cost
            elif eff["type"] == "counter" and eff["side"] == "opp":
                # Counter adverse = l'adversaire défausse une carte = CA pour moi.
                score += w["card_opp_discarded"]
            elif eff["type"] == "life_damage" and eff["side"] == "me":
                score += w["life_damage"] * (eff["value"] or 0)

        return round(score, 1)
