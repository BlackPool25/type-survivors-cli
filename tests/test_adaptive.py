"""Tests for Task 8 adaptive learning: confidence EMA, spaced repetition, mercy."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Final

import pytest

from tsurv.arena import (
    MERCY_RECOVERY_KEYSTROKES,
    MercyState,
    handle_keystroke,
    initial_arena,
    mercy_note_keystroke,
    mercy_note_stun,
    mercy_spawn_factor,
    mercy_tier,
    spawn_enemy,
)
from tsurv.profile import (
    CONFIDENCE_ALPHA,
    PROFILE_FILENAME,
    REVIEW_MIN_ATTEMPTS,
    KeyStat,
    Profile,
    ProfileError,
    confidence,
    load_profile,
    overdue_by,
    record_keystroke,
    review_due,
    save_profile,
    weak_keys_for_spawn,
)
from tsurv.words import (
    REVIEW_BOOST,
    WEAK_KEY_BOOST,
    Corruption,
    Tier,
    Word,
    WordText,
    pick_word,
    reweight_for_review,
)

_NOW: Final = 1_000_000.0
_SAMPLE_MS: Final = 100.0
_SLOW_MS: Final = 200.0
_TARGET_MS: Final = 100.0
_WRONG_PER_WINDOW: Final = 2
_OLD_REVIEW: Final = _NOW - 10_000_000.0
_SEED: Final = 7


def _stat(
    ema_ms: float | None = _SAMPLE_MS,
    best_ms: float | None = _SAMPLE_MS,
) -> KeyStat:
    """Build a key stat with pinned timing for confidence checks."""
    return KeyStat(presses=1, correct=1, ema_ms=ema_ms, best_ms=best_ms)


def test_confidence_is_one_at_target() -> None:
    """A key typed exactly at target speed reports full confidence."""
    assert confidence(_stat(), _TARGET_MS) == pytest.approx(1.0)


def test_confidence_drops_when_slower() -> None:
    """A key twice as slow as target reports half confidence."""
    stat = _stat(ema_ms=_SLOW_MS, best_ms=_SAMPLE_MS)
    assert confidence(stat, _TARGET_MS) == pytest.approx(0.5)


def test_confidence_caps_at_one_when_faster() -> None:
    """Beating the target never reports above full confidence."""
    stat = _stat(ema_ms=_SAMPLE_MS / 2.0, best_ms=_SAMPLE_MS / 2.0)
    assert confidence(stat, _TARGET_MS) == pytest.approx(1.0)


def test_confidence_zero_without_data() -> None:
    """A fresh key with no timing samples reports zero confidence."""
    assert confidence(KeyStat(), _TARGET_MS) == 0.0


def test_confidence_rejects_non_positive_target() -> None:
    """A zero or negative target speed raises instead of dividing."""
    with pytest.raises(ProfileError):
        _ = confidence(_stat(), 0.0)


def test_ema_first_sample_seeds_mean() -> None:
    """The first in-range timing seeds the EMA directly."""
    profile = record_keystroke(Profile(), "a", correct=True, dt=0.2)
    assert profile.per_key["a"].ema_ms == pytest.approx(_SLOW_MS)


def test_ema_math_uses_alpha() -> None:
    """The second sample moves the mean by alpha toward the sample."""
    profile = record_keystroke(Profile(), "a", correct=True, dt=0.1)
    profile = record_keystroke(profile, "a", correct=True, dt=0.2)
    expected = _SAMPLE_MS + CONFIDENCE_ALPHA * (_SLOW_MS - _SAMPLE_MS)
    assert profile.per_key["a"].ema_ms == pytest.approx(expected)


def test_clamp_rejects_outliers() -> None:
    """Latencies outside the believable window never touch the EMA."""
    profile = record_keystroke(Profile(), "a", correct=True, dt=0.1)
    before = profile.per_key["a"].ema_ms
    assert before is not None
    too_fast = record_keystroke(profile, "a", correct=True, dt=0.01)
    assert too_fast.per_key["a"].ema_ms == pytest.approx(before)
    too_slow = record_keystroke(profile, "a", correct=True, dt=20.0)
    assert too_slow.per_key["a"].ema_ms == pytest.approx(before)


def test_typo_increments_misses_without_timing() -> None:
    """A typo bumps missCount and leaves the smoothed timing alone."""
    profile = record_keystroke(Profile(), "a", correct=True, dt=0.1)
    missed = record_keystroke(profile, "a", correct=False, dt=0.1)
    stat = missed.per_key["a"]
    seeded = profile.per_key["a"].ema_ms
    assert seeded is not None
    assert stat.misses == 1
    assert stat.ema_ms == pytest.approx(seeded)


def test_best_tracks_running_min_of_smoothed() -> None:
    """Best keeps the fastest smoothed value, never a raw sample."""
    profile = record_keystroke(Profile(), "a", correct=True, dt=0.2)
    assert profile.per_key["a"].best_ms == pytest.approx(_SLOW_MS)
    profile = record_keystroke(profile, "a", correct=True, dt=0.1)
    first_best = profile.per_key["a"].best_ms
    assert first_best is not None
    assert first_best < _SLOW_MS
    profile = record_keystroke(profile, "a", correct=True, dt=0.5)
    assert profile.per_key["a"].best_ms == pytest.approx(first_best)


def test_promote_boundary() -> None:
    """Ten attempts at 100% accuracy promote one step and reset the window."""
    profile = Profile()
    for _ in range(REVIEW_MIN_ATTEMPTS):
        profile = record_keystroke(profile, "a", correct=True, dt=0.1, now=_NOW)
    stat = profile.per_key["a"]
    assert stat.review_step == 1
    assert (stat.review_attempts, stat.review_correct) == (0, 0)
    assert stat.last_review == _NOW


def test_no_promote_below_ten_attempts() -> None:
    """Nine perfect attempts are not enough to promote."""
    profile = Profile()
    for _ in range(REVIEW_MIN_ATTEMPTS - 1):
        profile = record_keystroke(profile, "a", correct=True, dt=0.1, now=_NOW)
    assert profile.per_key["a"].review_step == 0


def test_no_promote_below_threshold() -> None:
    """Ten attempts at 90% stay put (below the 98% promote line)."""
    profile = Profile()
    for index in range(REVIEW_MIN_ATTEMPTS):
        profile = record_keystroke(
            profile,
            "a",
            correct=index != 0,
            dt=0.1,
            now=_NOW,
        )
    stat = profile.per_key["a"]
    assert stat.review_step == 0
    assert (stat.review_attempts, stat.review_correct) == (0, 0)


def test_demote_boundary() -> None:
    """Ten attempts at 80% demote one step (below the 85% floor)."""
    profile = Profile(
        per_key={"a": KeyStat(review_step=2, last_review=_OLD_REVIEW)},
    )
    for index in range(REVIEW_MIN_ATTEMPTS):
        profile = record_keystroke(
            profile,
            "a",
            correct=index >= _WRONG_PER_WINDOW,
            dt=0.1,
            now=_NOW,
        )
    stat = profile.per_key["a"]
    assert stat.review_step == 1
    assert (stat.review_attempts, stat.review_correct) == (0, 0)


def test_demote_floors_at_zero() -> None:
    """Demotion never drops below the same-session step."""
    profile = Profile()
    for _ in range(REVIEW_MIN_ATTEMPTS):
        profile = record_keystroke(profile, "a", correct=False, dt=0.1, now=_NOW)
    assert profile.per_key["a"].review_step == 0


def test_review_round_trip(tmp_path_factory: pytest.TempPathFactory) -> None:
    """New timing/schedule fields survive a save/load cycle."""
    profile = Profile()
    for _ in range(REVIEW_MIN_ATTEMPTS):
        profile = record_keystroke(profile, "a", correct=True, dt=0.1, now=_NOW)
    tmp = tmp_path_factory.mktemp("review")
    save_profile(tmp, profile)
    assert load_profile(tmp) == profile


def test_old_save_loads_with_defaults(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Pre-Task-8 saves without the new fields load with fresh defaults."""
    tmp = tmp_path_factory.mktemp("oldsave")
    old = {"gold": 3, "per_key": {"a": {"presses": 5, "correct": 4, "total_time": 0.5}}}
    _ = (tmp / PROFILE_FILENAME).write_text(json.dumps(old), encoding="utf-8")
    profile = load_profile(Path(tmp))
    assert profile.per_key["a"] == KeyStat(presses=5, correct=4, total_time=0.5)


def test_overdue_orders_most_overdue_first() -> None:
    """Due keys sort by how far past their interval they are."""
    profile = Profile(
        per_key={
            "a": KeyStat(
                presses=12,
                correct=12,
                review_step=1,
                last_review=_NOW - 7200.0,
            ),
            "b": KeyStat(
                presses=12,
                correct=12,
                review_step=0,
                last_review=None,
            ),
        },
    )
    assert overdue_by(profile.per_key["b"], _NOW) > overdue_by(
        profile.per_key["a"],
        _NOW,
    )
    assert weak_keys_for_spawn(profile, _NOW)[0] == "b"


def test_review_due_gates_on_interval() -> None:
    """A freshly promoted key is not due until its hour passes."""
    stat = KeyStat(presses=10, correct=10, review_step=1, last_review=_NOW)
    assert review_due(stat, _NOW + 3599.0) is False
    assert review_due(stat, _NOW + 3600.0) is True


def test_review_reweight_boosts_overdue_most() -> None:
    """Overdue-weak words appear strictly more often than merely weak words."""
    candidates = (WordText("axe"), WordText("quiz"), WordText("stone"))
    weighted = reweight_for_review(candidates, ("q", "x"), overdue=("q",))
    assert weighted.count(WordText("quiz")) == WEAK_KEY_BOOST * REVIEW_BOOST
    assert weighted.count(WordText("axe")) == WEAK_KEY_BOOST
    assert weighted.count(WordText("stone")) == 1


def test_review_reweight_never_excludes() -> None:
    """Overdue weighting keeps every candidate eligible at least once."""
    candidates = (WordText("axe"), WordText("stone"))
    assert set(reweight_for_review(candidates, ("x",), overdue=("x",))) == set(
        candidates,
    )


def test_pick_word_accepts_overdue_keys() -> None:
    """Seeded draws with overdue keys still honor every spawn constraint."""
    rng = random.Random(_SEED)  # noqa: S311 - deterministic test RNG
    for _ in range(20):
        word: Word = pick_word(
            Tier.T1,
            (),
            (),
            weak_keys=("q",),
            overdue_keys=("q",),
            rng=rng,
        )
        assert word.text


def test_mercy_triggers_on_three_stuns_in_window() -> None:
    """Three typo-stuns inside 20s flip the valve on (3-in-20s choice)."""
    state = MercyState()
    for offset in (0.0, 5.0, 10.0):
        state = mercy_note_stun(state, _NOW + offset)
    assert state.active is True


def test_mercy_ignores_spread_stuns() -> None:
    """Three stuns spread past the window never trigger mercy."""
    state = MercyState()
    for offset in (0.0, 21.0, 42.0):
        state = mercy_note_stun(state, _NOW + offset)
    assert state.active is False


def test_mercy_recovers_after_clean_keystrokes() -> None:
    """Ten keystrokes at 80%+ accuracy switch the valve back off."""
    state = MercyState(active=True, stuns=(_NOW, _NOW + 1.0, _NOW + 2.0))
    for index in range(MERCY_RECOVERY_KEYSTROKES):
        state = mercy_note_keystroke(state, correct=index >= _WRONG_PER_WINDOW)
    assert state.active is False


def test_mercy_stays_on_after_dirty_window() -> None:
    """A recovery window below 80% keeps mercy on with a fresh count."""
    state = MercyState(active=True)
    for _ in range(MERCY_RECOVERY_KEYSTROKES):
        state = mercy_note_keystroke(state, correct=False)
    assert state.active is True
    assert (state.hits, state.total) == (0, 0)


def test_mercy_never_triggers_in_boss_waves() -> None:
    """Boss waves stay hard: stuns there never arm the valve."""
    state = spawn_enemy(
        initial_arena(boss_wave=True),
        Word(text=WordText("cat"), tier=Tier.T1, corruption=Corruption.CLEAN),
    )
    for index in range(6):
        state, _ = handle_keystroke(state, "c", _NOW + float(index) * 10.0)
        state, _ = handle_keystroke(state, "x", _NOW + float(index) * 10.0 + 1.0)
    assert state.mercy.active is False


def test_mercy_tier_drop_and_spawn_slowdown() -> None:
    """Mercy drops T3 to T2 and slows spawns until it clears."""
    hot = MercyState(active=True)
    assert mercy_tier(Tier.T3, hot) is Tier.T2
    assert mercy_tier(Tier.T2, hot) is Tier.T1
    assert mercy_tier(Tier.T1, hot) is Tier.T1
    assert mercy_spawn_factor(hot) > mercy_spawn_factor(MercyState())
