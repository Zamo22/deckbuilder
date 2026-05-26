"""Deckbuilding engine.

Four stages, run in sequence:
  1. candidates  — pull ~300 ranked candidates for (commander, archetype).
  2. roles       — slot-fill ramp/draw/interaction/wincons/lands/payoffs.
  3. manabase    — pip-aware land base sized to the rest of the deck.
  4. validate    — legality, role counts, curve, pip feasibility.

Each stage is deterministic and queries the local SQLite cache. No network,
no LLM. The whole pipeline runs in well under a second per deck.
"""
