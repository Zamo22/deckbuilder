"""Scrape EDHREC commander pages into local SQLite.

For each commander in commanders.json:
  1. Resolve name -> oracle_id from the cards table.
  2. Fetch the main commander page from json.edhrec.com (cached on disk).
  3. Insert/update the commander row + all cards across all cardlists.
  4. Record every theme listed in panels.taglinks.
  5. Fetch the top-N themes (by deck count, min threshold), insert theme_cards.

Polite scraping: 1.5s delay between fresh HTTP requests, disk-cached so
re-runs hit no network. Card-name -> oracle_id matching tries exact first,
then front-face for split/DFC cards; logs unmatched but does not fail.
"""

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw" / "edhrec"
DB_PATH = DATA_DIR / "cards.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
COMMANDERS_PATH = Path(__file__).parent / "commanders.json"

EDHREC_BASE = "https://json.edhrec.com/pages/commanders"
USER_AGENT = "deckbuilder-ingest/0.1 (personal-project)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

REQUEST_DELAY_SEC = 1.5          # Polite delay AFTER each fresh HTTP request.
THEME_MIN_DECKS = 100            # Skip themes below this — too thin to trust.
THEME_MAX_PER_COMMANDER = 10     # Cap top-N themes scraped per commander.


# ---------- Config / DB helpers ----------

def load_commanders() -> list[dict]:
    with open(COMMANDERS_PATH) as f:
        return json.load(f)


def init_db(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())


def resolve_oracle_id(conn: sqlite3.Connection, name: str) -> str | None:
    """Map a card name to oracle_id. Returns None on no match.

    Try exact match first, then front-face for split/DFC cards
    (Scryfall stores those as 'Front // Back', EDHREC often uses 'Front').
    """
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "SELECT oracle_id FROM cards WHERE name LIKE ? || ' // %'", (name,)
    ).fetchone()
    return row[0] if row else None


def get_commander_color_identity(conn: sqlite3.Connection, oracle_id: str) -> str:
    row = conn.execute(
        "SELECT color_identity FROM cards WHERE oracle_id = ?", (oracle_id,)
    ).fetchone()
    return row[0] if row else "[]"


# ---------- HTTP / caching ----------

def fetch_json(
    url: str, cache_path: Path, session: requests.Session
) -> dict | None:
    """Fetch JSON with disk cache. Returns parsed dict, or None on 404.

    Cache write is atomic (.tmp then rename) so a Ctrl-C mid-write doesn't
    leave a corrupt cache file that we'd later read.
    """
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    resp = session.get(url, headers=HEADERS, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()

    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp_path.write_bytes(resp.content)
    tmp_path.rename(cache_path)

    time.sleep(REQUEST_DELAY_SEC)
    return resp.json()


# ---------- EDHREC payload parsing ----------

def parse_cardlists(data: dict) -> dict[str, list[dict]]:
    """Return {tag: cardviews} from a commander/theme page payload."""
    cardlists = (
        data.get("container", {}).get("json_dict", {}).get("cardlists", [])
        or []
    )
    return {cl.get("tag", "?"): cl.get("cardviews", []) or [] for cl in cardlists}


def extract_taglinks(data: dict) -> list[dict]:
    """Return panels.taglinks (list of {count, slug, value}). Empty if absent."""
    return data.get("panels", {}).get("taglinks", []) or []


def dedup_cardviews(cardlists: dict[str, list[dict]]) -> dict[str, dict]:
    """Collapse all cardviews across all lists into {name: first_seen_cardview}.

    A card commonly appears in both a type bucket (creatures, instants...)
    AND a special list (topcards, highsynergycards). The numeric data is
    identical across lists, so first-seen wins.
    """
    by_name: dict[str, dict] = {}
    for cardviews in cardlists.values():
        for cv in cardviews:
            name = cv.get("name")
            if name and name not in by_name:
                by_name[name] = cv
    return by_name


# ---------- Insert helpers ----------

def upsert_commander(
    conn: sqlite3.Connection,
    oracle_id: str,
    name: str,
    slug: str,
    color_identity: str,
    deck_count: int,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO commanders (
            oracle_id, name, edhrec_slug, color_identity,
            edhrec_deck_count, last_scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            oracle_id, name, slug, color_identity,
            deck_count, datetime.now(timezone.utc).isoformat(),
        ),
    )


def insert_commander_cards(
    conn: sqlite3.Connection,
    commander_oracle_id: str,
    cardlists: dict[str, list[dict]],
    potential_decks: int,
) -> tuple[int, int]:
    """Insert commander_cards rows. Returns (inserted, unmatched)."""
    high_synergy = {cv["name"] for cv in cardlists.get("highsynergycards", [])}
    game_changers = {cv["name"] for cv in cardlists.get("gamechangers", [])}
    new_cards = {cv["name"] for cv in cardlists.get("newcards", [])}

    rows: list[tuple] = []
    unmatched = 0
    for name, cv in dedup_cardviews(cardlists).items():
        oracle_id = resolve_oracle_id(conn, name)
        if oracle_id is None:
            unmatched += 1
        rows.append((
            commander_oracle_id,
            oracle_id,
            name,
            cv.get("synergy"),
            cv.get("inclusion") or cv.get("num_decks"),
            potential_decks,
            1 if name in game_changers else 0,
            1 if name in high_synergy else 0,
            1 if name in new_cards else 0,
        ))

    conn.executemany(
        """
        INSERT OR REPLACE INTO commander_cards (
            commander_oracle_id, card_oracle_id, card_name,
            synergy_score, inclusion_count, potential_decks,
            is_game_changer, is_high_synergy, is_new_card
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows), unmatched


def insert_theme_cards(
    conn: sqlite3.Connection,
    commander_oracle_id: str,
    theme_slug: str,
    cardlists: dict[str, list[dict]],
    potential_decks: int,
) -> tuple[int, int]:
    high_synergy = {cv["name"] for cv in cardlists.get("highsynergycards", [])}
    game_changers = {cv["name"] for cv in cardlists.get("gamechangers", [])}
    new_cards = {cv["name"] for cv in cardlists.get("newcards", [])}

    rows: list[tuple] = []
    unmatched = 0
    for name, cv in dedup_cardviews(cardlists).items():
        oracle_id = resolve_oracle_id(conn, name)
        if oracle_id is None:
            unmatched += 1
        rows.append((
            commander_oracle_id,
            theme_slug,
            oracle_id,
            name,
            cv.get("synergy"),
            cv.get("inclusion") or cv.get("num_decks"),
            potential_decks,
            1 if name in game_changers else 0,
            1 if name in high_synergy else 0,
            1 if name in new_cards else 0,
        ))

    conn.executemany(
        """
        INSERT OR REPLACE INTO theme_cards (
            commander_oracle_id, theme_slug, card_oracle_id, card_name,
            synergy_score, inclusion_count, potential_decks,
            is_game_changer, is_high_synergy, is_new_card
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows), unmatched


def register_themes(
    conn: sqlite3.Connection,
    commander_oracle_id: str,
    taglinks: list[dict],
) -> None:
    """Insert every theme listed in panels.taglinks (with scraped=0)."""
    rows = [
        (commander_oracle_id, t["slug"], t["value"], t.get("count", 0), 0)
        for t in taglinks
        if t.get("slug") and t.get("value")
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO commander_themes (
            commander_oracle_id, theme_slug, theme_name,
            theme_deck_count, scraped
        ) VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )


# ---------- Per-commander pipeline ----------

def scrape_commander(
    conn: sqlite3.Connection,
    session: requests.Session,
    name: str,
    slug: str,
) -> dict:
    """Scrape one commander + its top themes. Commits as it goes."""
    oracle_id = resolve_oracle_id(conn, name)
    if oracle_id is None:
        raise RuntimeError(f"Commander '{name}' not found in cards table")

    url = f"{EDHREC_BASE}/{slug}.json"
    cache_path = RAW_DIR / f"{slug}.json"
    data = fetch_json(url, cache_path, session)
    if data is None:
        raise RuntimeError(f"EDHREC returned 404 for slug '{slug}'")

    potential_decks = data.get("num_decks_avg") or 0
    color_identity = get_commander_color_identity(conn, oracle_id)
    upsert_commander(conn, oracle_id, name, slug, color_identity, potential_decks)

    cardlists = parse_cardlists(data)
    cmdr_inserted, cmdr_unmatched = insert_commander_cards(
        conn, oracle_id, cardlists, potential_decks
    )

    taglinks = extract_taglinks(data)
    register_themes(conn, oracle_id, taglinks)
    conn.commit()

    eligible = sorted(
        [t for t in taglinks if t.get("count", 0) >= THEME_MIN_DECKS],
        key=lambda t: t["count"],
        reverse=True,
    )[:THEME_MAX_PER_COMMANDER]

    theme_inserted = 0
    theme_unmatched = 0
    themes_scraped = 0
    themes_404 = 0
    for t in eligible:
        theme_slug = t["slug"]
        theme_url = f"{EDHREC_BASE}/{slug}/{theme_slug}.json"
        theme_cache = RAW_DIR / slug / f"{theme_slug}.json"
        theme_data = fetch_json(theme_url, theme_cache, session)
        if theme_data is None:
            themes_404 += 1
            continue
        theme_potential = theme_data.get("num_decks_avg") or 0
        theme_cardlists = parse_cardlists(theme_data)
        ins, unm = insert_theme_cards(
            conn, oracle_id, theme_slug, theme_cardlists, theme_potential
        )
        theme_inserted += ins
        theme_unmatched += unm
        themes_scraped += 1
        conn.execute(
            """UPDATE commander_themes SET scraped = 1
               WHERE commander_oracle_id = ? AND theme_slug = ?""",
            (oracle_id, theme_slug),
        )
        conn.commit()

    return {
        "commander_cards": cmdr_inserted,
        "commander_unmatched": cmdr_unmatched,
        "themes_available": len(taglinks),
        "themes_eligible": len(eligible),
        "themes_scraped": themes_scraped,
        "themes_404": themes_404,
        "theme_cards": theme_inserted,
        "theme_unmatched": theme_unmatched,
        "deck_count": potential_decks,
    }


def main() -> int:
    print(f"Project root: {ROOT}")
    print(f"Database:     {DB_PATH}")
    print()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} does not exist. Run ingest/scryfall.py first.")
        return 1

    commanders = load_commanders()
    print(f"Loaded {len(commanders)} commanders from config")
    print()

    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        session = requests.Session()
        session.headers.update(HEADERS)

        for i, cmdr in enumerate(commanders, 1):
            tier = cmdr.get("tier", "?")
            print(f"[{i}/{len(commanders)}] {cmdr['name']} ({tier})")
            try:
                stats = scrape_commander(
                    conn, session, cmdr["name"], cmdr["slug"]
                )
                print(
                    f"  Decks tracked: {stats['deck_count']:,}\n"
                    f"  Commander cards: {stats['commander_cards']} "
                    f"({stats['commander_unmatched']} unmatched)\n"
                    f"  Themes: {stats['themes_scraped']}/{stats['themes_eligible']} scraped "
                    f"({stats['themes_available']} listed, {stats['themes_404']} 404)\n"
                    f"  Theme cards: {stats['theme_cards']} "
                    f"({stats['theme_unmatched']} unmatched)"
                )
            except Exception as e:
                print(f"  ERROR: {e}")
            print()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
