"""Deck builder orchestrator — assembles a 100-card Commander decklist.

Pipeline:
  1. Resolve commander name -> oracle_id.
  2. Stage 1 (candidates.py): build a ranked pool for (commander, archetype).
  3. Apply bracket Game Changer cap to the pool.
  4. Classify every candidate by role.
  5. Fill non-land roles (ramp, draw, interaction) up to budget.
  6. Fill payoff with what's left until 99-non-land-slots is full.
  7. Fill lands: top utility lands from pool + basics colored to the
     commander's identity to hit the bracket's land count.
  8. Print the deck grouped by role.

v0 stub for mana base: utility lands from EDHREC data + basics. Real
pip-distribution math (Frank Karsten) comes in Stage 3 proper.
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .candidates import Candidate, DB_PATH, build_candidate_pool, resolve_commander
from .manabase import build_mana_base
from .roles import Role, classify
from .slots import SlotBudget, get_budget, get_gc_cap, role_to_budget_count


@dataclass
class BuiltDeck:
    commander: Candidate
    selections: list[tuple[Role, Candidate]]   # non-basic-land cards
    basic_lands: dict[str, int]                # land name -> count
    bracket: int
    archetype: str | None
    meta: dict = field(default_factory=dict)

    @property
    def total_cards(self) -> int:
        return 1 + len(self.selections) + sum(self.basic_lands.values())


# ---------- Helpers ----------

def _load_commander_as_candidate(
    conn: sqlite3.Connection, oracle_id: str
) -> Candidate:
    """Fetch the commander itself from cards table and wrap as a Candidate."""
    row = conn.execute(
        """SELECT oracle_id, name, type_line, mana_cost, cmc, color_identity,
                  oracle_text, produced_mana
           FROM cards WHERE oracle_id = ?""",
        (oracle_id,),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Commander oracle_id {oracle_id} not in cards table")
    return Candidate(
        oracle_id=row["oracle_id"],
        name=row["name"],
        type_line=row["type_line"],
        mana_cost=row["mana_cost"],
        cmc=row["cmc"],
        color_identity=json.loads(row["color_identity"]),
        oracle_text=row["oracle_text"],
        produced_mana=json.loads(row["produced_mana"]) if row["produced_mana"] else None,
        synergy_score=None,
        inclusion_count=0,
        potential_decks=0,
        is_game_changer=False,
        is_high_synergy=False,
        source="commander",
        score=0.0,
    )


def _apply_gc_cap(
    pool: list[Candidate], gc_cap: int | None
) -> tuple[list[Candidate], int]:
    """Filter pool to at most `gc_cap` Game Changer cards (preserves order).

    Returns (filtered_pool, kept_gc_count). gc_cap=None means no cap.
    """
    if gc_cap is None:
        return pool, sum(1 for c in pool if c.is_game_changer)
    out: list[Candidate] = []
    gc_used = 0
    for c in pool:
        if c.is_game_changer:
            if gc_used < gc_cap:
                out.append(c)
                gc_used += 1
            # else drop
        else:
            out.append(c)
    return out, gc_used


def _group_by_role(pool: list[Candidate]) -> dict[Role, list[Candidate]]:
    by_role: dict[Role, list[Candidate]] = defaultdict(list)
    for c in pool:
        by_role[classify(c)].append(c)
    return by_role


def _take_top_n(
    cards: list[Candidate], n: int, taken: set[str]
) -> list[Candidate]:
    """Take up to n cards not already in `taken`. Updates `taken` in place."""
    picked: list[Candidate] = []
    for c in cards:
        if len(picked) >= n:
            break
        if c.oracle_id in taken:
            continue
        picked.append(c)
        taken.add(c.oracle_id)
    return picked


# ---------- Public API ----------

def build_deck(
    conn: sqlite3.Connection,
    commander_name: str,
    bracket: int = 4,
    archetype: str | None = None,
) -> BuiltDeck | None:
    """Build a complete 100-card deck. Returns None if commander not found."""
    resolved = resolve_commander(conn, commander_name)
    if not resolved:
        return None
    commander_oracle_id, _ = resolved

    pool, pool_meta = build_candidate_pool(
        conn, commander_oracle_id, archetype
    )

    gc_cap = get_gc_cap(bracket)
    pool, gc_kept = _apply_gc_cap(pool, gc_cap)

    by_role = _group_by_role(pool)
    budget = get_budget(bracket)
    taken: set[str] = set()
    selections: list[tuple[Role, Candidate]] = []

    # Stage 2: fill non-land slots first. We need them filled before the
    # mana base so pip counting (in manabase) sees the actual deck.
    non_land_target = 99 - budget.lands

    for role in (Role.RAMP, Role.DRAW, Role.INTERACTION):
        target = role_to_budget_count(budget, role)
        picks = _take_top_n(by_role.get(role, []), target, taken)
        for c in picks:
            selections.append((role, c))

    # Payoff absorbs the rest of the non-land slots, including any under-fill
    # from earlier roles (e.g. a thin INTERACTION pool spills into PAYOFF).
    payoff_target = non_land_target - len(selections)
    payoff_picks = _take_top_n(
        by_role.get(Role.PAYOFF, []), payoff_target, taken
    )
    for c in payoff_picks:
        selections.append((Role.PAYOFF, c))

    # If the entire pool was thin, fall back to any leftover non-land card.
    if len(selections) < non_land_target:
        leftovers = [
            c for c in pool
            if c.oracle_id not in taken and classify(c) != Role.LAND
        ]
        for c in leftovers[: non_land_target - len(selections)]:
            selections.append((classify(c), c))
            taken.add(c.oracle_id)

    commander = _load_commander_as_candidate(conn, commander_oracle_id)

    # Stage 3: mana base. Reserves basics, then fills utility from the
    # remaining lands in the candidate pool.
    non_land_cards = [c for _, c in selections]
    candidate_lands = [
        c for c in by_role.get(Role.LAND, [])
        if c.oracle_id not in taken
    ]
    utility_lands, basic_lands = build_mana_base(
        commander_ci=sorted(commander.color_identity),
        candidate_lands=candidate_lands,
        non_land_cards=non_land_cards,
        total_land_count=budget.lands,
    )
    for c in utility_lands:
        selections.append((Role.LAND, c))
        taken.add(c.oracle_id)

    meta = {
        "pool_meta": pool_meta,
        "gc_cap": gc_cap,
        "gc_kept": gc_kept,
        "role_counts": {
            role.value: sum(1 for r, _ in selections if r == role)
            for role in Role
        },
        "basic_count": sum(basic_lands.values()),
    }

    return BuiltDeck(
        commander=commander,
        selections=selections,
        basic_lands=basic_lands,
        bracket=bracket,
        archetype=archetype,
        meta=meta,
    )


# ---------- Output ----------

def _format_card_line(c: Candidate) -> str:
    syn = c.synergy_score if c.synergy_score is not None else 0.0
    flags = []
    if c.is_game_changer:
        flags.append("GC")
    flag_str = " " + " ".join(flags) if flags else ""
    return (
        f"  - {c.name:<38} "
        f"syn {syn:+.2f}  "
        f"{c.inclusion_rate * 100:5.1f}%"
        f"{flag_str}"
    )


def print_deck(deck: BuiltDeck) -> None:
    print(f"=== {deck.commander.name} — Bracket {deck.bracket} ===")
    if deck.archetype:
        print(f"Archetype: {deck.archetype}")
    print(
        f"Color identity: {''.join(sorted(deck.commander.color_identity)) or 'C'}"
        f"   Total: {deck.total_cards} cards"
    )
    for w in deck.meta["pool_meta"].get("warnings", []):
        print(f"  ! {w}")
    role_counts = deck.meta["role_counts"]
    basics = deck.meta["basic_count"]
    print(
        f"Role counts: lands {role_counts['land']}+{basics}b  "
        f"ramp {role_counts['ramp']}  "
        f"draw {role_counts['draw']}  "
        f"interaction {role_counts['interaction']}  "
        f"payoff {role_counts['payoff']}"
    )
    if deck.meta["gc_cap"] is not None:
        print(f"Game Changers: {deck.meta['gc_kept']} / {deck.meta['gc_cap']} cap")
    print()

    print("COMMANDER:")
    print(f"  - {deck.commander.name:<38} [{deck.commander.type_line}]")
    print()

    by_role: dict[Role, list[Candidate]] = defaultdict(list)
    for role, c in deck.selections:
        by_role[role].append(c)

    role_order = [Role.LAND, Role.RAMP, Role.DRAW, Role.INTERACTION, Role.PAYOFF]
    for role in role_order:
        cards = by_role.get(role, [])
        if role == Role.LAND:
            n = len(cards) + sum(deck.basic_lands.values())
        else:
            n = len(cards)
        if n == 0:
            continue
        print(f"{role.value.upper()} ({n}):")
        for c in cards:
            print(_format_card_line(c))
        if role == Role.LAND:
            for name, count in deck.basic_lands.items():
                print(f"  - {name} × {count}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a complete 100-card Commander deck."
    )
    parser.add_argument("commander", help="Commander name (exact or substring)")
    parser.add_argument(
        "--bracket", type=int, default=4, choices=[1, 2, 3, 4],
        help="Power bracket (default 4)",
    )
    parser.add_argument(
        "--theme", default=None,
        help="Archetype/theme slug (e.g. 'infect', 'lands-matter')",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        deck = build_deck(conn, args.commander, args.bracket, args.theme)
        if deck is None:
            print(f"Commander not found in scraped data: {args.commander}")
            return 1
        print_deck(deck)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
