-- Schéma SQLite du tracker OPTCGSim.
-- Idempotence : matches.id = hash stable (contenu de log, ou clé synthétique ranked).

CREATE TABLE IF NOT EXISTS matches (
    id                TEXT PRIMARY KEY,
    played_at         TEXT,            -- ISO 8601
    source            TEXT,            -- autosaved | live | opbounty
    room_code         TEXT,
    engine_version    TEXT,
    mode              TEXT,            -- ranked | direct | unknown
    format            TEXT,
    format_confidence TEXT,
    meta              TEXT,            -- période meta (date + cartes), ex. OP16
    me                TEXT,
    opponent          TEXT,
    my_leader         TEXT,
    opp_leader        TEXT,
    my_deck           TEXT,            -- nom du deck nommé du joueur (inféré, NULL = non identifié)
    i_went_first      INTEGER,         -- 0/1/NULL
    result            TEXT,            -- win | loss | unknown
    win_reason        TEXT,            -- concede | disconnect | damage | inferred | unknown
    duration_s        REAL,
    my_rating         REAL,
    opp_rating        REAL,
    rating_delta      REAL,
    my_deck_remaining INTEGER,
    opp_deck_remaining INTEGER
);

CREATE TABLE IF NOT EXISTS decks (
    match_id  TEXT REFERENCES matches(id) ON DELETE CASCADE,
    side      TEXT,                    -- me | opp
    card_id   TEXT,
    qty       INTEGER,
    known     INTEGER,                 -- 1 = decklist complète, 0 = "cartes vues"
    PRIMARY KEY (match_id, side, card_id)
);

CREATE TABLE IF NOT EXISTS opening_hands (
    match_id  TEXT REFERENCES matches(id) ON DELETE CASCADE,
    side      TEXT,
    position  INTEGER,
    card_id   TEXT,
    kept      INTEGER                  -- 1 = main gardée, 0 = mulligan
);

CREATE TABLE IF NOT EXISTS events (
    match_id    TEXT REFERENCES matches(id) ON DELETE CASCADE,
    seq         INTEGER,
    turn        INTEGER,
    side        TEXT,
    type        TEXT,                  -- draw | deploy | attack | attack_fail | counter | counter_event
                                    --   | don | don_attach | end_turn | result
                                    --   | ko | effect_remove | trash_bare | life_damage  (Value Score)
    card_id     TEXT,
    target_id   TEXT,
    power       INTEGER,
    value       INTEGER,
    raw         TEXT,
    PRIMARY KEY (match_id, seq)
);

CREATE TABLE IF NOT EXISTS turn_snapshots (
    match_id    TEXT REFERENCES matches(id) ON DELETE CASCADE,
    idx         INTEGER,               -- ordre d'apparition
    turn        INTEGER,
    side        TEXT,
    hand_count  INTEGER,
    hand_ids    TEXT,                  -- JSON
    board_ids   TEXT,                  -- JSON
    trash_ids   TEXT,                  -- JSON
    life        INTEGER,
    deck_remaining INTEGER,            -- depuis le flux RZ1
    PRIMARY KEY (match_id, idx)
);

CREATE TABLE IF NOT EXISTS cards (
    card_id     TEXT PRIMARY KEY,
    name        TEXT,
    set_code    TEXT,
    block       INTEGER,
    color       TEXT,
    cost        INTEGER,
    power       INTEGER,
    counter     INTEGER,
    card_type   TEXT,
    has_trigger INTEGER,         -- 1 = carte Trigger, 0 = non, NULL = inconnu
    has_blocker INTEGER,
    has_rush    INTEGER,
    has_dbl_atk INTEGER
);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_matches_leaders ON matches(my_leader, opp_leader);
CREATE INDEX IF NOT EXISTS idx_matches_mode ON matches(mode);
CREATE INDEX IF NOT EXISTS idx_events_match ON events(match_id);
