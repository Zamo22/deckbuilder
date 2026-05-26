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

-- ============================================================
-- EDHREC ingestion tables
-- ============================================================

-- One row per commander we've scraped. oracle_id joins back to cards.
CREATE TABLE IF NOT EXISTS commanders (
    oracle_id          TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    edhrec_slug        TEXT NOT NULL UNIQUE,
    color_identity     TEXT NOT NULL,
    edhrec_deck_count  INTEGER,             -- num_decks_avg from EDHREC main page
    last_scraped_at    TEXT,                -- ISO timestamp
    FOREIGN KEY (oracle_id) REFERENCES cards(oracle_id)
);

-- Card data from a commander's main EDHREC page (no archetype filter).
-- PK is (commander, card_name) because EDHREC uses names; oracle_id can be NULL
-- if name->oracle_id resolution failed (split/DFC edge cases, weird tokens).
CREATE TABLE IF NOT EXISTS commander_cards (
    commander_oracle_id TEXT NOT NULL,
    card_oracle_id      TEXT,               -- NULL if name match failed
    card_name           TEXT NOT NULL,      -- preserved verbatim from EDHREC
    synergy_score       REAL,               -- Signed; positive = unusually common here
    inclusion_count     INTEGER,            -- decks containing this card
    potential_decks     INTEGER,            -- total decks for the commander
    is_game_changer     INTEGER NOT NULL DEFAULT 0,
    is_high_synergy     INTEGER NOT NULL DEFAULT 0,
    is_new_card         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (commander_oracle_id, card_name),
    FOREIGN KEY (commander_oracle_id) REFERENCES commanders(oracle_id)
);
CREATE INDEX IF NOT EXISTS idx_cmdr_cards_synergy
    ON commander_cards(commander_oracle_id, synergy_score DESC);
CREATE INDEX IF NOT EXISTS idx_cmdr_cards_inclusion
    ON commander_cards(commander_oracle_id, inclusion_count DESC);
CREATE INDEX IF NOT EXISTS idx_cmdr_cards_oracle
    ON commander_cards(card_oracle_id);

-- Available themes for each commander (from panels.taglinks).
-- 'scraped' = 1 once we've fetched the theme's dedicated page.
CREATE TABLE IF NOT EXISTS commander_themes (
    commander_oracle_id TEXT NOT NULL,
    theme_slug          TEXT NOT NULL,
    theme_name          TEXT NOT NULL,      -- Human-readable, e.g. "Infect"
    theme_deck_count    INTEGER,            -- Decks of (commander + theme)
    scraped             INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (commander_oracle_id, theme_slug),
    FOREIGN KEY (commander_oracle_id) REFERENCES commanders(oracle_id)
);

-- Card data from theme-specific pages. Same shape as commander_cards
-- but keyed by (commander, theme, card). Synergy is computed against
-- the theme's deck pool, not the commander's main pool.
CREATE TABLE IF NOT EXISTS theme_cards (
    commander_oracle_id TEXT NOT NULL,
    theme_slug          TEXT NOT NULL,
    card_oracle_id      TEXT,
    card_name           TEXT NOT NULL,
    synergy_score       REAL,
    inclusion_count     INTEGER,
    potential_decks     INTEGER,
    is_game_changer     INTEGER NOT NULL DEFAULT 0,
    is_high_synergy     INTEGER NOT NULL DEFAULT 0,
    is_new_card         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (commander_oracle_id, theme_slug, card_name),
    FOREIGN KEY (commander_oracle_id, theme_slug)
        REFERENCES commander_themes(commander_oracle_id, theme_slug)
);
CREATE INDEX IF NOT EXISTS idx_theme_cards_synergy
    ON theme_cards(commander_oracle_id, theme_slug, synergy_score DESC);
CREATE INDEX IF NOT EXISTS idx_theme_cards_oracle
    ON theme_cards(card_oracle_id);
