"""Ingest Scryfall oracle_cards bulk data into a local SQLite cache.

Steps:
  1. Fetch the bulk-data manifest from Scryfall's API.
  2. Find the "oracle_cards" entry (one row per unique card).
  3. Download the JSON file to data/raw/ (skipped if already present).
  4. Stream-parse with ijson, filter to Commander-legal cards,
     write to data/cards.db.

Re-running is idempotent — INSERT OR REPLACE on oracle_id.
"""

import json
import sqlite3
import sys
from pathlib import Path

import ijson
import requests
from tqdm import tqdm


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "cards.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

BULK_DATA_URL = "https://api.scryfall.com/bulk-data"
USER_AGENT = "deckbuilder-ingest/0.1 (personal-project)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

# Layouts that aren't real playable cards (tokens, art series, emblems).
SKIP_LAYOUTS = {"token", "double_faced_token", "emblem", "art_series", "vanguard"}

INSERT_SQL = """
INSERT OR REPLACE INTO cards (
    oracle_id, name, mana_cost, cmc, type_line, oracle_text,
    colors, color_identity, power, toughness, loyalty,
    keywords, produced_mana, edhrec_rank, layout,
    image_uri, scryfall_uri, is_banned_in_commander
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def fetch_bulk_manifest() -> dict:
    """Return Scryfall's oracle_cards bulk-data entry."""
    resp = requests.get(BULK_DATA_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    for entry in resp.json()["data"]:
        if entry["type"] == "oracle_cards":
            return entry
    raise RuntimeError("No oracle_cards entry in Scryfall bulk manifest")


def download_bulk_file(entry: dict) -> Path:
    """Download oracle_cards JSON to data/raw/. Skips if file already exists."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    updated_at = entry["updated_at"][:10]  # YYYY-MM-DD
    out_path = RAW_DIR / f"oracle_cards_{updated_at}.json"

    if out_path.exists():
        print(f"Already downloaded: {out_path.name}")
        return out_path

    url = entry["download_uri"]
    size = entry["size"]
    print(f"Downloading {url}")
    print(f"Size: {size / 1_000_000:.1f} MB")

    with requests.get(url, headers=HEADERS, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            with tqdm(total=size, unit="B", unit_scale=True, unit_divisor=1024) as pbar:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

    return out_path


def init_db(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())


def is_commander_relevant(card: dict) -> bool:
    """True if we want this card in the cache.

    We keep cards that are LEGAL or BANNED in Commander — banned cards
    stay in the DB so the engine can reject them by checking the column,
    rather than maintaining its own banlist.
    """
    status = card.get("legalities", {}).get("commander", "not_legal")
    return status in ("legal", "banned", "restricted")


def extract_image_uri(card: dict) -> str | None:
    """Get a 'normal' size image URL, handling double-faced cards."""
    image_uris = card.get("image_uris") or {}
    uri = image_uris.get("normal") or image_uris.get("large")
    if uri:
        return uri
    faces = card.get("card_faces") or []
    if faces:
        face_uris = faces[0].get("image_uris") or {}
        return face_uris.get("normal") or face_uris.get("large")
    return None


def card_to_row(card: dict) -> tuple:
    """Map a Scryfall card dict to a tuple matching the cards table columns."""
    is_banned = 1 if card.get("legalities", {}).get("commander") == "banned" else 0
    return (
        card["oracle_id"],
        card["name"],
        card.get("mana_cost"),
        card.get("cmc", 0.0),
        card.get("type_line", ""),
        card.get("oracle_text"),
        json.dumps(card.get("colors", [])),
        json.dumps(card.get("color_identity", [])),
        card.get("power"),
        card.get("toughness"),
        card.get("loyalty"),
        json.dumps(card.get("keywords", [])),
        json.dumps(card.get("produced_mana", [])),
        card.get("edhrec_rank"),
        card.get("layout"),
        extract_image_uri(card),
        card.get("scryfall_uri"),
        is_banned,
    )


def ingest(json_path: Path, db_path: Path) -> dict:
    """Stream the bulk JSON and write Commander-relevant cards to SQLite."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)

        total_seen = 0
        total_ingested = 0
        banned_count = 0
        batch: list[tuple] = []
        BATCH_SIZE = 1000

        with open(json_path, "rb") as f:
            # ijson.items(f, "item") yields each element of the top-level JSON
            # array one at a time. The file is ~150MB so streaming matters.
            # use_float=True: parse fractional JSON numbers as float, not Decimal.
            # Python 3.12+ removed sqlite3's legacy Decimal->float adapter.
            cards = ijson.items(f, "item", use_float=True)

            with tqdm(unit=" cards") as pbar:
                for card in cards:
                    total_seen += 1
                    pbar.update(1)

                    if card.get("layout") in SKIP_LAYOUTS:
                        continue
                    if "oracle_id" not in card:
                        continue
                    if not is_commander_relevant(card):
                        continue

                    if card.get("legalities", {}).get("commander") == "banned":
                        banned_count += 1

                    batch.append(card_to_row(card))
                    total_ingested += 1

                    if len(batch) >= BATCH_SIZE:
                        conn.executemany(INSERT_SQL, batch)
                        conn.commit()
                        batch.clear()

            if batch:
                conn.executemany(INSERT_SQL, batch)
                conn.commit()
    finally:
        conn.close()

    return {
        "total_seen": total_seen,
        "total_ingested": total_ingested,
        "banned_count": banned_count,
    }


def main() -> int:
    print(f"Project root: {ROOT}")
    print(f"Database:     {DB_PATH}")
    print()

    print("Fetching Scryfall bulk-data manifest...")
    entry = fetch_bulk_manifest()
    print(f"  oracle_cards updated_at: {entry['updated_at']}")
    print()

    json_path = download_bulk_file(entry)
    print()

    print("Ingesting into SQLite...")
    stats = ingest(json_path, DB_PATH)
    print()

    print("Done.")
    print(f"  Cards seen:     {stats['total_seen']:,}")
    print(f"  Cards ingested: {stats['total_ingested']:,}")
    print(f"  Banned (kept):  {stats['banned_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
