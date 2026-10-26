"""Tests for the Glicko-lite skill rating (visible rank, persistent)."""

from __future__ import annotations

from typing import Final

from tsurv.rating import (
    MIN_RATING,
    RD_FLOOR,
    RD_START,
    bank_run_skill,
    initial_rating,
    rank_for,
    update_rating,
)

_PRIOR: Final = 40.0
_FAST: Final = 80.0
_STEADY: Final = 60.0
_CLOSE_ENOUGH: Final = 5.0
_LONG_RUN: Final = 50
_BANKED_KILLS: Final = 5
"""Kill count folded by one banked run in the skill persistence test."""


def test_initial_rating_starts_uncertain() -> None:
    """Fresh players place near the prior with a wide deviation."""
    rating = initial_rating(prior=_PRIOR)
    assert rating.rating == _PRIOR
    assert rating.rd == RD_START
    assert rating.kills == 0


def test_first_kills_swing_fast() -> None:
    """High RD means early observations move the estimate a long way."""
    first = update_rating(initial_rating(), _FAST)
    second = update_rating(first, _FAST)
    assert first.rating > _PRIOR
    assert second.rating > first.rating
    assert second.rating - first.rating < first.rating - _PRIOR


def test_rating_converges_and_rd_floors() -> None:
    """Steady play settles near truth; uncertainty never hits zero."""
    rating = initial_rating()
    for _ in range(_LONG_RUN):
        rating = update_rating(rating, _STEADY)
    assert abs(rating.rating - _STEADY) < _CLOSE_ENOUGH
    assert rating.rd == RD_FLOOR
    assert rating.kills == _LONG_RUN


def test_rating_never_goes_negative() -> None:
    """Pathological slumps clamp at the floor, never below."""
    rating = initial_rating()
    for _ in range(_LONG_RUN):
        rating = update_rating(rating, 0.0)
    assert rating.rating == MIN_RATING


def test_rank_tiers_ascend() -> None:
    """Visible ranks rise tier by tier with the estimate."""
    ranks = [rank_for(float(wpm)) for wpm in (10, 25, 40, 55, 70, 95)]
    assert ranks == ["Spark", "Ember", "Flame", "Blaze", "Inferno", "Mythic"]


def test_bank_run_skill_folds_pace_into_estimate() -> None:
    """One banked run moves the estimate toward the run pace."""
    skill = bank_run_skill(initial_rating(), _FAST, _BANKED_KILLS)
    assert skill.rating > _PRIOR
    assert skill.rd < RD_START
    assert skill.kills == _BANKED_KILLS


def test_bank_run_skill_ignores_empty_runs() -> None:
    """A run with no kills still counts experience, never pace."""
    skill = bank_run_skill(initial_rating(), 0.0, 0)
    assert skill.rating == _PRIOR
    assert skill.kills == 0
