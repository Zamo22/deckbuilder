"""FastAPI app exposing the deckbuilder engine.

All routes are prefixed with /api so dev and production share the same
URL shape — locally the Next.js dev server proxies /api/* to this app
on port 8000 (see next.config.ts), in production Vercel rewrites it.
"""

import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

# Ensure project root (parent of api/) is on sys.path so `engine` and
# `ingest` packages import cleanly under Vercel's function runtime,
# which may not include the project root in sys.path by default.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from engine.build import build_deck
from engine.candidates import DB_PATH


app = FastAPI(title="Deckbuilder API", version="0.1.0")

# CORS only matters in dev (Next.js :3000 -> FastAPI :8000). In production
# both are same-origin so the middleware is a no-op.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _conn() -> sqlite3.Connection:
    """Fresh sqlite3 connection per request. Cheap on SQLite.

    Read-only mode is required in serverless deployments where the
    function filesystem is read-only — without it SQLite tries to
    create a journal file on first access and crashes. Safe locally
    too: we never write at runtime.
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


class BuildRequest(BaseModel):
    commander: str = Field(..., description="Commander name (exact or substring)")
    bracket: int = Field(4, ge=1, le=4, description="Power bracket 1-4")
    archetype: str | None = Field(None, description="EDHREC theme slug")


@app.get("/api/health")
def health() -> dict:
    """Sanity check + commander count."""
    conn = _conn()
    try:
        count = conn.execute("SELECT COUNT(*) FROM commanders").fetchone()[0]
        return {"ok": True, "commanders": count}
    finally:
        conn.close()


@app.get("/api/commanders")
def list_commanders() -> list[dict]:
    """Return all scraped commanders for the dropdown, sorted by popularity."""
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT oracle_id, name, edhrec_slug, color_identity,
                   edhrec_deck_count
            FROM commanders
            ORDER BY edhrec_deck_count DESC
            """
        ).fetchall()
        return [
            {
                "oracle_id": r["oracle_id"],
                "name": r["name"],
                "slug": r["edhrec_slug"],
                "color_identity": json.loads(r["color_identity"]),
                "deck_count": r["edhrec_deck_count"],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/api/commanders/{slug}/themes")
def list_themes(slug: str) -> list[dict]:
    """Themes available for a commander. Only returns themes we've actually
    scraped (have card-level data for)."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT oracle_id FROM commanders WHERE edhrec_slug = ?", (slug,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Commander '{slug}' not found")
        rows = conn.execute(
            """
            SELECT theme_slug, theme_name, theme_deck_count
            FROM commander_themes
            WHERE commander_oracle_id = ? AND scraped = 1
            ORDER BY theme_deck_count DESC
            """,
            (row["oracle_id"],),
        ).fetchall()
        return [
            {
                "slug": r["theme_slug"],
                "name": r["theme_name"],
                "deck_count": r["theme_deck_count"],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.post("/api/build")
def build(req: BuildRequest) -> dict:
    """Build a 100-card Commander deck."""
    conn = _conn()
    try:
        deck = build_deck(
            conn,
            commander_name=req.commander,
            bracket=req.bracket,
            archetype=req.archetype,
        )
        if deck is None:
            raise HTTPException(
                404, f"Commander not found in scraped data: {req.commander}"
            )
        return {
            "commander": asdict(deck.commander),
            "selections": [
                {"role": role.value, "card": asdict(card)}
                for role, card in deck.selections
            ],
            "basic_lands": deck.basic_lands,
            "bracket": deck.bracket,
            "archetype": deck.archetype,
            "total_cards": deck.total_cards,
            "meta": deck.meta,
        }
    finally:
        conn.close()
