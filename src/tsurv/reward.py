"""Skill-gated kill rewards: accuracy bands, streak ladder, consistency gate."""

from __future__ import annotations

from typing import Final, NewType

Accuracy = NewType("Accuracy", float)
"""Net run accuracy in 0..1 (tally-based: extra/incorrect dilute, missed never do)."""

ConsistencyScore = NewType("ConsistencyScore", float)
"""Kogasa consistency in 0..100 (confident only; rough samples never gate)."""

StreakMult = NewType("StreakMult", float)
"""Kill score multiplier from the streak ladder (x4/x8/x16 clean flow)."""

STREAK_X4: Final = 4
"""First ladder rung: four straight kills quadruple the banded base."""

STREAK_X8: Final = 8
"""Second ladder rung (shares the x8 shield/slow-mo milestone)."""

STREAK_X16: Final = 16
"""Top ladder rung: sixteen straight kills pay sixteen times the banded base."""

CONSISTENCY_GATE: Final = 60.0
"""Kogasa floor for full streak gains; ragged runs bank half."""

CONSISTENCY_CEILING: Final = 100.0
"""Top of the kogasa scale; anything above is a caller bug."""

KILL_POINTS_PER_CHAR: Final = 10
"""Base score per word character before bands, ladder, and gate."""

ACC_BANDS: Final = (
    (0.95, 1.0),
    (0.90, 0.8),
    (0.85, 0.6),
    (0.80, 0.4),
)
"""TypeClash-style payout per net-accuracy floor; below 0.80 pays nothing."""


def accuracy_band(acc: float) -> float:
    """Payout multiplier for net accuracy (sloppy waves earn zero bonus)."""
    if not 0.0 <= acc <= 1.0:
        msg = f"accuracy {acc} outside 0..1"
        raise ValueError(msg)
    for floor, payout in ACC_BANDS:
        if acc >= floor:
            return payout
    return 0.0


def consistency_gate(consist: float | None) -> float:
    """Streak-gain multiplier: ragged runs bank half, rough runs pay in full."""
    if consist is None:
        return 1.0
    if not 0.0 <= consist <= CONSISTENCY_CEILING:
        msg = f"consistency {consist} outside 0..100"
        raise ValueError(msg)
    return 0.5 if consist < CONSISTENCY_GATE else 1.0


def streak_multiplier(streak: int) -> float:
    """Ladder multiplier for the post-kill streak (short streaks pay base)."""
    if streak < 0:
        msg = f"streak must be non-negative, got {streak}"
        raise ValueError(msg)
    if streak >= STREAK_X16:
        return 16.0
    if streak >= STREAK_X8:
        return 8.0
    if streak >= STREAK_X4:
        return 4.0
    return 1.0


def score_kill(
    chars: int,
    acc: float,
    streak_mult: float,
    consist: float | None,
) -> int:
    """Gated kill payout: chars*10 x band(acc) x streak_mult x gate(consist)."""
    if chars < 0:
        msg = f"char count must be non-negative, got {chars}"
        raise ValueError(msg)
    if streak_mult < 0.0:
        msg = f"streak multiplier must be non-negative, got {streak_mult}"
        raise ValueError(msg)
    gated = accuracy_band(acc) * streak_mult * consistency_gate(consist)
    return round(chars * KILL_POINTS_PER_CHAR * gated)
