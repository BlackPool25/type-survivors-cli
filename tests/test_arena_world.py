"""World-space spawns: simultaneous ring waves, viewport-free camera, real travel."""

from __future__ import annotations

import math
from typing import Final

from tsurv.app import leaked_untyped
from tsurv.arena import (
    SPAWN_BASE_RADIUS,
    EnemyKind,
    advance,
    initial_arena,
    seconds_to_impact,
    spawn_count_for_level,
    spawn_radius_for_level,
    spawn_wave,
    world_xy,
)
from tsurv.stage import world_to_cell
from tsurv.words import Tier, Word, WordText

_MIN_SEPARATION: Final = 0.25
"""Brief floor: simultaneous foes land at least 0.25 rad apart."""

_SMALL_VIEW: Final = (80, 24)
"""Compact pilot viewport: the camera must match the wide field."""

_WIDE_VIEW: Final = (120, 30)
"""Full pilot viewport: same world, more visible field."""


def _word(text: str) -> Word:
    """Build a T1 word for ring-wave tests."""
    return Word(text=WordText(text), tier=Tier.T1)


def _angular_gap(first: float, second: float) -> float:
    """Shortest circular distance between two ring angles."""
    return abs((first - second + math.pi) % (2.0 * math.pi) - math.pi)


def test_spawn_count_grows_with_level_capped() -> None:
    """Wave size is 1 + level//2, never above the 8-foe field cap."""
    for level, want in ((1, 1), (2, 2), (3, 2), (4, 3), (30, 8)):
        assert spawn_count_for_level(level) == want


def test_simultaneous_spawn_count() -> None:
    """Level 3 deals 2 foes on the same tick, spread around the ring."""
    words = (_word("alpha"), _word("beta"))
    state = spawn_wave(initial_arena(), words, level=3, start_angle=0.0)
    assert len(state.enemies) == len(words)
    first, second = state.enemies
    assert first.id != second.id
    assert _angular_gap(first.angle, second.angle) >= _MIN_SEPARATION
    assert first.distance == second.distance > 0.0


def test_spawn_radius_viewport_independent() -> None:
    """One world pos maps to the same center-relative cell at 80x24, 120x30."""
    state = spawn_wave(initial_arena(), (_word("alpha"),), level=3)
    foe = state.enemies[0]
    x, y = world_xy(foe)
    small = world_to_cell(x=x, y=y, width=_SMALL_VIEW[0], height=_SMALL_VIEW[1])
    wide = world_to_cell(x=x, y=y, width=_WIDE_VIEW[0], height=_WIDE_VIEW[1])
    assert (small[0] - _SMALL_VIEW[0] // 2, small[1] - _SMALL_VIEW[1] // 2) == (
        wide[0] - _WIDE_VIEW[0] // 2,
        wide[1] - _WIDE_VIEW[1] // 2,
    )


def test_far_spawn_lives_longer() -> None:
    """Outer rings buy more typing time; level 1 matches today's distance."""
    assert spawn_radius_for_level(1) == SPAWN_BASE_RADIUS
    assert spawn_radius_for_level(5) > spawn_radius_for_level(1)
    near = seconds_to_impact(EnemyKind.GRUNT, spawn_radius_for_level(1))
    far = seconds_to_impact(EnemyKind.GRUNT, spawn_radius_for_level(5))
    assert far > near


def test_advance_reports_foe_ids() -> None:
    """Leaks carry stable foe ids, so duplicate words stay attributable."""
    state = spawn_wave(
        initial_arena(),
        (_word("cat"), _word("cat")),
        level=3,
        start_angle=0.0,
    )
    ids = {foe.id for foe in state.enemies}
    assert len(ids) == len(state.enemies)
    after, leaked = advance(state, 60.0)
    assert after.enemies == ()
    assert set(leaked) == ids


def test_duplicate_leaks_count_every_foe() -> None:
    """Two foes sharing a word each bill their own untyped chars on leak."""
    state = spawn_wave(
        initial_arena(),
        (_word("cat"), _word("cat")),
        level=3,
        start_angle=0.0,
    )
    after, leaked = advance(state, 60.0)
    assert after.enemies == ()
    assert leaked_untyped(state, leaked) == len("cat") * len(leaked)
