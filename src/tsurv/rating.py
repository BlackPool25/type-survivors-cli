"""Glicko-lite skill rating: estimated true WPM plus uncertainty.

The estimate fuses per-kill pace observations with precision weighting, so
fresh players (wide RD) place within a few kills while veterans (RD at the
floor) drift instead of jumping. The number feeds spawn pressure and the
visible hub rank; it never touches player power.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

RD_START: Final = 60.0
"""Fresh-player deviation: wide enough that early kills place fast."""

RD_FLOOR: Final = 8.0
"""Deviation never drops below this, so established players still adapt."""

OBS_NOISE: Final = 12.0
"""Assumed per-kill WPM noise; weights each observation against the RD."""

MIN_RATING: Final = 1.0
"""Estimate clamps here; a slump cannot push the curve below a crawl."""

RANKS: Final = (
    (20.0, "Spark"),
    (35.0, "Ember"),
    (50.0, "Flame"),
    (65.0, "Blaze"),
    (80.0, "Inferno"),
)
"""Visible rank ladder: estimate below the cut earns the title."""


@dataclass(frozen=True, slots=True)
class SkillRating:
    """Persistent skill estimate: rating plus deviation plus evidence."""

    rating: float
    rd: float
    kills: int


def initial_rating(prior: float = 40.0) -> SkillRating:
    """Start a new player at the prior with maximum uncertainty."""
    return SkillRating(rating=prior, rd=RD_START, kills=0)


def update_rating(current: SkillRating, observed_wpm: float) -> SkillRating:
    """Fuse one per-kill pace observation into the estimate."""
    obs = max(observed_wpm, 0.0)
    prior_var = current.rd**2
    obs_var = OBS_NOISE**2
    gain = prior_var / (prior_var + obs_var)
    rating = max(current.rating + gain * (obs - current.rating), MIN_RATING)
    rd = max((1.0 - gain) * prior_var**0.5, RD_FLOOR)
    return SkillRating(rating=rating, rd=rd, kills=current.kills + 1)


def rank_for(rating: float) -> str:
    """Visible hub rank; thresholds ascend with estimated WPM."""
    for cut, title in RANKS:
        if rating < cut:
            return title
    return "Mythic"
