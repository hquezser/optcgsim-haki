"""Agrégations statistiques au-dessus de la base SQLite."""

from __future__ import annotations

from dataclasses import dataclass

from .db.store import Store

# On ne compte que les parties à issue nette pour les winrates.
_DECISIVE = "result IN ('win','loss')"


@dataclass
class Row:
    label: str
    wins: int
    losses: int

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def winrate(self) -> float:
        return 100 * self.wins / self.total if self.total else 0.0


def _mode_clause(mode: str | None) -> tuple[str, tuple]:
    if mode and mode != "all":
        return " AND mode = ?", (mode,)
    return "", ()


class Stats:
    def __init__(self, store: Store):
        self.s = store

    def overall(self, mode: str | None = None) -> Row:
        mc, mp = _mode_clause(mode)
        sql = f"""SELECT
                    SUM(result='win')  AS w,
                    SUM(result='loss') AS l
                  FROM matches WHERE {_DECISIVE}{mc}"""
        r = self.s.query(sql, mp)[0]
        return Row("Global", r["w"] or 0, r["l"] or 0)

    def _grouped(self, expr: str, mode: str | None, label_fn=None, having_min: int = 1) -> list[Row]:
        mc, mp = _mode_clause(mode)
        sql = f"""SELECT {expr} AS g,
                         SUM(result='win')  AS w,
                         SUM(result='loss') AS l
                  FROM matches WHERE {_DECISIVE}{mc}
                  GROUP BY g"""
        rows = []
        for r in self.s.query(sql, mp):
            label = r["g"] if r["g"] is not None else "(inconnu)"
            if label_fn:
                label = label_fn(r["g"])
            row = Row(str(label), r["w"] or 0, r["l"] or 0)
            if row.total >= having_min:
                rows.append(row)
        return sorted(rows, key=lambda x: x.total, reverse=True)

    def by_my_leader(self, mode: str | None = None, having_min: int = 1) -> list[Row]:
        return self._grouped(
            "my_leader", mode,
            label_fn=lambda g: self.s.card_name(g) if g else "(inconnu)",
            having_min=having_min,
        )

    def by_my_deck(self, mode: str | None = None, having_min: int = 1) -> list[Row]:
        """Winrate par deck nommé du joueur. NULL -> « deck non identifié »."""
        return self._grouped(
            "my_deck", mode,
            label_fn=lambda g: g if g else "(deck non identifié)",
            having_min=having_min,
        )

    def by_matchup(self, mode: str | None = None, having_min: int = 1) -> list[Row]:
        mc, mp = _mode_clause(mode)
        sql = f"""SELECT my_leader AS a, opp_leader AS b,
                         SUM(result='win')  AS w,
                         SUM(result='loss') AS l
                  FROM matches
                  WHERE {_DECISIVE} AND my_leader IS NOT NULL AND opp_leader IS NOT NULL{mc}
                  GROUP BY a, b"""
        rows = []
        for r in self.s.query(sql, mp):
            label = f"{self.s.card_name(r['a'])} vs {self.s.card_name(r['b'])}"
            row = Row(label, r["w"] or 0, r["l"] or 0)
            if row.total >= having_min:
                rows.append(row)
        return sorted(rows, key=lambda x: x.total, reverse=True)

    def by_turn_order(self, mode: str | None = None) -> list[Row]:
        mc, mp = _mode_clause(mode)
        sql = f"""SELECT i_went_first AS g,
                         SUM(result='win')  AS w,
                         SUM(result='loss') AS l
                  FROM matches WHERE {_DECISIVE} AND i_went_first IS NOT NULL{mc}
                  GROUP BY g"""
        out = []
        for r in self.s.query(sql, mp):
            label = "Premier" if r["g"] == 1 else "Second"
            out.append(Row(label, r["w"] or 0, r["l"] or 0))
        return out

    def by_mulligan(self, mode: str | None = None) -> list[Row]:
        """Impact de garder vs mulligan, basé sur la main du joueur local."""
        mc, mp = _mode_clause(mode)
        sql = f"""SELECT oh.kept AS g,
                         SUM(m.result='win')  AS w,
                         SUM(m.result='loss') AS l
                  FROM matches m
                  JOIN (SELECT DISTINCT match_id, kept FROM opening_hands WHERE side='me') oh
                    ON oh.match_id = m.id
                  WHERE {_DECISIVE} AND oh.kept IS NOT NULL{mc}
                  GROUP BY oh.kept"""
        out = []
        for r in self.s.query(sql, mp):
            label = "Main gardée" if r["g"] == 1 else "Mulligan"
            out.append(Row(label, r["w"] or 0, r["l"] or 0))
        return out

    def avg_duration(self, mode: str | None = None) -> float | None:
        mc, mp = _mode_clause(mode)
        sql = f"SELECT AVG(duration_s) d FROM matches WHERE duration_s IS NOT NULL{mc}"
        return self.s.query(sql, mp)[0]["d"]
