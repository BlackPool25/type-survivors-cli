"""AI director: strain signal plus the Build/Peak/Relax pressure cycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

CROWD_WEIGHT: Final = 0.6
"""Strain share from field crowding (foes on screen over the cap)."""

HEALTH_WEIGHT: Final = 0.4
"""Strain share from missing hull (low HP strains even a clear field)."""

PEAK_ENTER_STRAIN: Final = 0.75
"""Build breaks into Peak once strain crosses this line."""

PEAK_MIN_S: Final = 10.0
"""Peak holds at least this long, even after the player recovers."""

RELAX_ENTER_STRAIN: Final = 0.5
"""Peak settles into Relax once strain drops back under this line."""

RELAX_S: Final = 8.0
"""Relax always expires back into Build after this breather."""

PEAK_GAP_MULT: Final = 0.8
"""Peak spawns faster: gaps shrink to four-fifths."""

RELAX_GAP_MULT: Final = 1.3
"""Relax spawns slower: gaps stretch by nearly a third."""


class Phase(StrEnum):
    """Director beat: Build pressure, Peak intensity, Relax breather."""

    BUILD = "BUILD"
    PEAK = "PEAK"
    RELAX = "RELAX"


@dataclass(frozen=True, slots=True)
class DirectorState:
    """One director beat plus its clock (bosses freeze the clock)."""

    phase: Phase = Phase.BUILD
    time_in_phase: float = 0.0


def initial_director() -> DirectorState:
    """Fresh run, fresh director: always open on a calm Build."""
    return DirectorState()


def compute_strain(foe_count: int, foe_cap: int, hp_frac: float) -> float:
    """Pressure 0..1: crowd weight plus missing-hull weight, clamped."""
    crowd = foe_count / foe_cap if foe_cap > 0 else 0.0
    strain = CROWD_WEIGHT * crowd + HEALTH_WEIGHT * (1.0 - hp_frac)
    return min(max(strain, 0.0), 1.0)


def director_step(
    state: DirectorState,
    strain: float,
    dt: float,
    *,
    boss_wave: bool = False,
) -> DirectorState:
    """Advance the beat: overrun flips to Peak, control earns Relax.

    Boss waves freeze the director; scripted pressure never spikes mid-fight.
    """
    if boss_wave:
        return state
    elapsed = state.time_in_phase + dt
    match state.phase:
        case Phase.BUILD:
            if strain >= PEAK_ENTER_STRAIN:
                return DirectorState(phase=Phase.PEAK, time_in_phase=0.0)
        case Phase.PEAK:
            if elapsed >= PEAK_MIN_S and strain < RELAX_ENTER_STRAIN:
                return DirectorState(phase=Phase.RELAX, time_in_phase=0.0)
        case Phase.RELAX:
            if elapsed >= RELAX_S:
                return DirectorState(phase=Phase.BUILD, time_in_phase=0.0)
    return replace(state, time_in_phase=elapsed)


def gap_multiplier(phase: Phase) -> float:
    """Spawn-gap factor for the beat: Peak hurries, Relax breathes."""
    match phase:
        case Phase.BUILD:
            return 1.0
        case Phase.PEAK:
            return PEAK_GAP_MULT
        case Phase.RELAX:
            return RELAX_GAP_MULT
