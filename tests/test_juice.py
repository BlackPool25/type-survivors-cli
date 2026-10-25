"""Game-feel juice: telegraphs, hit-stop, knockback, shake, slow-mo, calibration.

TDD RED: tsurv.juice does not exist yet, so every import from it fails until
the module (plus its app/arena/profile wiring) lands.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import replace
from typing import Final

import pytest
from textual import events

from tsurv.app import BOSS_EVERY, ArenaScreen, TypeSurvivorsApp
from tsurv.arena import EnemyKind, seconds_to_impact
from tsurv.combat import SHIELD_STREAK_EVERY
from tsurv.juice import (
    HIT_STOP_S,
    PARTICLE_BURST,
    SLOW_MO_S,
    SLOW_MO_SCALE,
    TELEGRAPH_S,
    JuiceState,
    Seconds,
    apply_calibration,
    calibrate_base_wpm,
    is_bar_break,
    low_hp,
    spawn_burst,
    step_juice,
    telegraph_seconds,
    telegraph_showing,
    time_scale,
    trigger_bar_break,
    trigger_kill,
)
from tsurv.profile import Profile, ProfileError

_NOW: Final = 100.0
_IMPACT_CLOSE: Final = 0.05
_IMPACT_FAR: Final = 5.0
_GRUNT_IMPACT_AT_FIVE: Final = 5.0
_BOSS_IMPACT_AT_EIGHT: Final = 20.0
_RANK1_BARS: Final = 3
_SPAWN_GAP_TICK: Final = 3.5
_HIT_STOP_WAIT: Final = 0.12
_WAVE_SECONDS: Final = 30.0
_LOW_HP: Final = 30.0
_JUST_ABOVE_LOW_HP: Final = 31.0
_FULL_HP: Final = 100.0
_CAL_A: Final = 10.0
_CAL_B: Final = 70.0
_CAL_C: Final = 130.0
_EXPECTED_CAL_MEAN: Final = 1.0
_STEADY_WPM: Final = 60.0
_NEGATIVE_WPM: Final = -5.0
_SEED: Final = 7
_WAVE_TWO: Final = 2


def test_telegraph_meets_200ms_floor_all_kinds() -> None:
    """Every kind rears up at least 200ms (grunt verbatim) before it can leak."""
    for kind in EnemyKind:
        duration = telegraph_seconds(kind)
        assert isinstance(duration, float)
        assert duration >= Seconds(0.2)
    assert telegraph_seconds(EnemyKind.GRUNT) == TELEGRAPH_S


def test_telegraph_shows_only_inside_final_approach() -> None:
    """The warning appears during the last telegraph window, never after leak."""
    assert telegraph_showing(_IMPACT_CLOSE, EnemyKind.GRUNT)
    assert telegraph_showing(TELEGRAPH_S, EnemyKind.GRUNT)
    assert not telegraph_showing(TELEGRAPH_S + _IMPACT_CLOSE, EnemyKind.GRUNT)
    assert not telegraph_showing(_IMPACT_FAR, EnemyKind.GRUNT)
    assert not telegraph_showing(0.0, EnemyKind.GRUNT)


def test_seconds_to_impact_uses_live_speed() -> None:
    """Arena helper divides distance by the kind's real speed (no tables)."""
    assert seconds_to_impact(EnemyKind.GRUNT, _IMPACT_FAR) == _GRUNT_IMPACT_AT_FIVE
    assert seconds_to_impact(EnemyKind.BOSS, 8.0) == _BOSS_IMPACT_AT_EIGHT


def test_bar_break_sets_knockback_and_hit_stop() -> None:
    """Burning a bar raises the knockback flag inside an 80ms freeze window."""
    rng = random.Random(_SEED)  # noqa: S311
    effect = trigger_bar_break(JuiceState(), _NOW, rng)
    assert effect.knockback_until == _NOW + HIT_STOP_S
    assert effect.hit_stop_until == _NOW + HIT_STOP_S
    assert effect.flash_until == _NOW + HIT_STOP_S
    assert effect.trauma == 1.0
    assert len(effect.particles) == PARTICLE_BURST


def test_hit_stop_freezes_then_releases() -> None:
    """Keys land during the ~80ms freeze; the sim resumes the instant it ends."""
    rng = random.Random(_SEED)  # noqa: S311
    frozen = trigger_bar_break(JuiceState(), _NOW, rng)
    assert frozen.frozen_at(_NOW + HIT_STOP_S - 0.001)
    assert not frozen.frozen_at(_NOW + HIT_STOP_S)


def test_streak_eight_kill_arms_half_second_slow_mo() -> None:
    """The x8 streak milestone (shared with the shield) slows time for 0.5s."""
    calm = trigger_kill(JuiceState(), SHIELD_STREAK_EVERY - 1, _NOW)
    assert calm.slow_mo_until == 0.0
    assert time_scale(calm, _NOW) == 1.0
    slow = trigger_kill(JuiceState(), SHIELD_STREAK_EVERY, _NOW)
    assert slow.slow_mo_until == _NOW + SLOW_MO_S
    assert time_scale(slow, _NOW) == SLOW_MO_SCALE
    assert time_scale(slow, _NOW + SLOW_MO_S) == 1.0


def test_trauma_shakes_then_settles() -> None:
    """Kills rattle the screen; a quiet second clears the trauma fully."""
    rung = trigger_kill(JuiceState(), 1, _NOW)
    assert rung.shake_active
    assert not JuiceState().shake_active
    assert not step_juice(rung, 1.0).shake_active


def test_particles_age_out_after_burst() -> None:
    """A knockback burst is one-shot: every mote dies within a second."""
    rng = random.Random(_SEED)  # noqa: S311
    burst = spawn_burst(rng)
    assert len(burst) == PARTICLE_BURST
    assert step_juice(JuiceState(particles=burst), 1.0).particles == ()


def test_low_hp_pulse_threshold() -> None:
    """The pulse fires at/below 30% vitals, never on a corpse or full bar."""
    assert low_hp(_LOW_HP, _FULL_HP)
    assert not low_hp(_JUST_ABOVE_LOW_HP, _FULL_HP)
    assert not low_hp(_FULL_HP, _FULL_HP)
    assert not low_hp(0.0, _FULL_HP)


def test_bar_break_covers_boss_kills_and_bar_burns() -> None:
    """Boss kills and multi-word burns blast; plain grunt kills only rattle."""
    assert is_bar_break(EnemyKind.BOSS, 1)
    assert is_bar_break(EnemyKind.HEX, 2)
    assert not is_bar_break(EnemyKind.GRUNT, 1)


def test_calibration_measures_mean_word_rate() -> None:
    """Steady one-word-per-second play calibrates to exactly 1 WPM."""
    assert calibrate_base_wpm(()) == 0.0
    assert calibrate_base_wpm((_CAL_A,)) == 0.0
    steady = (_CAL_A, _CAL_B, _CAL_C)
    assert calibrate_base_wpm(steady) == _EXPECTED_CAL_MEAN
    assert calibrate_base_wpm((0.0, 1.0, 2.0)) == _STEADY_WPM


def test_calibration_rejects_negative_and_old_saves_load_none() -> None:
    """Bad rates raise; saves written before the field existed load as None."""
    with pytest.raises(ProfileError):
        _ = apply_calibration(Profile(), _NEGATIVE_WPM)
    assert Profile.model_validate_json("{}").base_wpm is None
    assert apply_calibration(Profile(), _STEADY_WPM).base_wpm == _STEADY_WPM


def test_pilot_telegraph_marks_close_foe() -> None:
    """A grunt inside its 200ms impact window gets the on-screen ! marker."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(spawn_enabled=False, seed=_SEED)
        async with app.run_test() as pilot:
            del pilot
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.spawn_test_enemy("cat", distance=_IMPACT_FAR)
            screen.spawn_test_enemy("zz", distance=_IMPACT_CLOSE)
            assert screen.foes_text.count("!") == 1

    asyncio.run(_scenario())


def test_pilot_bar_burn_freezes_tick() -> None:
    """Burning a boss bar on screen freezes foe motion for ~80ms, then frees."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=_SEED)
        async with app.run_test() as pilot:
            del pilot
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.set_restored(replace(screen.arena_state, wave=BOSS_EVERY))
            screen.tick(_SPAWN_GAP_TICK)
            assert len(screen.arena_state.enemies) == 1
            foe = screen.arena_state.enemies[0]
            assert foe.kind is EnemyKind.BOSS
            raw = str(foe.word.text)
            for char in raw:
                await screen.on_key(events.Key(char, char))
            assert screen.arena_state.enemies[0].hp_words == _RANK1_BARS - 1
            assert screen.knockback_active
            assert screen.hit_stop_active
            held = screen.arena_state.enemies[0].distance
            screen.tick(0.01)
            assert screen.arena_state.enemies[0].distance == held
            await asyncio.sleep(_HIT_STOP_WAIT)
            assert not screen.hit_stop_active
            screen.tick(0.01)
            assert screen.arena_state.enemies[0].distance < held

    asyncio.run(_scenario())


def test_pilot_wave1_calibrates_base_wpm() -> None:
    """Clearing wave 1 writes the measured base rate onto the profile."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(spawn_enabled=False, seed=_SEED)
        async with app.run_test() as pilot:
            del pilot
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert app.profile.base_wpm is None
            while screen.arena_state.enemies:
                foe = screen.arena_state.enemies[0]
                for char in str(foe.word.text):
                    await screen.on_key(events.Key(char, char))
            screen.tick(_WAVE_SECONDS)
            assert screen.arena_state.wave == _WAVE_TWO
            assert app.profile.base_wpm is not None
            assert app.profile.base_wpm >= 0.0

    asyncio.run(_scenario())


def test_pilot_wave5_boss_full_playthrough() -> None:
    """Wave-5 boss: 3 bars, every burn knocks back, kill clears, wave 6 runs.

    Pacing invariants: the boss needs exactly `bars` phrase completions
    (killable inside its bars) and the lane never sits empty mid-fight.
    """

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=_SEED)
        async with app.run_test() as pilot:
            del pilot
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.set_restored(replace(screen.arena_state, wave=BOSS_EVERY))
            screen.tick(_SPAWN_GAP_TICK)
            assert screen.arena_state.boss_wave
            foe = screen.arena_state.enemies[0]
            assert foe.kind is EnemyKind.BOSS
            assert foe.hp_words == _RANK1_BARS
            raw = str(foe.word.text)
            assert raw
            for bar in range(_RANK1_BARS, 0, -1):
                assert len(screen.arena_state.enemies) == 1
                for char in raw:
                    await screen.on_key(events.Key(char, char))
                assert screen.knockback_active
                await asyncio.sleep(_HIT_STOP_WAIT)
                if bar > 1:
                    assert screen.arena_state.enemies[0].hp_words == bar - 1
            assert screen.arena_state.kills == 1
            assert screen.arena_state.enemies == ()
            screen.tick(1.0)
            assert screen.arena_state.wave == BOSS_EVERY + 1
            assert not screen.arena_state.boss_wave

    asyncio.run(_scenario())
