"""Stage 1: build a candidate pool for a (commander, archetype) pair.

Scoring:
  score = inclusion_rate + max(0, synergy_score)

  inclusion_rate ∈ [0, 1]:  "how often this card appears in decks of this
                             commander/theme" — captures staple-ness.
  synergy_score  ∈ [-x, y]: "how unusually frequent this card is here
                             vs format average" — captures fit. Clamped at
                             0 below so universal staples (Sol Ring etc.)
                             aren't penalised for being run everywhere.

Pool construction (tiered):
  - No archetype:                    top 300 from commander_cards.
  - Archetype + theme data exists:   top 250 theme + top 100 commander,
                                     deduped by oracle_id.
  - Archetype + no theme data:       fall back to commander_cards, surface
                                     a warning so the caller knows the
                                     archetype input had no effect.

Color-identity safety filter applied at the end (defensive — EDHREC's
data should already respect this, but the cost of an explicit check is
trivial and a single miss would corrupt the whole deck).
"""

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "cards.db"

POOL_SIZE_NO_THEME = 300
POOL_SIZE_THEME_HALF = 250
POOL_SIZE_COMMANDER_HALF = 100


@dataclass
class Candidate:
    oracle_id: str
    name: str
    type_line: str
    mana_cost: str | None
    cmc: float
    color_identity: list[str]
    oracle_text: str | None
    produced_mana: list[str] | None
    image_uri: str | None
    synergy_score: float | None
    inclusion_count: int
    potential_decks: int
    is_game_changer: bool
    is_high_synergy: bool
    source: str          # "commander" or "theme:<slug>"
    score: float

    @property
    def inclusion_rate(self) -> float:
        if not self.potential_decks:
            return 0.0
        return self.inclusion_count / self.potential_decks


# ---------- Internal helpers ----------

def _row_to_candidate(row: sqlite3.Row, source: str) -> Candidate:
    potential = row["potential_decks"] or 0
    inclusion = row["inclusion_count"] or 0
    synergy = row["synergy_score"] or 0.0
    inclusion_rate = (inclusion / potential) if potential else 0.0
    score = inclusion_rate + max(0.0, synergy)

    produced = row["produced_mana"]
    return Candidate(
        oracle_id=row["oracle_id"],
        name=row["name"],
        type_line=row["type_line"],
        mana_cost=row["mana_cost"],
        cmc=row["cmc"],
        color_identity=json.loads(row["color_identity"]),
        oracle_text=row["oracle_text"],
        produced_mana=json.loads(produced) if produced else None,
        image_uri=row["image_uri"],
        synergy_score=row["synergy_score"],
        inclusion_count=inclusion,
        potential_decks=potential,
        is_game_changer=bool(row["is_game_changer"]),
        is_high_synergy=bool(row["is_high_synergy"]),
        source=source,
        score=score,
    )


# The score formula appears in three places:
#   - _row_to_candidate (Python, for the returned Candidate.score)
#   - _fetch_commander_pool (SQL, for ORDER BY against cc.* columns)
#   - _fetch_theme_pool (SQL, for ORDER BY against tc.* columns)
# Keep them in sync. SQLite's two-arg MAX(a, b) is scalar (like GREATEST).

def _fetch_commander_pool(
    conn: sqlite3.Connection, commander_oracle_id: str, limit: int
) -> list[Candidate]:
    rows = conn.execute(
        """
        SELECT
            c.oracle_id, c.name, c.type_line, c.mana_cost, c.cmc,
            c.color_identity, c.oracle_text, c.produced_mana, c.image_uri,
            cc.synergy_score, cc.inclusion_count, cc.potential_decks,
            cc.is_game_changer, cc.is_high_synergy
        FROM commander_cards cc
        JOIN cards c ON c.oracle_id = cc.card_oracle_id
        WHERE cc.commander_oracle_id = ?
          AND cc.card_oracle_id IS NOT NULL
          AND c.is_banned_in_commander = 0
        ORDER BY (
            CAST(cc.inclusion_count AS REAL) / NULLIF(cc.potential_decks, 0)
            + MAX(0, COALESCE(cc.synergy_score, 0))
        ) DESC
        LIMIT ?
        """,
        (commander_oracle_id, limit),
    ).fetchall()
    return [_row_to_candidate(r, "commander") for r in rows]


def _fetch_theme_pool(
    conn: sqlite3.Connection,
    commander_oracle_id: str,
    theme_slug: str,
    limit: int,
) -> list[Candidate]:
    rows = conn.execute(
        """
        SELECT
            c.oracle_id, c.name, c.type_line, c.mana_cost, c.cmc,
            c.color_identity, c.oracle_text, c.produced_mana, c.image_uri,
            tc.synergy_score, tc.inclusion_count, tc.potential_decks,
            tc.is_game_changer, tc.is_high_synergy
        FROM theme_cards tc
        JOIN cards c ON c.oracle_id = tc.card_oracle_id
        WHERE tc.commander_oracle_id = ?
          AND tc.theme_slug = ?
          AND tc.card_oracle_id IS NOT NULL
          AND c.is_banned_in_commander = 0
        ORDER BY (
            CAST(tc.inclusion_count AS REAL) / NULLIF(tc.potential_decks, 0)
            + MAX(0, COALESCE(tc.synergy_score, 0))
        ) DESC
        LIMIT ?
        """,
        (commander_oracle_id, theme_slug, limit),
    ).fetchall()
    return [_row_to_candidate(r, f"theme:{theme_slug}") for r in rows]


def _theme_data_available(
    conn: sqlite3.Connection, commander_oracle_id: str, theme_slug: str
) -> bool:
    row = conn.execute(
        """SELECT scraped FROM commander_themes
           WHERE commander_oracle_id = ? AND theme_slug = ?""",
        (commander_oracle_id, theme_slug),
    ).fetchone()
    return bool(row and row["scraped"])


def _get_commander_color_identity(
    conn: sqlite3.Connection, commander_oracle_id: str
) -> set[str]:
    row = conn.execute(
        "SELECT color_identity FROM cards WHERE oracle_id = ?",
        (commander_oracle_id,),
    ).fetchone()
    return set(json.loads(row["color_identity"])) if row else set()


def _filter_color_identity(
    candidates: list[Candidate], commander_ci: set[str]
) -> tuple[list[Candidate], int]:
    kept: list[Candidate] = []
    dropped = 0
    for c in candidates:
        if set(c.color_identity).issubset(commander_ci):
            kept.append(c)
        else:
            dropped += 1
    return kept, dropped


# ---------- Public API ----------

def resolve_commander(
    conn: sqlite3.Connection, name_query: str
) -> tuple[str, str] | None:
    """Resolve a commander name (exact or substring) to (oracle_id, full_name).

    Only matches against commanders we've scraped EDHREC data for.
    """
    row = conn.execute(
        "SELECT oracle_id, name FROM commanders WHERE name = ?", (name_query,)
    ).fetchone()
    if row:
        return row["oracle_id"], row["name"]
    row = conn.execute(
        "SELECT oracle_id, name FROM commanders WHERE name LIKE ? LIMIT 1",
        (f"%{name_query}%",),
    ).fetchone()
    return (row["oracle_id"], row["name"]) if row else None


def build_candidate_pool(
    conn: sqlite3.Connection,
    commander_oracle_id: str,
    archetype: str | None = None,
) -> tuple[list[Candidate], dict]:
    """Return (pool_sorted_by_score_desc, meta).

    meta keys:
        commander_oracle_id, archetype, commander_color_identity,
        source ('commander_only' | 'theme_plus_commander' | 'commander_fallback'),
        pool_size, warnings (list[str]), and tier-specific counts.
    """
    meta: dict = {
        "commander_oracle_id": commander_oracle_id,
        "archetype": archetype,
        "warnings": [],
    }

    commander_ci = _get_commander_color_identity(conn, commander_oracle_id)
    meta["commander_color_identity"] = sorted(commander_ci)

    if archetype is None:
        pool = _fetch_commander_pool(
            conn, commander_oracle_id, POOL_SIZE_NO_THEME
        )
        meta["source"] = "commander_only"

    elif _theme_data_available(conn, commander_oracle_id, archetype):
        theme_pool = _fetch_theme_pool(
            conn, commander_oracle_id, archetype, POOL_SIZE_THEME_HALF
        )
        commander_pool = _fetch_commander_pool(
            conn, commander_oracle_id, POOL_SIZE_COMMANDER_HALF
        )
        # Dedup by oracle_id, prefer the theme entry (theme synergy
        # is computed against a more specific deck pool — more signal).
        by_id: dict[str, Candidate] = {c.oracle_id: c for c in theme_pool}
        for c in commander_pool:
            by_id.setdefault(c.oracle_id, c)
        pool = sorted(by_id.values(), key=lambda c: c.score, reverse=True)
        meta["source"] = "theme_plus_commander"
        meta["theme_pool_size"] = len(theme_pool)
        meta["commander_pool_size"] = len(commander_pool)
        meta["overlap"] = (
            len(theme_pool) + len(commander_pool) - len(by_id)
        )

    else:
        meta["warnings"].append(
            f"Archetype '{archetype}' has no EDHREC theme data for this "
            "commander; falling back to commander-level data."
        )
        pool = _fetch_commander_pool(
            conn, commander_oracle_id, POOL_SIZE_NO_THEME
        )
        meta["source"] = "commander_fallback"

    pool, dropped = _filter_color_identity(pool, commander_ci)
    if dropped:
        meta["warnings"].append(
            f"Dropped {dropped} cards outside commander color identity."
        )
    meta["pool_size"] = len(pool)
    return pool, meta


# ---------- CLI test harness ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a candidate pool for a commander (spot-check tool)."
    )
    parser.add_argument(
        "commander", help="Commander name (exact or substring)"
    )
    parser.add_argument(
        "--theme", default=None,
        help="Archetype/theme slug (e.g. 'infect', 'lands-matter')",
    )
    parser.add_argument(
        "--limit", type=int, default=30,
        help="How many top candidates to print (default 30)",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        resolved = resolve_commander(conn, args.commander)
        if not resolved:
            print(f"Commander not found in scraped data: {args.commander}")
            return 1
        oracle_id, full_name = resolved

        print(f"Commander: {full_name}")
        if args.theme:
            print(f"Archetype: {args.theme}")
        print()

        pool, meta = build_candidate_pool(conn, oracle_id, args.theme)

        print(f"Pool size: {meta['pool_size']}")
        print(f"Source:    {meta['source']}")
        print(f"Color ID:  {meta['commander_color_identity']}")
        if "overlap" in meta:
            print(
                f"Overlap:   {meta['overlap']} cards in both theme and "
                "commander pools"
            )
        for w in meta["warnings"]:
            print(f"  ! {w}")
        print()

        n = min(args.limit, len(pool))
        print(f"=== Top {n} candidates ===")
        print(
            f"{'#':<3} {'Score':<6} {'Syn':<6} {'Incl%':<6} {'GC':<3} "
            f"{'Name':<38} {'Type'}"
        )
        print("-" * 110)
        for i, c in enumerate(pool[:n], 1):
            print(
                f"{i:<3} "
                f"{c.score:<6.2f} "
                f"{(c.synergy_score or 0):<+6.2f} "
                f"{c.inclusion_rate*100:<6.1f} "
                f"{'GC' if c.is_game_changer else '':<3} "
                f"{c.name:<38.38} "
                f"{c.type_line[:38]}"
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
