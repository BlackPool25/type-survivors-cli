"""Pure combat core: targeting, keystrokes, streaks, pacing (no Textual imports)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NewType, assert_never

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tsurv.words import Word

EnemyId = NewType("EnemyId", int)
"""Stable handle for one on-screen enemy."""

ESC: Final = "\x1b"
"""Key that drops the current target."""

STUN_DURATION: Final = 0.6
"""Gun-jam window after a typo, in seconds."""

SHIELD_DURATION: Final = 1.0
"""Shield granted by streak milestones, in seconds."""

SHIELD_STREAK_EVERY: Final = 8
"""Every Nth streak kill grants a shield."""

WPM_WINDOW: Final = 20
"""Rolling WPM counts completions over this many trailing words."""

WPM_MIN_SAMPLES: Final = 2
"""Rolling WPM needs at least this many timestamps, else it reports zero."""

BASE_SPAWN_INTERVAL: Final = 2.0
"""Spawn gap in seconds at parity between player and reference WPM."""

SPAWN_CLAMP_MIN: Final = 0.6
"""Spawn interval never drops below base times this."""

SPAWN_CLAMP_MAX: Final = 1.6
"""Spawn interval never rises above base times this."""


@dataclass(frozen=True, slots=True)
class EnemyState:
    """One on-screen enemy: its word, remaining bars, and threat distance."""

    id: EnemyId
    word: Word
    hp_words: int
    distance: float


@dataclass(frozen=True, slots=True)
class Advanced:
    """A correct char extended the typed prefix (word still alive)."""

    target: EnemyId
    typed: int
    streak: int


@dataclass(frozen=True, slots=True)
class Kill:
    """A completed word killed its enemy and bumped the streak."""

    target: EnemyId
    streak: int
    shield_until: float


@dataclass(frozen=True, slots=True)
class TypoStun:
    """A wrong char jammed the gun; the streak reset to zero."""

    stun_until: float
    streak: int


@dataclass(frozen=True, slots=True)
class NoTarget:
    """The key matched nothing (or cleared the lock); no state changed."""


Keystroke = Advanced | Kill | TypoStun | NoTarget
"""Outcome of one keystroke against the arena."""


def _by_id(enemies: Sequence[EnemyState], target: EnemyId) -> EnemyState | None:
    """Return the enemy with this id, or None once it is gone."""
    for enemy in enemies:
        if enemy.id == target:
            return enemy
    return None


def _nearest(enemies: Sequence[EnemyState]) -> EnemyState:
    """Pick the closest enemy, breaking ties by lower id (needs ≥1 enemy)."""
    return min(enemies, key=lambda enemy: (enemy.distance, enemy.id))


def _check_key(ch: str) -> None:
    """Reject anything that is not one keypress (Esc counts as one)."""
    if len(ch) != 1:
        msg = f"keystroke must be one character, got {ch!r}"
        raise ValueError(msg)


def lock_target(
    ch: str,
    enemies: Sequence[EnemyState],
    current: EnemyId | None,
) -> EnemyId | None:
    """Pick which enemy a keypress refers to (Esc clears the lock).

    First letters lock the nearest word starting with them; when a lock
    exists, a letter matching another same-initial word's second letter
    disambiguates the pair. Unrelated keys keep a live lock sticky.
    """
    if ch == ESC:
        return None
    _check_key(ch)
    if current is not None:
        locked = _by_id(enemies, current)
        if locked is not None:
            initial = locked.word.text[:1]
            pair = [
                enemy
                for enemy in enemies
                if enemy.word.text.startswith(initial) and len(enemy.word.text) > 1
            ]
            if pair:
                for enemy in sorted(pair, key=lambda e: (e.distance, e.id)):
                    if enemy.word.text[1] == ch:
                        return enemy.id
            fresh = [enemy for enemy in enemies if enemy.word.text.startswith(ch)]
            if fresh:
                return _nearest(fresh).id
            return current
    fresh = [enemy for enemy in enemies if enemy.word.text.startswith(ch)]
    if fresh:
        return _nearest(fresh).id
    return None


def _advance(enemy: EnemyState, typed: int, streak: int, now: float) -> Advanced | Kill:
    """Build the outcome for reaching a longer typed prefix."""
    if typed >= len(enemy.word.text):
        streak += 1
        shield = now + SHIELD_DURATION if streak % SHIELD_STREAK_EVERY == 0 else 0.0
        return Kill(target=enemy.id, streak=streak, shield_until=shield)
    return Advanced(target=enemy.id, typed=typed, streak=streak)


def apply_keystroke(  # noqa: PLR0913, PLR0917 - seven explicit params per ruling
    ch: str,
    enemies: Sequence[EnemyState],
    current: EnemyId | None,
    typed: int,
    streak: int,
    now: float,
    stunned_until: float = 0.0,
) -> Keystroke:
    """Resolve one keypress in order: stun gate, Esc, lock, advance/kill/typo.

    Progress rides on `typed` (the locked word's matched prefix length);
    completing a word is always a Kill, and a miss on the locked word
    retargets to a prefix-sharing enemy before counting as a typo.
    """
    if now < stunned_until:
        return TypoStun(stun_until=stunned_until, streak=0)
    if ch == ESC:
        return NoTarget()
    _check_key(ch)
    locked = _by_id(enemies, current) if current is not None else None
    outcome: Keystroke
    if locked is None:
        target_id = lock_target(ch, enemies, current)
        found = _by_id(enemies, target_id) if target_id is not None else None
        outcome = _advance(found, 1, streak, now) if found is not None else NoTarget()
    else:
        word = locked.word.text
        if typed < len(word) and word[typed] == ch:
            outcome = _advance(locked, typed + 1, streak, now)
        else:
            prefix = word[:typed]
            alts = [
                enemy
                for enemy in enemies
                if enemy.id != locked.id
                and enemy.word.text.startswith(prefix)
                and len(enemy.word.text) > typed
                and enemy.word.text[typed] == ch
            ]
            if alts:
                outcome = _advance(_nearest(alts), typed + 1, streak, now)
            else:
                outcome = TypoStun(stun_until=now + STUN_DURATION, streak=0)
    return outcome


def keystroke_target(result: Keystroke) -> EnemyId | None:
    """Extract the locked enemy from any keystroke outcome (exhaustive)."""
    match result:
        case Advanced(target=target) | Kill(target=target):
            return target
        case TypoStun() | NoTarget():
            return None
        case _:
            assert_never(result)


def rolling_wpm(events: Sequence[float], now: float) -> float:
    """Completions per minute over the trailing words (at most 20).

    `events` must be chronological: the tail slice keeps the latest entries.
    """
    recent = [moment for moment in events if moment <= now][-WPM_WINDOW:]
    if len(recent) < WPM_MIN_SAMPLES:
        return 0.0
    elapsed = now - recent[0]
    if elapsed <= 0.0:
        return 0.0
    return float(len(recent)) / elapsed * 60.0


def spawn_interval(ref_wpm: float, player_wpm: float) -> float:
    """Spawn gap: base scaled by ref/player, clamped to 0.6x-1.6x.

    An idle player (no WPM yet) spawns at the slowest cap, never crashing.
    """
    ratio = ref_wpm / player_wpm if player_wpm > 0.0 else SPAWN_CLAMP_MAX
    return BASE_SPAWN_INTERVAL * min(max(ratio, SPAWN_CLAMP_MIN), SPAWN_CLAMP_MAX)
