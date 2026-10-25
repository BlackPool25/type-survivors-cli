"""Tests for skill-gated kill rewards: accuracy bands, streak ladder, gate."""

from __future__ import annotations

import asyncio
from typing import Final

import pytest

from tsurv.app import ArenaScreen, TypeSurvivorsApp
from tsurv.arena import chain_lightning, handle_keystroke, initial_arena, spawn_enemy
from tsurv.combat import Kill
from tsurv.items import NOVA_CHARGE_SECONDS, nova_charge, nova_ready
from tsurv.reward import (
    accuracy_band,
    consistency_gate,
    score_kill,
    streak_multiplier,
)
from tsurv.words import Tier, Word, WordText

_NOW: Final = 100.0
_GOLD: Final = "cat"
_SLOPPY_ACC: Final = 0.79
_STEADY_CONSIST: Final = 80.0
_BAND_FULL: Final = 100
_BAND_HIGH: Final = 80
_BAND_MID: Final = 60
_BAND_LOW: Final = 40
_BAND_EDGE: Final = 0.8
_STREAK_FULL: Final = 800
_GATE_HALF: Final = 0.5
_X4: Final = 4.0
_X8: Final = 8.0
_X16: Final = 16.0
_CHARGED: Final = 5.0


def _word(text: str) -> Word:
    """Build a T1 word for reward scenarios."""
    return Word(text=WordText(text), tier=Tier.T1)


def _kill(
    text: str,
    accuracy: float = 1.0,
    consistency: float | None = None,
) -> int:
    """Type a full word in the arena, return the score gained on the kill."""
    state = spawn_enemy(initial_arena(), _word(text))
    before = int(state.score)
    outcome: object = None
    for index, char in enumerate(text):
        state, outcome = handle_keystroke(
            state,
            char,
            _NOW + float(index),
            accuracy=accuracy,
            consistency=consistency,
        )
    assert isinstance(outcome, Kill)
    return int(state.score) - before


def test_sloppy_wave_earns_zero_bonus() -> None:
    """A kill at 79% accuracy banks nothing (band floor is 80%)."""
    assert _kill(_GOLD, accuracy=_SLOPPY_ACC, consistency=_STEADY_CONSIST) == 0


def test_bands_step_down() -> None:
    """Each accuracy boundary pays its exact band (95/90/85/80, else zero)."""
    assert score_kill(10, 0.95, 1.0, None) == _BAND_FULL
    assert score_kill(10, 0.90, 1.0, None) == _BAND_HIGH
    assert score_kill(10, 0.85, 1.0, None) == _BAND_MID
    assert score_kill(10, 0.80, 1.0, None) == _BAND_LOW
    assert score_kill(10, 0.7999, 1.0, None) == 0
    assert accuracy_band(0.949) == _BAND_EDGE
    assert accuracy_band(0.50) == 0.0


def test_low_consistency_halves_streak() -> None:
    """Consistency under 60 halves the kill; 60+ and rough pay in full."""
    full = score_kill(10, 1.0, 8.0, 80.0)
    assert full == _STREAK_FULL
    assert score_kill(10, 1.0, 8.0, 59.9) == full // 2
    assert score_kill(10, 1.0, 8.0, 60.0) == full
    assert score_kill(10, 1.0, 8.0, None) == full
    assert consistency_gate(None) == 1.0
    assert consistency_gate(0.0) == _GATE_HALF


def test_streak_ladder_rungs() -> None:
    """The x4/x8/x16 ladder multiplies clean flow; short streaks pay base."""
    assert streak_multiplier(0) == 1.0
    assert streak_multiplier(3) == 1.0
    assert streak_multiplier(4) == _X4
    assert streak_multiplier(8) == _X8
    assert streak_multiplier(16) == _X16
    with pytest.raises(ValueError, match="streak must be non-negative"):
        _ = streak_multiplier(-1)
    with pytest.raises(ValueError, match="char count must be non-negative"):
        _ = score_kill(-1, 1.0, 1.0, None)
    with pytest.raises(ValueError, match="accuracy"):
        _ = score_kill(3, 1.5, 1.0, None)


def test_clean_kill_pays_base_by_default() -> None:
    """Perfect accuracy with no history keeps the legacy chars*10 payout."""
    assert _kill(_GOLD) == len(_GOLD) * 10


def test_chain_lightning_uses_bands() -> None:
    """Chain arcs score through the same gate: sloppy chains pay nothing."""
    state = initial_arena()
    for text in ("aaa", "bbb", "ccc"):
        state = spawn_enemy(state, _word(text))
    sloppy, _ = chain_lightning(state, state.enemies[0].id, accuracy=_SLOPPY_ACC)
    assert int(sloppy.score) == int(state.score)
    clean, _ = chain_lightning(state, state.enemies[0].id, accuracy=1.0)
    assert int(clean.score) - int(state.score) == (3 + 3) * 10


def test_nova_charge_tracks_net_accuracy() -> None:
    """Only seconds at/above 95% net accuracy charge NOVA toward 30s."""
    assert nova_charge(0.0, 1.0, 1.0) == 1.0
    assert nova_charge(_CHARGED, 0.50, 1.0) == _CHARGED
    assert nova_ready(0.95, nova_charge(29.0, 0.95, 1.0)) is True
    assert nova_ready(0.949, NOVA_CHARGE_SECONDS + 30.0) is False


def test_pilot_clean_kill_pays_base() -> None:
    """End to end: a clean pilot kill banks chars*10 (band 1, streak 1)."""

    async def _scenario() -> int:
        app = TypeSurvivorsApp(initial_words=(_GOLD,), spawn_enabled=False)
        async with app.run_test() as pilot:
            for char in _GOLD:
                await pilot.press(char)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.nova_armed is False
            return screen.score_value

    assert asyncio.run(_scenario()) == len(_GOLD) * 10


def test_pilot_mashed_run_earns_nothing() -> None:
    """End to end: mashing extras tanks accuracy, so the kill pays zero."""

    async def _scenario() -> int:
        app = TypeSurvivorsApp(initial_words=(_GOLD,), spawn_enabled=False)
        async with app.run_test() as pilot:
            for _ in range(3):
                await pilot.press("z")
            for char in _GOLD:
                await pilot.press(char)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            return screen.score_value

    assert asyncio.run(_scenario()) == 0
