"""Stockage SQLite : insertion idempotente d'un MatchRecord + requêtes de base."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..model import MatchRecord

SCHEMA = Path(__file__).with_name("schema.sql")
_CARD_STATS = Path(__file__).parent.parent / "data" / "card_stats.json"


class Store:
    def __init__(self, db_path: str | Path = "optcg.db"):
        self.path = str(db_path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA.read_text())
        # Migrations : colonnes ajoutées après la création initiale du schéma.
        for col in ("has_trigger INTEGER", "has_blocker INTEGER",
                    "has_rush INTEGER", "has_dbl_atk INTEGER"):
            try:
                self.conn.execute(f"ALTER TABLE cards ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        try:
            self.conn.execute("ALTER TABLE matches ADD COLUMN my_deck TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()
        self._sync_card_stats()
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _sync_card_stats(self) -> None:
        """Importe card_stats.json si la date a changé depuis le dernier import."""
        if not _CARD_STATS.exists():
            return
        payload = json.loads(_CARD_STATS.read_text())
        current_date = payload.get("generated", "")
        if not current_date:
            return
        row = self.conn.execute(
            "SELECT value FROM metadata WHERE key='card_stats_date'"
        ).fetchone()
        if row and row["value"] == current_date:
            return  # déjà à jour
        self.import_card_stats(payload.get("cards", {}))
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('card_stats_date', ?)",
            (current_date,),
        )

    def import_card_stats(self, cards: dict) -> int:
        """Enrichit la table cards avec has_trigger et counter depuis card_stats.json.

        Idempotent. counter n'écrase pas une valeur déjà connue (ex. JSON local Unity).
        """
        c = self.conn
        for card_id, data in cards.items():
            set_code = card_id.split("-", 1)[0]
            c.execute(
                "INSERT OR IGNORE INTO cards (card_id, set_code) VALUES (?,?)",
                (card_id, set_code),
            )
            c.execute(
                "UPDATE cards SET "
                "has_trigger = ?, has_blocker = ?, has_rush = ?, has_dbl_atk = ?, "
                "counter    = COALESCE(?, counter), "
                "cost       = COALESCE(?, cost), "
                "power      = COALESCE(?, power), "
                "card_type  = COALESCE(?, card_type), "
                "color      = COALESCE(?, color) "
                "WHERE card_id = ?",
                (
                    1 if data.get("trigger") else 0,
                    1 if data.get("blocker") else 0,
                    1 if data.get("rush")    else 0,
                    1 if data.get("dbl_atk") else 0,
                    data.get("counter"),
                    data.get("cost"),
                    data.get("power"),
                    data.get("card_type"),
                    data.get("color"),
                    card_id,
                ),
            )
        return len(cards)

    def has_match(self, match_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM matches WHERE id = ?", (match_id,))
        return cur.fetchone() is not None

    def upsert_match(self, rec: MatchRecord) -> None:
        """Insère/remplace un match et ses tables liées. Idempotent par rec.match_id."""
        c = self.conn
        mid = rec.match_id
        # Purge des lignes liées avant réinsertion (remplacement propre).
        for tbl in ("decks", "opening_hands", "events", "turn_snapshots"):
            c.execute(f"DELETE FROM {tbl} WHERE match_id = ?", (mid,))

        c.execute(
            """INSERT OR REPLACE INTO matches
               (id, played_at, source, room_code, engine_version, mode, format,
                format_confidence, meta, me, opponent, my_leader, opp_leader, my_deck,
                i_went_first,
                result, win_reason, duration_s, my_rating, opp_rating, rating_delta,
                my_deck_remaining, opp_deck_remaining)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mid,
                rec.played_at.isoformat() if rec.played_at else None,
                rec.source, rec.room_code, rec.engine_version, rec.mode, rec.format,
                rec.format_confidence, rec.meta, rec.me.name, rec.opp.name,
                rec.me.leader, rec.opp.leader, rec.my_deck,
                None if rec.i_went_first is None else int(rec.i_went_first),
                rec.result, rec.win_reason, rec.duration_s,
                rec.me.rating, rec.opp.rating, rec.me.rating_delta,
                rec.me.deck_remaining, rec.opp.deck_remaining,
            ),
        )

        for side, p in (("me", rec.me), ("opp", rec.opp)):
            for cid, qty in p.deck.items():
                c.execute(
                    "INSERT OR REPLACE INTO decks (match_id, side, card_id, qty, known) VALUES (?,?,?,?,?)",
                    (mid, side, cid, qty, int(p.deck_known)),
                )
            for pos, cid in enumerate(p.opening_hand):
                kept = None if p.mulligan is None else int(not p.mulligan)
                c.execute(
                    "INSERT INTO opening_hands (match_id, side, position, card_id, kept) VALUES (?,?,?,?,?)",
                    (mid, side, pos, cid, kept),
                )

        for e in rec.events:
            c.execute(
                """INSERT OR REPLACE INTO events
                   (match_id, seq, turn, side, type, card_id, target_id, power, value, raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (mid, e.seq, e.turn, e.side, e.type, e.card_id, e.target_id, e.power, e.value, e.raw),
            )

        for idx, sn in enumerate(rec.snapshots):
            c.execute(
                """INSERT OR REPLACE INTO turn_snapshots
                   (match_id, idx, turn, side, hand_count, hand_ids, board_ids, trash_ids,
                    life, deck_remaining)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (mid, idx, sn.turn, sn.side, sn.hand_count,
                 json.dumps(sn.hand_ids), json.dumps(sn.board_ids),
                 json.dumps(sn.trash_ids), sn.life, sn.deck_remaining),
            )

        # Cache des noms de cartes vus.
        for cid, name in rec.card_names.items():
            c.execute(
                "INSERT OR IGNORE INTO cards (card_id, name, set_code) VALUES (?,?,?)",
                (cid, name, cid.split("-", 1)[0]),
            )
            c.execute(
                "UPDATE cards SET name = COALESCE(name, ?) WHERE card_id = ?",
                (name, cid),
            )
        self.conn.commit()

    def upsert_card_meta(self, meta) -> None:
        """Renseigne/complète une carte dans le cache (depuis carddb ou import externe)."""
        c = self.conn
        c.execute(
            "INSERT OR IGNORE INTO cards (card_id, set_code) VALUES (?,?)",
            (meta.card_id, meta.set_code),
        )
        c.execute(
            """UPDATE cards SET
                 name = COALESCE(?, name), block = COALESCE(?, block),
                 color = COALESCE(?, color), cost = COALESCE(?, cost),
                 power = COALESCE(?, power), counter = COALESCE(?, counter),
                 card_type = COALESCE(?, card_type)
               WHERE card_id = ?""",
            (meta.name, meta.block, meta.color, meta.cost, meta.power,
             meta.counter, meta.card_type, meta.card_id),
        )

    def import_card_names(self, mapping: dict[str, str]) -> int:
        """Importe un référentiel externe id->nom (complète sans écraser l'existant)."""
        n = 0
        for cid, name in mapping.items():
            if not name:
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO cards (card_id, set_code) VALUES (?,?)",
                (cid, cid.split("-", 1)[0]),
            )
            self.conn.execute(
                "UPDATE cards SET name = COALESCE(name, ?) WHERE card_id = ?", (name, cid))
            n += 1
        self.conn.commit()
        return n

    def all_card_ids(self) -> set[str]:
        """Tous les card_id référencés (decks, leaders, events, snapshots)."""
        ids: set[str] = set()
        for r in self.query("SELECT DISTINCT card_id FROM decks WHERE card_id IS NOT NULL"):
            ids.add(r["card_id"])
        for r in self.query("SELECT DISTINCT card_id FROM events WHERE card_id IS NOT NULL"):
            ids.add(r["card_id"])
        for col in ("my_leader", "opp_leader"):
            for r in self.query(f"SELECT DISTINCT {col} AS c FROM matches WHERE {col} IS NOT NULL"):
                ids.add(r["c"])
        return ids

    # --- Requêtes utilitaires ---
    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def card_name(self, card_id: str) -> str:
        row = self.conn.execute("SELECT name FROM cards WHERE card_id = ?", (card_id,)).fetchone()
        return (row["name"] if row and row["name"] else card_id)
