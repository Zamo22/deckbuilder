"""Role classification for cards.

Priority order (first match wins):
  1. type_line contains "Land"            -> LAND
  2. card name in role_overrides.json     -> override
  3. oracle_text matches a pattern        -> RAMP | INTERACTION | DRAW
  4. fallback                              -> PAYOFF

PAYOFF is the catch-all: archetype synergy, wincons, utility, tutors,
anything that isn't obviously ramp/draw/interaction. Splitting WINCON
out is a v1 problem — high-impact PAYOFF cards naturally rise to the
top of the candidate pool by score anyway.

Maintenance loop:
  1. Run engine.build for a commander.
  2. Eyeball the role groupings in the output.
  3. If a card is in the wrong group, add to role_overrides.json.
  4. Rebuild. No code change required.
"""

import json
import re
from enum import Enum
from pathlib import Path

from .candidates import Candidate


class Role(str, Enum):
    LAND = "land"
    RAMP = "ramp"
    DRAW = "draw"
    INTERACTION = "interaction"
    PAYOFF = "payoff"


OVERRIDES_PATH = Path(__file__).parent / "role_overrides.json"


def _load_overrides() -> dict[str, Role]:
    with open(OVERRIDES_PATH) as f:
        raw = json.load(f)
    return {
        name: Role(value)
        for name, value in raw.items()
        if not name.startswith("_")
    }


ROLE_OVERRIDES: dict[str, Role] = _load_overrides()


# Pattern rules. Compiled once. Each role's patterns are tried in order;
# first match wins. Keep these conservative — false positives that span
# roles (e.g. "draw a card" inside a land-search clause) are why
# overrides exist.

_RAMP_PATTERNS = [
    # Mana producers: "Add {C}", "Add {G}{G}", "Add one mana of any color"
    re.compile(r"\badd (\{[CWUBRG0-9X/]+\}|one mana|two mana|three mana)", re.IGNORECASE),
    # Land searchers: "Search your library for [up to N] [basic] land(s)"
    re.compile(r"search your library for (a |an |up to \w+ )?(basic )?lands?\b", re.IGNORECASE),
    # Basic-type searchers (Nature's Lore, Three Visits — overridden, but pattern is here for siblings)
    re.compile(r"search your library for (a |an |up to \w+ )?(forest|island|plains|swamp|mountain) cards?\b", re.IGNORECASE),
    # Treasure generators (small wins for Korvold etc.)
    re.compile(r"create (a |\w+ )?treasure tokens?", re.IGNORECASE),
]

_INTERACTION_PATTERNS = [
    re.compile(r"\bcounter target\b", re.IGNORECASE),
    re.compile(r"\bdestroy target\b", re.IGNORECASE),
    re.compile(r"\bexile target\b", re.IGNORECASE),
    re.compile(r"\bdestroy all\b", re.IGNORECASE),
    re.compile(r"\bexile all\b", re.IGNORECASE),
    re.compile(r"return target \w+ to (its|their) owner's hand", re.IGNORECASE),
    re.compile(r"return all .+ to (its|their) owners' hands", re.IGNORECASE),
]

_DRAW_PATTERNS = [
    re.compile(r"\bdraws? (a card|two cards|three cards|four cards|\w+ cards|that many cards|cards equal)", re.IGNORECASE),
]


def classify(card: Candidate) -> Role:
    """Determine a card's role. See module docstring for priority order."""
    if "Land" in card.type_line:
        return Role.LAND

    if card.name in ROLE_OVERRIDES:
        return ROLE_OVERRIDES[card.name]

    text = card.oracle_text or ""

    if any(p.search(text) for p in _RAMP_PATTERNS):
        return Role.RAMP
    if any(p.search(text) for p in _INTERACTION_PATTERNS):
        return Role.INTERACTION
    if any(p.search(text) for p in _DRAW_PATTERNS):
        return Role.DRAW

    return Role.PAYOFF
