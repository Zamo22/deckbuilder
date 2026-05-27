"""Package detection — combo pieces that travel together.

Risk 3 from the design phase: a naive top-N candidate pool produces
"goodstuff piles with no soul" — high-synergy cards get picked but the
specific combos that make them work are missed because their partners
don't have synergy scores high enough to surface on their own.

The fix is hand-encoded domain knowledge. packages.json defines
combo bundles. If a trigger card appears in the pool, package
detection identifies which partner cards must be prioritized in slot
filling so the combo isn't half-assembled.

Three behaviours:
  - "any" (default): at least one partner is enough.
  - require_all=true:  all listed partners must be present (storm
                       combos with multiple discrete pieces).
  - reverse-detection: partners that are themselves listed as triggers
                       in another package (Demonic Consultation needs
                       a wincon target like Thassa's Oracle).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .candidates import Candidate


PACKAGES_PATH = Path(__file__).parent / "packages.json"


@dataclass(frozen=True)
class PackageRequirement:
    """One package's contribution to the must-include list."""
    package_name: str
    triggers_present: list[str]
    required_partners: list[str]    # the partners we want in the deck


def _load_packages() -> dict[str, dict]:
    with open(PACKAGES_PATH) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def compute_required_cards(
    pool: list[Candidate],
) -> tuple[set[str], list[PackageRequirement]]:
    """Identify package-partner cards that must be prioritised.

    Returns (set of card names to boost, list of detected packages).
    """
    packages = _load_packages()
    pool_names = {c.name for c in pool}

    required_names: set[str] = set()
    detected: list[PackageRequirement] = []

    for pkg_name, pkg in packages.items():
        triggers = pkg.get("triggers", [])
        partners = pkg.get("partners", [])
        require_all = pkg.get("require_all", False)

        triggers_in_pool = [t for t in triggers if t in pool_names]
        if not triggers_in_pool:
            continue

        partners_in_pool = [p for p in partners if p in pool_names]
        if not partners_in_pool:
            # Package fires but no partners available — skip silently.
            # Could surface a warning later; for v0 it just means the
            # candidate pool was too thin to complete this combo.
            continue

        if require_all:
            # Only act if every partner is available; otherwise this
            # combo can't be built at all.
            if len(partners_in_pool) < len(partners):
                continue
            chosen_partners = partners_in_pool
        else:
            chosen_partners = partners_in_pool

        required_names.update(chosen_partners)
        detected.append(
            PackageRequirement(
                package_name=pkg_name,
                triggers_present=triggers_in_pool,
                required_partners=chosen_partners,
            )
        )

    return required_names, detected


def boost_required_in_role_lists(
    by_role: dict,
    required_names: set[str],
) -> None:
    """Reorder each role's card list so required-package cards come first.

    Mutates `by_role` in place. Preserves relative order within
    "required" and "other" groups, so within each group, score-sorted
    order is maintained.
    """
    if not required_names:
        return
    for role, cards in by_role.items():
        required = [c for c in cards if c.name in required_names]
        others = [c for c in cards if c.name not in required_names]
        by_role[role] = required + others
