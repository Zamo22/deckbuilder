"""Retroactively trim theme_cards to top-N per (commander, theme) by score.

Run once after the initial scrape to reclaim the ~60% of theme_cards data
that the engine never reads. Idempotent — safe to re-run; a no-op once
every (commander, theme) is already at or below the cap.

Score = inclusion_rate + max(0, synergy_score). Must match the formula
in engine/candidates.py and ingest/edhrec.py. If you change one, change
all three.
"""

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "cards.db"

KEEP_PER_THEME = 100


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: database missing: {DB_PATH}")
        return 1

    size_before = DB_PATH.stat().st_size
    print(f"Database: {DB_PATH}")
    print(f"Before:   {size_before / 1_000_000:.1f} MB on disk")

    conn = sqlite3.connect(DB_PATH)
    try:
        rows_before = conn.execute(
            "SELECT COUNT(*) FROM theme_cards"
        ).fetchone()[0]
        print(f"          {rows_before:,} theme_cards rows")

        cur = conn.execute(
            """
            DELETE FROM theme_cards
            WHERE rowid IN (
                SELECT rowid FROM (
                    SELECT
                        rowid,
                        ROW_NUMBER() OVER (
                            PARTITION BY commander_oracle_id, theme_slug
                            ORDER BY (
                                CAST(inclusion_count AS REAL)
                                  / NULLIF(potential_decks, 0)
                                + MAX(0, COALESCE(synergy_score, 0))
                            ) DESC
                        ) AS rn
                    FROM theme_cards
                )
                WHERE rn > ?
            )
            """,
            (KEEP_PER_THEME,),
        )
        deleted = cur.rowcount
        conn.commit()
        rows_after = conn.execute(
            "SELECT COUNT(*) FROM theme_cards"
        ).fetchone()[0]
        print(f"Pruned:   {deleted:,} rows deleted")
        print(f"After:    {rows_after:,} theme_cards rows")
    finally:
        conn.close()

    # VACUUM has to run outside a transaction, so use a fresh connection.
    # isolation_level=None disables sqlite3's auto-BEGIN.
    print("Running VACUUM to reclaim disk space...")
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()

    size_after = DB_PATH.stat().st_size
    print(
        f"Disk:     {size_before / 1_000_000:.1f} MB → "
        f"{size_after / 1_000_000:.1f} MB "
        f"({(size_before - size_after) / 1_000_000:.1f} MB saved)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
