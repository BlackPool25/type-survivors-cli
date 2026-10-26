"""Tests for the pure combat core (targeting, keystrokes, streaks, pacing)."""

from __future__ import annotations

from tsurv.combat import (
    BASE_SPAWN_INTERVAL,
    ESC,
    SHIELD_DURATION,
    SHIELD_STREAK_EVERY,
    SPAWN_CLAMP_MAX,
    SPAWN_CLAMP_MIN,
    STUN_DURATION,
    Advanced,
    EnemyId,
    EnemyState,
    Keystroke,
    Kill,
    NoTarget,
    TypoStun,
    apply_keystroke,
    keystroke_target,
    lock_target,
    rolling_wpm,
    spawn_interval,
)
from tsurv.words import Tier, Word, WordText


def _enemy(eid: int, text: str, distance: float = 5.0) -> EnemyState:
    """Build one enemy with a T1 word at the given distance."""
    return EnemyState(
        id=EnemyId(eid),
        word=Word(text=WordText(text), tier=Tier.T1),
        hp_words=1,
        distance=distance,
    )


def test_first_letter_locks_target() -> None:
    """The first typed letter locks the enemy whose word starts with it."""
    enemies = (_enemy(0, "cat"), _enemy(1, "dog"))
    assert lock_target("c", enemies, None) == EnemyId(0)
    assert lock_target("d", enemies, None) == EnemyId(1)


def test_first_letter_prefers_nearest() -> None:
    """Shared initials lock the nearest enemy (ties break by lower id)."""
    enemies = (_enemy(0, "snake", distance=5.0), _enemy(1, "storm", distance=2.0))
    assert lock_target("s", enemies, None) == EnemyId(1)


def test_second_letter_disambiguates_pair() -> None:
    """A second letter retargets within the same-initial pair."""
    enemies = (_enemy(0, "snake", distance=1.0), _enemy(1, "storm", distance=9.0))
    assert lock_target("s", enemies, None) == EnemyId(0)
    assert lock_target("t", enemies, EnemyId(0)) == EnemyId(1)
    assert lock_target("n", enemies, EnemyId(0)) == EnemyId(0)


def test_esc_clears_target() -> None:
    """Esc drops the lock and reports no target."""
    enemies = (_enemy(0, "cat"),)
    assert lock_target(ESC, enemies, EnemyId(0)) is None
    result = apply_keystroke(ESC, enemies, EnemyId(0), 1, 0, 10.0, 0.0)
    assert isinstance(result, NoTarget)


def test_correct_char_advances() -> None:
    """Matching chars advance the typed prefix without touching streak."""
    enemies = (_enemy(0, "cat"), _enemy(1, "dog"))
    first = apply_keystroke("c", enemies, None, 0, 0, 10.0, 0.0)
    assert first == Advanced(target=EnemyId(0), typed=1, streak=0)
    second = apply_keystroke("a", enemies, EnemyId(0), 1, 0, 10.5, 0.0)
    assert second == Advanced(target=EnemyId(0), typed=2, streak=0)


def test_wrong_char_stuns_and_resets_streak() -> None:
    """A wrong char jams the gun, resetting the streak (STUN_DURATION)."""
    enemies = (_enemy(0, "cat"),)
    result = apply_keystroke("x", enemies, EnemyId(0), 1, 5, 10.0, 0.0)
    assert result == TypoStun(stun_until=10.0 + STUN_DURATION, streak=0)


def test_focus_rank_shortens_typo_stun() -> None:
    """Focus ranks shrink the jam window through the stun_duration knob."""
    enemies = (_enemy(0, "cat"),)
    result = apply_keystroke(
        "x",
        enemies,
        EnemyId(0),
        1,
        5,
        10.0,
        0.0,
        stun_duration=0.4,
    )
    assert result == TypoStun(stun_until=10.4, streak=0)


def test_completing_word_kills() -> None:
    """Typing the final char kills and bumps the streak."""
    enemies = (_enemy(0, "cat"),)
    assert apply_keystroke("c", enemies, None, 0, 0, 10.0, 0.0) == Advanced(
        target=EnemyId(0),
        typed=1,
        streak=0,
    )
    assert apply_keystroke("a", enemies, EnemyId(0), 1, 0, 10.5, 0.0) == Advanced(
        target=EnemyId(0),
        typed=2,
        streak=0,
    )
    result = apply_keystroke("t", enemies, EnemyId(0), 2, 0, 11.0, 0.0)
    assert isinstance(result, Kill)
    assert result.target == EnemyId(0)
    assert result.streak == 1


def test_stunned_input_is_ignored() -> None:
    """Input during the jam window reports the remaining stun."""
    enemies = (_enemy(0, "cat"),)
    result = apply_keystroke("a", enemies, EnemyId(0), 1, 0, 10.2, 10.0 + STUN_DURATION)
    assert result == TypoStun(stun_until=10.0 + STUN_DURATION, streak=0)


def test_no_match_reports_no_target() -> None:
    """A fresh letter matching nothing locks nothing."""
    enemies = (_enemy(0, "cat"),)
    assert lock_target("z", enemies, None) is None
    assert isinstance(apply_keystroke("z", enemies, None, 0, 0, 10.0, 0.0), NoTarget)


def test_stale_target_falls_back_to_fresh_lock() -> None:
    """An unknown current id behaves like no lock."""
    enemies = (_enemy(0, "cat"),)
    assert lock_target("c", enemies, EnemyId(99)) == EnemyId(0)
    result = apply_keystroke("c", enemies, EnemyId(99), 0, 0, 10.0, 0.0)
    assert result == Advanced(target=EnemyId(0), typed=1, streak=0)


def test_single_char_word_kills_immediately() -> None:
    """A one-letter word is a kill on the locking keystroke."""
    enemies = (_enemy(0, "a"),)
    result = apply_keystroke("a", enemies, None, 0, 3, 10.0, 0.0)
    assert isinstance(result, Kill)
    assert (result.target, result.streak) == (EnemyId(0), 4)


def test_mismatch_retargets_shared_prefix() -> None:
    """A miss on the locked word switches to a prefix-sharing enemy."""
    enemies = (_enemy(0, "snake", distance=1.0), _enemy(1, "sneak", distance=9.0))
    assert apply_keystroke("s", enemies, None, 0, 0, 10.0, 0.0) == Advanced(
        target=EnemyId(0),
        typed=1,
        streak=0,
    )
    assert apply_keystroke("n", enemies, EnemyId(0), 1, 0, 10.1, 0.0) == Advanced(
        target=EnemyId(0),
        typed=2,
        streak=0,
    )
    switched = apply_keystroke("e", enemies, EnemyId(0), 2, 0, 10.2, 0.0)
    assert switched == Advanced(target=EnemyId(1), typed=3, streak=0)


def _kill(text: str, eid: int, streak: int, now: float) -> Kill:
    """Type one whole word fresh and return the Kill outcome."""
    enemies = (_enemy(eid, text),)
    target: EnemyId | None = None
    typed = 0
    result: Keystroke = apply_keystroke(
        text[0],
        enemies,
        target,
        typed,
        streak,
        now,
        0.0,
    )
    for letter in text[1:]:
        assert isinstance(result, Advanced)
        target, typed = result.target, result.typed
        result = apply_keystroke(letter, enemies, target, typed, streak, now, 0.0)
    assert isinstance(result, Kill)
    return result


def test_streak_eighth_kill_grants_shield() -> None:
    """The kill reaching a multiple-of-8 streak shields for 1s."""
    kill = _kill("cat", 0, SHIELD_STREAK_EVERY - 1, 100.0)
    assert kill.streak == SHIELD_STREAK_EVERY
    assert kill.shield_until == 100.0 + SHIELD_DURATION


def test_non_milestone_kill_grants_no_shield() -> None:
    """Other kills bump the streak with no shield."""
    kill = _kill("cat", 0, 6, 100.0)
    assert (kill.streak, kill.shield_until) == (7, 0.0)


def test_sixteenth_kill_shields_again() -> None:
    """Every multiple of 8 shields, not just the first."""
    kill = _kill("cat", 0, 15, 50.0)
    assert (kill.streak, kill.shield_until) == (16, 50.0 + SHIELD_DURATION)


def test_rolling_wpm_over_word_completions() -> None:
    """WPM is completions per minute from the oldest kept timestamp."""
    now = 1000.0
    events = [now - 57.0 + 3.0 * i for i in range(20)]
    assert rolling_wpm(events, now) == 20.0 / 57.0 * 60.0


def test_rolling_wpm_keeps_last_twenty() -> None:
    """Only the trailing 20 timestamps count."""
    now = 1000.0
    events = [now - 24.0 + float(i) for i in range(25)]
    assert rolling_wpm(events, now) == 20.0 / 19.0 * 60.0


def test_rolling_wpm_needs_history() -> None:
    """Empty, single, or future-only histories report zero."""
    assert rolling_wpm([], 100.0) == 0.0
    assert rolling_wpm([99.0], 100.0) == 0.0
    assert rolling_wpm([101.0, 102.0], 100.0) == 0.0


def test_spawn_interval_parity_is_base() -> None:
    """Matching player and reference WPM spawns at the base gap."""
    assert spawn_interval(60.0, 60.0) == BASE_SPAWN_INTERVAL


def test_spawn_interval_clamps() -> None:
    """Faster players floor at 0.6x; slower (or idle) cap at 1.6x."""
    assert spawn_interval(60.0, 600.0) == BASE_SPAWN_INTERVAL * SPAWN_CLAMP_MIN
    assert spawn_interval(60.0, 100.0) == BASE_SPAWN_INTERVAL * SPAWN_CLAMP_MIN
    assert spawn_interval(600.0, 60.0) == BASE_SPAWN_INTERVAL * SPAWN_CLAMP_MAX
    assert spawn_interval(60.0, 0.0) == BASE_SPAWN_INTERVAL * SPAWN_CLAMP_MAX


def test_keystroke_target_extracts_lock() -> None:
    """Advanced/Kill carry their enemy; stuns and misses carry none."""
    assert keystroke_target(Advanced(target=EnemyId(0), typed=1, streak=0)) == EnemyId(
        0,
    )
    kill = Kill(target=EnemyId(1), streak=8, shield_until=101.0)
    assert keystroke_target(kill) == EnemyId(1)
    assert keystroke_target(TypoStun(stun_until=10.0 + STUN_DURATION, streak=0)) is None
    assert keystroke_target(NoTarget()) is None


def test_esc_during_stun_stays_jammed() -> None:
    """The jam window blocks every key, including Esc."""
    enemies = (_enemy(0, "cat"),)
    result = apply_keystroke(ESC, enemies, EnemyId(0), 1, 0, 10.2, 10.0 + STUN_DURATION)
    assert result == TypoStun(stun_until=10.0 + STUN_DURATION, streak=0)
