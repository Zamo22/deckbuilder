-- Schema for the local Scryfall card cache.
-- Re-running ingest is idempotent (INSERT OR REPLACE on oracle_id).

CREATE TABLE IF NOT EXISTS cards (
    oracle_id              TEXT PRIMARY KEY,
    name                   TEXT NOT NULL,
    mana_cost              TEXT,           -- e.g. "{2}{U}{U}". NULL for lands.
    cmc                    REAL NOT NULL,  -- REAL because of half-mana cards.
    type_line              TEXT NOT NULL,
    oracle_text            TEXT,
    colors                 TEXT,           -- JSON array, e.g. ["U","B"].
    color_identity         TEXT NOT NULL,  -- JSON array; deck-legality key.
    power                  TEXT,           -- TEXT because "*" is valid.
    toughness              TEXT,
    loyalty                TEXT,
    keywords               TEXT,           -- JSON array.
    produced_mana          TEXT,           -- JSON array; ramp/land queries use this.
    edhrec_rank            INTEGER,        -- Nullable; not every card has a rank.
    layout                 TEXT,           -- "normal", "modal_dfc", "transform"...
    image_uri              TEXT,
    scryfall_uri           TEXT,
    is_banned_in_commander INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cards_name           ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_edhrec_rank    ON cards(edhrec_rank);
CREATE INDEX IF NOT EXISTS idx_cards_color_identity ON cards(color_identity);
CREATE INDEX IF NOT EXISTS idx_cards_cmc            ON cards(cmc);
