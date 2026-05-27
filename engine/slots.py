"""Bracket-aware slot budgets for deck assembly.

Brackets are Wizards' May-2024 official Commander power tiers:
  1 — Precon level; no Game Changers; weaker answers
  2 — Backbone of decks; no Game Changers
  3 — Upgraded; up to 3 Game Changers; mild tutors okay
  4 — Optimized; all Game Changers, infinite combos, fast mana
  5 — cEDH (we don't target this in v0)

Budgets sum to 99 (commander is the 100th card). PAYOFF absorbs anything
that isn't ramp/draw/interaction/wincon/land — archetype synergy, utility,
tutors, protection.

Adjust by editing this file. The build pipeline reads only these
constants — no other code knows or cares about the numbers.
"""

from dataclasses import dataclass

from .roles import Role


@dataclass(frozen=True)
class SlotBudget:
    lands: int
    ramp: int
    draw: int
    interaction: int
    wincon: int
    payoff: int

    def total(self) -> int:
        return (
            self.lands
            + self.ramp
            + self.draw
            + self.interaction
            + self.wincon
            + self.payoff
        )


# Higher brackets shift slots toward INTERACTION, RAMP, and WINCON
# (more answers, faster mana, dedicated finishers). LAND count tightens
# as the curve sharpens.
BRACKET_BUDGETS: dict[int, SlotBudget] = {
    1: SlotBudget(lands=40, ramp=10, draw=8,  interaction=6,  wincon=2, payoff=33),
    2: SlotBudget(lands=38, ramp=10, draw=10, interaction=8,  wincon=3, payoff=30),
    3: SlotBudget(lands=37, ramp=10, draw=10, interaction=10, wincon=3, payoff=29),
    4: SlotBudget(lands=36, ramp=11, draw=10, interaction=12, wincon=4, payoff=26),
}

# Game Changer cap (None = unlimited). See Wizards' bracket rules.
BRACKET_GC_CAP: dict[int, int | None] = {
    1: 0,
    2: 0,
    3: 3,
    4: None,
}


def get_budget(bracket: int) -> SlotBudget:
    if bracket not in BRACKET_BUDGETS:
        raise ValueError(
            f"Unknown bracket {bracket}; valid: {sorted(BRACKET_BUDGETS)}"
        )
    return BRACKET_BUDGETS[bracket]


def get_gc_cap(bracket: int) -> int | None:
    return BRACKET_GC_CAP[bracket]


def role_to_budget_count(budget: SlotBudget, role: Role) -> int:
    return {
        Role.LAND: budget.lands,
        Role.RAMP: budget.ramp,
        Role.DRAW: budget.draw,
        Role.INTERACTION: budget.interaction,
        Role.WINCON: budget.wincon,
        Role.PAYOFF: budget.payoff,
    }[role]
