"""Stage 3: build a mana base for a deck.

Two responsibilities:

  1. Reserve basic-land slots up-front, so a candidate pool full of
     utility/dual lands can't crowd basics out (the bug that left Atraxa
     with zero basics).

  2. Allocate basics across the commander's colors proportional to the
     deck's actual pip distribution — a deck with WW in many costs needs
     more Plains than a deck with one W splash.

The heuristic for "how many basics" is by-colors-in-identity:

    1 color  (mono):   24 basics  (utility lands fill the rest)
    2 colors:          12 basics
    3 colors:           8 basics
    4 colors:           6 basics
    5 colors:           5 basics
    0 colors (colorless): 30 Wastes

These are starting points. Higher-power decks (bracket 4) often want
fewer basics — but the candidate pool already biases toward duals at
high power because EDHREC's data reflects what tournament decks run,
so we let the data express the balance via utility-land scores.

Pip counting is conservative: parse {W}/{U}/{B}/{R}/{G} symbols literally,
ignore hybrid like {W/U} (counts as zero for both — wrong but rare and
small effect). Full Karsten pip-source-target math is a v1 polish.

Basics from the candidate pool are filtered out before utility selection
so we don't end up with "Forest" as a single-copy candidate AND a
separately-allocated basic multiplier.
"""

from collections import Counter

from .candidates import Candidate


BASIC_LAND_BY_COLOR = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}

BASIC_NAMES = set(BASIC_LAND_BY_COLOR.values()) | {"Wastes"}

# Number of basics to reserve before utility-land selection, by
# number of colors in commander's identity.
MIN_BASICS_BY_COLORS: dict[int, int] = {
    0: 30,   # colorless → Wastes
    1: 24,
    2: 12,
    3: 8,
    4: 6,
    5: 5,
}


def _count_pips(non_land_cards: list[Candidate]) -> Counter:
    """Count {W}/{U}/{B}/{R}/{G} symbols in mana costs across cards.

    Hybrid pips like {W/U} are ignored (counted as zero) — fine for v0
    since hybrid is rare in the colours that matter at this granularity.
    """
    pips: Counter = Counter()
    for c in non_land_cards:
        cost = c.mana_cost or ""
        for color in "WUBRG":
            pips[color] += cost.count(f"{{{color}}}")
    return pips


def _allocate_basics(
    commander_ci: list[str],
    basic_total: int,
    non_land_cards: list[Candidate],
) -> dict[str, int]:
    """Distribute `basic_total` basics across commander_ci colours by pip ratio.

    Uses largest-remainder rounding so the totals always sum exactly.
    Falls back to even distribution if no colored pips are found.
    """
    if basic_total <= 0:
        return {}
    if not commander_ci:
        return {"Wastes": basic_total}

    pips = _count_pips(non_land_cards)
    relevant = {color: pips.get(color, 0) for color in commander_ci}
    total_pips = sum(relevant.values())

    if total_pips == 0:
        # No colored pips (rare — colorless deck in colored identity).
        # Even split as a fallback.
        per_color, leftover = divmod(basic_total, len(commander_ci))
        out: dict[str, int] = {}
        for i, color in enumerate(commander_ci):
            count = per_color + (1 if i < leftover else 0)
            if count:
                out[BASIC_LAND_BY_COLOR[color]] = count
        return out

    # Largest-remainder method: floor each share, then distribute the
    # leftover to colors with the largest fractional parts.
    raw_shares = {
        color: (relevant[color] / total_pips) * basic_total
        for color in commander_ci
    }
    allocated = {color: int(raw_shares[color]) for color in commander_ci}
    remainder = basic_total - sum(allocated.values())
    sorted_by_frac = sorted(
        commander_ci,
        key=lambda c: raw_shares[c] - int(raw_shares[c]),
        reverse=True,
    )
    for color in sorted_by_frac:
        if remainder <= 0:
            break
        allocated[color] += 1
        remainder -= 1

    return {
        BASIC_LAND_BY_COLOR[color]: count
        for color, count in allocated.items()
        if count > 0
    }


def build_mana_base(
    commander_ci: list[str],
    candidate_lands: list[Candidate],
    non_land_cards: list[Candidate],
    total_land_count: int,
) -> tuple[list[Candidate], dict[str, int]]:
    """Build (utility_lands, basics) summing to `total_land_count`.

    Args:
        commander_ci: e.g. ["G", "U"] for Omo. Empty list = colorless.
        candidate_lands: lands from the candidate pool, score-sorted.
        non_land_cards: the non-land selections (for pip counting).
        total_land_count: target land count for the deck (from bracket budget).

    Returns:
        (utility_lands_picked, {basic_name: count}) — picked +
        sum(basics) == total_land_count.
    """
    n_colors = len(commander_ci)
    min_basics = MIN_BASICS_BY_COLORS.get(n_colors, 5)

    # Filter basics out of the candidate pool — we allocate them separately.
    non_basic_pool = [c for c in candidate_lands if c.name not in BASIC_NAMES]

    # Reserve basic slots; what's left goes to utility lands.
    utility_target = max(0, total_land_count - min_basics)
    utility_picks = non_basic_pool[:utility_target]

    # If the pool didn't have enough utility lands to hit the target,
    # the unfilled utility slots roll over into more basics.
    basics_count = total_land_count - len(utility_picks)
    basics = _allocate_basics(commander_ci, basics_count, non_land_cards)

    return utility_picks, basics
