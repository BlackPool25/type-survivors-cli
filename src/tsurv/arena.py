"""Arena state: pure endless-loop mechanics wiring words/combat/items."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from math import cos, pi, sin
from typing import Final, NewType, assert_never

from tsurv.combat import (
    Advanced,
    EnemyId,
    EnemyState,
    Keystroke,
    Kill,
    NoTarget,
    TypoStun,
    apply_keystroke,
)
from tsurv.items import ItemKind, TriggerResult, trigger
from tsurv.reward import score_kill, streak_multiplier
from tsurv.words import Corruption, Tier, Word

Score = NewType("Score", int)
"""Run score: word-length points accumulated per kill."""


class EnemyKind(StrEnum):
    """On-screen enemy shape (identity is shape + icon, never color-only)."""

    GRUNT = "GRUNT"
    MITE = "MITE"
    HEX = "HEX"
    ELITE = "ELITE"
    BOSS = "BOSS"


LEAK_DAMAGE: Final = 10.0
"""HP lost when one enemy reaches the Sanctuary Core."""

MERCY_STUNS: Final = 3
"""Typo-stuns inside the rolling window that arm the mercy valve."""

MERCY_WINDOW_S: Final = 20.0
"""Rolling seconds over which typo-stuns count toward mercy."""

MERCY_RECOVERY_KEYSTROKES: Final = 10
"""Resolved keystrokes per recovery window while mercy is active."""

MERCY_RECOVERY_ACC: Final = 0.8
"""Recovery-window accuracy that switches the valve back off."""

MERCY_SPAWN_SLOWDOWN: Final = 1.5
"""Spawn-gap multiplier while mercy is active (slower spawns)."""

ELITE_DROP_RATE: Final = 0.10
"""Elite Chain Spark drop chance per kill (~10%)."""

MAX_SIMULTANEOUS: Final = 8
"""Field cap: one wave never deals more foes than the viewport holds."""

SPAWN_BASE_RADIUS: Final = 5.0
"""Level-1 ring distance: today's spawn gap, so impact seconds carry over."""

SPAWN_RADIUS_STEP: Final = 0.5
"""World units added per level past the first: outer rings buy typing time."""


def _speed_of(kind: EnemyKind) -> float:
    """Convergence speed in distance units per second (exhaustive)."""
    match kind:
        case EnemyKind.GRUNT:
            return 1.0
        case EnemyKind.MITE:
            return 1.6
        case EnemyKind.HEX:
            return 0.6
        case EnemyKind.ELITE:
            return 1.0
        case EnemyKind.BOSS:
            return 0.4
        case _:
            assert_never(kind)


def seconds_to_impact(kind: EnemyKind, distance: float) -> float:
    """Seconds until a foe at `distance` leaks (Task 7 telegraph hook)."""
    return distance / _speed_of(kind)


def spawn_count_for_level(level: int) -> int:
    """Simultaneous wave size: 1 + level//2, capped at the field cap."""
    return min(max(1 + level // 2, 1), MAX_SIMULTANEOUS)


def spawn_radius_for_level(level: int) -> float:
    """Ring radius in world units: today's distance at level 1, wider later."""
    return SPAWN_BASE_RADIUS + SPAWN_RADIUS_STEP * float(max(level - 1, 0))


def world_xy(foe: ArenaEnemy) -> tuple[float, float]:
    """World-space position of a foe (polar sim state to camera input)."""
    return (foe.distance * cos(foe.angle), foe.distance * sin(foe.angle))


@dataclass(frozen=True, slots=True)
class ArenaEnemy:
    """One foe: its kind, word, remaining bars, and threat distance."""

    id: EnemyId
    kind: EnemyKind
    word: Word
    hp_words: int
    distance: float
    angle: float = 0.0

    def to_combat(self) -> EnemyState:
        """Project onto the combat core's enemy view."""
        return EnemyState(
            id=self.id,
            word=self.word,
            hp_words=self.hp_words,
            distance=self.distance,
        )


@dataclass(frozen=True, slots=True)
class MercyState:
    """Mercy valve: rolling typo-stun timestamps plus recovery progress.

    Three stuns inside 20s arm the valve (slower spawns, easier tiers)
    until a 10-keystroke window clears 80% accuracy. Never arms during
    boss waves — bosses stay hard.
    """

    stuns: tuple[float, ...] = ()
    active: bool = False
    hits: int = 0
    total: int = 0

    def __post_init__(self) -> None:
        """Reject negative recovery tallies and hits above total."""
        if self.hits < 0 or self.total < 0 or self.hits > self.total:
            msg = f"invalid mercy window: {self.total} keys, {self.hits} hits"
            raise ValueError(msg)


def mercy_note_stun(state: MercyState, now: float) -> MercyState:
    """Record a fresh typo-stun; three inside the window arm the valve."""
    recent = tuple(
        moment for moment in (*state.stuns, now) if now - moment <= MERCY_WINDOW_S
    )
    if state.active:
        return replace(state, stuns=recent)
    if len(recent) >= MERCY_STUNS:
        return MercyState(stuns=recent, active=True)
    return replace(state, stuns=recent)


def mercy_note_keystroke(state: MercyState, *, correct: bool) -> MercyState:
    """Count one resolved keystroke; a clean window switches the valve off."""
    if not state.active:
        return state
    hits = state.hits + (1 if correct else 0)
    total = state.total + 1
    if total < MERCY_RECOVERY_KEYSTROKES:
        return replace(state, hits=hits, total=total)
    if hits / total >= MERCY_RECOVERY_ACC:
        return MercyState()
    return replace(state, hits=0, total=0)


def mercy_tier(tier: Tier, mercy: MercyState) -> Tier:
    """Drop one difficulty tier while mercy is active (boss tiers untouched)."""
    if not mercy.active:
        return tier
    match tier:
        case Tier.T3:
            return Tier.T2
        case Tier.T2:
            return Tier.T1
        case Tier.T1 | Tier.CODE | Tier.BOSS:
            return tier
        case _:
            assert_never(tier)


def mercy_spawn_factor(mercy: MercyState) -> float:
    """Spawn-gap multiplier: slower spawns while mercy is active."""
    return MERCY_SPAWN_SLOWDOWN if mercy.active else 1.0


@dataclass(frozen=True, slots=True)
class ArenaState:
    """Full endless-loop state: foes, score, vitals, locks, effect windows."""

    enemies: tuple[ArenaEnemy, ...] = ()
    score: Score = Score(0)
    kills: int = 0
    streak: int = 0
    wave: int = 1
    hp: float = 100.0
    max_hp: float = 100.0
    revives_used: int = 0
    shield_until: float = 0.0
    frost_until: float = 0.0
    stunned_until: float = 0.0
    current: EnemyId | None = None
    typed: int = 0
    next_id: int = 0
    boss_wave: bool = False
    mercy: MercyState = MercyState()


def initial_arena(
    hp: float = 100.0,
    streak: int = 0,
    shield_until: float = 0.0,
    frost_until: float = 0.0,
    *,
    boss_wave: bool = False,
) -> ArenaState:
    """Build an empty arena at full health with the given streak/windows."""
    return ArenaState(
        hp=hp,
        streak=streak,
        shield_until=shield_until,
        frost_until=frost_until,
        boss_wave=boss_wave,
    )


def spawn_enemy(
    state: ArenaState,
    word: Word,
    kind: EnemyKind = EnemyKind.GRUNT,
    hp_words: int = 1,
    distance: float = 5.0,
) -> ArenaState:
    """Append one foe, handing out the next stable enemy id."""
    foe = ArenaEnemy(
        id=EnemyId(state.next_id),
        kind=kind,
        word=word,
        hp_words=hp_words,
        distance=distance,
    )
    return replace(state, enemies=(*state.enemies, foe), next_id=state.next_id + 1)


def spawn_wave(
    state: ArenaState,
    words: tuple[Word, ...],
    level: int,
    start_angle: float = 0.0,
    kind: EnemyKind = EnemyKind.GRUNT,
) -> ArenaState:
    """Deal one simultaneous ring wave: even spread on the level radius.

    The caller deals the words (uniqueness stays the spawner's job); the
    ring owns geometry only. Angles land 2pi/n apart, so foes never stack.
    """
    radius = spawn_radius_for_level(level)
    count = len(words)
    step = (2.0 * pi / count) if count else 0.0
    foes = tuple(
        ArenaEnemy(
            id=EnemyId(state.next_id + index),
            kind=kind,
            word=word,
            hp_words=1,
            distance=radius,
            angle=(start_angle + float(index) * step) % (2.0 * pi),
        )
        for index, word in enumerate(words)
    )
    return replace(
        state,
        enemies=(*state.enemies, *foes),
        next_id=state.next_id + count,
    )


def handle_keystroke(
    state: ArenaState,
    ch: str,
    now: float,
    *,
    accuracy: float = 1.0,
    consistency: float | None = None,
) -> tuple[ArenaState, Keystroke]:
    """Resolve one keypress: advance/kill via combat, score, streak, shields.

    Boss bars burn one hp_word per completed word (the foe stays locked
    until its last bar); streak-x8 kills produce shield_until, merged
    with max() so a fresh shield never clobbers a longer live one.
    Kills bank the skill-gated payout (bands x ladder x consistency gate).
    """
    foes = tuple(foe.to_combat() for foe in state.enemies)
    outcome = apply_keystroke(
        ch,
        foes,
        state.current,
        state.typed,
        state.streak,
        now,
        state.stunned_until,
    )
    match outcome:
        case Advanced(target=target, typed=typed):
            mercy = mercy_note_keystroke(state.mercy, correct=True)
            return replace(state, current=target, typed=typed, mercy=mercy), outcome
        case Kill(target=target, streak=streak, shield_until=shield):
            foe = next(item for item in state.enemies if item.id == target)
            gained = Score(
                state.score
                + score_kill(
                    len(str(foe.word.text)),
                    accuracy,
                    streak_multiplier(streak),
                    consistency,
                ),
            )
            merged = max(state.shield_until, shield)
            mercy = mercy_note_keystroke(state.mercy, correct=True)
            if foe.hp_words > 1:
                burned = tuple(
                    replace(item, hp_words=item.hp_words - 1)
                    if item.id == target
                    else item
                    for item in state.enemies
                )
                return replace(
                    state,
                    enemies=burned,
                    score=gained,
                    streak=streak,
                    shield_until=merged,
                    current=target,
                    typed=0,
                    mercy=mercy,
                ), outcome
            rest = tuple(item for item in state.enemies if item.id != target)
            live = (
                state.current
                if any(item.id == state.current for item in rest)
                else None
            )
            return replace(
                state,
                enemies=rest,
                score=gained,
                kills=state.kills + 1,
                streak=streak,
                shield_until=merged,
                current=live,
                typed=0 if live is None else state.typed,
                mercy=mercy,
            ), outcome
        case TypoStun(stun_until=until):
            fresh = until > state.stunned_until
            mercy = state.mercy
            if fresh and not state.boss_wave:
                mercy = mercy_note_stun(state.mercy, now)
            return replace(state, stunned_until=until, streak=0, mercy=mercy), outcome
        case NoTarget():
            return state, outcome


def advance(state: ArenaState, dt: float) -> tuple[ArenaState, tuple[EnemyId, ...]]:
    """Move foes inward; leaks cost HP, clear the lock, and report foe ids."""
    moved = tuple(
        replace(foe, distance=foe.distance - _speed_of(foe.kind) * dt)
        for foe in state.enemies
    )
    leaked = tuple(foe.id for foe in moved if foe.distance <= 0.0)
    rest = tuple(foe for foe in moved if foe.distance > 0.0)
    hp = max(state.hp - LEAK_DAMAGE * len(leaked), 0.0)
    live = state.current if any(foe.id == state.current for foe in rest) else None
    after = replace(
        state,
        enemies=rest,
        hp=hp,
        current=live,
        typed=0 if live is None else state.typed,
    )
    return after, leaked


def merge_window(live: float, gained: float) -> float:
    """Merge effect windows with max(): uses never clear live effects."""
    return max(live, gained)


def apply_pickup(state: ArenaState, item: ItemKind, now: float) -> ArenaState:
    """Apply one typed item grab, max()-merging nonzero effect windows."""
    result: TriggerResult = trigger(
        item,
        state.hp,
        state.max_hp,
        state.revives_used,
        now,
    )
    return replace(
        state,
        hp=result.hp,
        revives_used=result.revives_used,
        frost_until=merge_window(state.frost_until, result.frost_until),
        shield_until=merge_window(state.shield_until, result.shield_until),
    )


def roll_drop(kind: EnemyKind, roll: float) -> ItemKind | None:
    """Drop table: Frost guaranteed per boss, Chain ~10% on elites.

    NOVA never drops; it charges via nova_ready (30s at 95%+ accuracy).
    """
    if kind is EnemyKind.BOSS:
        return ItemKind.FROST_VEIL
    if kind is EnemyKind.ELITE and roll < ELITE_DROP_RATE:
        return ItemKind.CHAIN_SPARK
    return None


def boss_cleared(state: ArenaState) -> bool:
    """Boss waves end on kill: true once no BOSS-kind foe remains."""
    return state.boss_wave and not any(
        foe.kind is EnemyKind.BOSS for foe in state.enemies
    )


def set_boss_wave(state: ArenaState, *, flag: bool) -> ArenaState:
    """Mark the timed wave as a boss wave (or release it once cleared)."""
    return replace(state, boss_wave=flag)


def clear_lock(state: ArenaState) -> ArenaState:
    """Drop the current target lock (Esc), keeping everything else."""
    return replace(state, current=None, typed=0, stunned_until=0.0)


def reset_word(state: ArenaState) -> ArenaState:
    """Drop the target lock and cancel any active typo stun immediately."""
    return replace(state, current=None, typed=0, stunned_until=0.0)


def chain_lightning(
    state: ArenaState,
    exclude: EnemyId,
    arcs: int = 2,
    *,
    accuracy: float = 1.0,
    consistency: float | None = None,
) -> tuple[ArenaState, int]:
    """Chain Spark arc: kill up to `arcs` nearest foes past the typed one.

    shortcut: arcs a fixed count, upgrade to distance-falloff when items grow.
    """
    others = sorted(
        (foe for foe in state.enemies if foe.id != exclude),
        key=lambda foe: (foe.distance, foe.id),
    )
    zapped = tuple(foe.id for foe in others[:arcs])
    rest = tuple(foe for foe in state.enemies if foe.id not in zapped)
    mult = streak_multiplier(state.streak)
    gained = Score(
        state.score
        + sum(
            score_kill(len(str(foe.word.text)), accuracy, mult, consistency)
            for foe in others[:arcs]
        ),
    )
    live = state.current if any(foe.id == state.current for foe in rest) else None
    after = replace(
        state,
        enemies=rest,
        score=gained,
        kills=state.kills + len(zapped),
        current=live,
        typed=0 if live is None else state.typed,
    )
    return after, len(zapped)


_GLITCH_BLOCKS: Final = "░▒▓"

_ROT13_TABLE: Final = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
)


def corrupted_display(word: Word) -> str:
    """Render a word through its corruption stage (display-only).

    Lock/target/advance always use the raw text; this never feeds logic.
    """
    raw = str(word.text)
    match word.corruption:
        case Corruption.CLEAN:
            return raw
        case Corruption.REVERSED:
            return raw[::-1]
        case Corruption.GLITCH:
            return "".join(
                _GLITCH_BLOCKS[(ord(char) + index) % len(_GLITCH_BLOCKS)]
                for index, char in enumerate(raw)
            )
        case Corruption.ROT13:
            return raw.translate(_ROT13_TABLE)
        case _:
            assert_never(word.corruption)
