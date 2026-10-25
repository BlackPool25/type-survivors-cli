"""Game feel: telegraphs, hit-stop, knockback, shake, flash, particles, slow-mo.

All motion runs through pure state so tests pin the timings exactly. Verbatim
spec values: grunt 200ms rear-up (DESIGN section 3), ~80ms hit-stop and 0.5s
streak-x8 slow-mo (DESIGN section 5), 60fps tick (DESIGN section 5), x8 shield
cadence shared with slow-mo (combat.SHIELD_STREAK_EVERY). Values marked
`chosen` have no spec number; the report lists them as guesses to revisit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import pairwise
from typing import TYPE_CHECKING, Final, NewType, assert_never

from tsurv.arena import EnemyKind
from tsurv.combat import SHIELD_STREAK_EVERY
from tsurv.profile import Profile, ProfileError

if TYPE_CHECKING:
    import random
    from collections.abc import Sequence

Seconds = NewType("Seconds", float)

TELEGRAPH_S: Final = 0.2
HIT_STOP_S: Final = 0.08
SLOW_MO_S: Final = 0.5
SLOW_MO_SCALE: Final = 0.5  # chosen: half-speed reads as slow-mo
LOW_HP_FRACTION: Final = 0.3  # chosen: pulse at/below 30% vitals
TRAUMA_DECAY_PER_S: Final = 1.0  # chosen: full trauma clears in one quiet second
TRAUMA_KILL: Final = 0.3  # chosen: three rattles stack to a full shake
PARTICLE_BURST: Final = 12  # chosen: one ring of twelve motes per bar break


@dataclass(frozen=True, slots=True)
class Particle:
    """One knockback mote: position, velocity, remaining life in seconds."""

    x: float
    y: float
    vx: float
    vy: float
    life: float


@dataclass(frozen=True, slots=True)
class JuiceState:
    """Timestamps (monotonic seconds) for every transient feel window."""

    hit_stop_until: float = 0.0
    knockback_until: float = 0.0
    flash_until: float = 0.0
    slow_mo_until: float = 0.0
    trauma: float = 0.0
    particles: tuple[Particle, ...] = ()

    def frozen_at(self, now: float) -> bool:
        """Report whether the sim holds still for hit-stop at `now`."""
        return now < self.hit_stop_until

    @property
    def shake_active(self) -> bool:
        """Report whether residual trauma should rattle the frame."""
        return self.trauma > 0.0


def telegraph_seconds(kind: EnemyKind) -> Seconds:
    """Return the rear-up warning each kind shows before it can leak."""
    match kind:
        case EnemyKind.GRUNT:
            return Seconds(TELEGRAPH_S)
        case EnemyKind.MITE:
            return Seconds(TELEGRAPH_S)
        case EnemyKind.HEX:
            return Seconds(TELEGRAPH_S)
        case EnemyKind.ELITE:
            return Seconds(TELEGRAPH_S)
        case EnemyKind.BOSS:
            return Seconds(TELEGRAPH_S)
        case _:
            assert_never(kind)


def telegraph_showing(impact_in: float, kind: EnemyKind) -> bool:
    """Report whether the leak warning shows given seconds until impact."""
    return 0.0 < impact_in <= telegraph_seconds(kind)


def is_bar_break(kind: EnemyKind, hp_words: int) -> bool:
    """Report whether a completion earns the knockback blast treatment."""
    return hp_words > 1 or kind is EnemyKind.BOSS


def spawn_burst(
    rng: random.Random,
    count: int = PARTICLE_BURST,
) -> tuple[Particle, ...]:
    """Emit one ring of short-lived motes for a bar break."""
    return tuple(
        Particle(
            x=0.0,
            y=0.0,
            vx=rng.uniform(-2.0, 2.0),
            vy=rng.uniform(-2.0, 2.0),
            life=rng.uniform(0.25, 0.6),
        )
        for _ in range(count)
    )


def trigger_bar_break(state: JuiceState, now: float, rng: random.Random) -> JuiceState:
    """Raise knockback + hit-stop + flash, max trauma, burst particles."""
    window = now + HIT_STOP_S
    return replace(
        state,
        hit_stop_until=window,
        knockback_until=window,
        flash_until=window,
        trauma=1.0,
        particles=spawn_burst(rng),
    )


def trigger_kill(state: JuiceState, streak_after: int, now: float) -> JuiceState:
    """Rattle the frame on a kill; arm 0.5s slow-mo on the x8 milestone."""
    slow_mo_until = state.slow_mo_until
    if streak_after % SHIELD_STREAK_EVERY == 0:
        slow_mo_until = now + SLOW_MO_S
    return replace(
        state,
        slow_mo_until=slow_mo_until,
        trauma=min(1.0, state.trauma + TRAUMA_KILL),
    )


def step_juice(state: JuiceState, dt: float) -> JuiceState:
    """Age trauma and particles by `dt`; windows expire on their own."""
    aged = tuple(
        Particle(
            x=mote.x + mote.vx * dt,
            y=mote.y + mote.vy * dt,
            vx=mote.vx,
            vy=mote.vy,
            life=mote.life - dt,
        )
        for mote in state.particles
        if mote.life - dt > 0.0
    )
    return replace(
        state,
        trauma=max(0.0, state.trauma - TRAUMA_DECAY_PER_S * dt),
        particles=aged,
    )


def time_scale(state: JuiceState, now: float) -> float:
    """Return the sim speed multiplier (half speed inside slow-mo)."""
    return SLOW_MO_SCALE if now < state.slow_mo_until else 1.0


def low_hp(hp: float, max_hp: float) -> bool:
    """Report whether living vitals sit at/below the pulse threshold."""
    return max_hp > 0.0 and 0.0 < hp <= max_hp * LOW_HP_FRACTION


def calibrate_base_wpm(kill_times: Sequence[float]) -> float:
    """Measure the mean per-word rate from wave-1 kill timestamps."""
    gaps = [later - first for first, later in pairwise(kill_times) if later > first]
    if not gaps:
        return 0.0
    return sum(60.0 / gap for gap in gaps) / len(gaps)


def apply_calibration(profile: Profile, base_wpm: float) -> Profile:
    """Write the measured base rate onto a profile copy."""
    if base_wpm < 0.0:
        msg = f"base_wpm must be non-negative: {base_wpm}"
        raise ProfileError(msg)
    return profile.model_copy(update={"base_wpm": base_wpm})
