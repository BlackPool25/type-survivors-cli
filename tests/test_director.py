"""Tests for the AI director: strain signal, Build/Peak/Relax FSM, gaps."""

from __future__ import annotations

from tsurv.director import (
    CROWD_WEIGHT,
    HEALTH_WEIGHT,
    PEAK_MIN_S,
    RELAX_S,
    DirectorState,
    Phase,
    compute_strain,
    director_step,
    gap_multiplier,
    initial_director,
)


def test_strain_weights_crowd_and_health() -> None:
    """Full field at full HP strains more than an empty field near death."""
    assert compute_strain(0, 8, 1.0) == 0.0
    assert compute_strain(8, 8, 0.0) == 1.0
    assert compute_strain(8, 8, 1.0) == CROWD_WEIGHT
    assert compute_strain(0, 8, 0.0) == HEALTH_WEIGHT


def test_build_breaks_into_peak_when_overrun() -> None:
    """Sustained overcrowding flips the director into Peak."""
    state = initial_director()
    assert director_step(state, 0.8, 1.0).phase is Phase.PEAK
    assert director_step(state, 0.5, 1.0).phase is Phase.BUILD


def test_peak_holds_until_controlled() -> None:
    """Peak lasts the minimum beat even after the player recovers."""
    peaked = director_step(initial_director(), 0.9, 0.0)
    assert director_step(peaked, 0.1, 1.0).phase is Phase.PEAK
    settled = director_step(peaked, 0.1, PEAK_MIN_S)
    assert settled.phase is Phase.RELAX


def test_relax_returns_to_build_after_breather() -> None:
    """Relax always expires back into Build, never sticks."""
    relaxed = DirectorState(phase=Phase.RELAX, time_in_phase=0.0)
    assert director_step(relaxed, 0.9, 1.0).phase is Phase.RELAX
    assert director_step(relaxed, 0.9, RELAX_S).phase is Phase.BUILD


def test_boss_waves_freeze_the_director() -> None:
    """Scripted boss pressure never triggers Peak or Relax mid-fight."""
    state = director_step(initial_director(), 0.9, 0.0)
    assert director_step(state, 0.9, 30.0, boss_wave=True) is state


def test_gap_multipliers_breathe() -> None:
    """Peak spawns faster, Relax slower, Build neutral."""
    assert gap_multiplier(Phase.BUILD) == 1.0
    assert gap_multiplier(Phase.PEAK) < 1.0
    assert gap_multiplier(Phase.RELAX) > 1.0
