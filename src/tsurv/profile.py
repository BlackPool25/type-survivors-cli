"""Player profile + persistence: Pydantic at the save boundary, stdlib elsewhere."""

from __future__ import annotations

import math
import os
import shutil
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, Self, assert_never, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

if TYPE_CHECKING:
    from pathlib import Path

PROFILE_FILENAME: Final = "profile.json"
"""Save file name inside the player data dir."""

CONFIDENCE_ALPHA: Final = 0.1
"""EMA weight per correct keystroke (keybr-style smoothing)."""

LATENCY_MIN_MS: Final = 40.0
"""Fastest believable inter-key latency; below this is a rejected outlier."""

LATENCY_MAX_MS: Final = 12000.0
"""Slowest believable inter-key latency; above this is a rejected outlier."""

REVIEW_INTERVALS_S: Final = (0.0, 3600.0, 86400.0, 259200.0, 604800.0, 1209600.0)
"""Weak-key review ladder: same-session, 1h, 1d, 3d, 7d, 14d."""

REVIEW_PROMOTE_ACC: Final = 0.98
"""Accuracy over a full window that promotes a key one ladder step."""

REVIEW_MIN_ATTEMPTS: Final = 10
"""Attempts per review window before promote/demote is evaluated."""

REVIEW_DEMOTE_ACC: Final = 0.85
"""Accuracy below this over a full window demotes a key one ladder step."""


class ProfileError(ValueError):
    """Raised when a profile file is corrupt or a keystroke update is invalid."""


class Palette(StrEnum):
    """Colorblind-safe palette mode for the arena UI."""

    STANDARD = "STANDARD"
    PROTAN = "PROTAN"
    DEUTAN = "DEUTAN"
    TRITAN = "TRITAN"


@dataclass(frozen=True, slots=True)
class Settings:
    """Shell toggles: palette, sound, bold readability, screen shake."""

    palette: Palette = Palette.STANDARD
    sound_on: bool = True
    bold: bool = False
    shake: bool = True


@dataclass(frozen=True, slots=True)
class KeyStat:
    """Per-key coaching stats: presses, hits, press time, confidence, review.

    ema_ms/best_ms carry the keybr-style confidence tracker (Task 8): EMA of
    in-range correct-key latencies plus the running min of the smoothed value.
    review_* / last_review carry the cross-session spaced-repetition schedule.
    """

    presses: int = 0
    correct: int = 0
    total_time: float = 0.0
    ema_ms: float | None = None
    best_ms: float | None = None
    misses: int = 0
    review_step: int = 0
    review_attempts: int = 0
    review_correct: int = 0
    last_review: float | None = None

    def __post_init__(self) -> None:
        """Reject negative counts, hits above presses, and negative time."""
        if self.presses < 0 or self.correct < 0 or self.correct > self.presses:
            msg = f"invalid key counts: {self.presses} presses, {self.correct} hits"
            raise ProfileError(msg)
        if self.total_time < 0.0:
            msg = f"invalid key time: {self.total_time}"
            raise ProfileError(msg)
        if self.ema_ms is not None and self.ema_ms < 0.0:
            msg = f"invalid key ema: {self.ema_ms}"
            raise ProfileError(msg)
        if self.best_ms is not None and self.best_ms < 0.0:
            msg = f"invalid key best: {self.best_ms}"
            raise ProfileError(msg)
        if self.misses < 0:
            msg = f"invalid key misses: {self.misses}"
            raise ProfileError(msg)
        if not 0 <= self.review_step < len(REVIEW_INTERVALS_S):
            msg = f"invalid review step: {self.review_step}"
            raise ProfileError(msg)
        if (
            self.review_attempts < 0
            or self.review_correct < 0
            or self.review_correct > self.review_attempts
        ):
            msg = (
                "invalid review window: "
                f"{self.review_attempts} attempts, {self.review_correct} hits"
            )
            raise ProfileError(msg)
        if self.last_review is not None and not math.isfinite(self.last_review):
            msg = f"invalid last review: {self.last_review}"
            raise ProfileError(msg)

    @property
    def accuracy(self) -> float:
        """Fraction of presses correct, 0.0 before any press."""
        if self.presses <= 0:
            return 0.0
        return self.correct / self.presses


@dataclass(frozen=True, slots=True)
class RunSummary:
    """One finished run for Task 6's report card (weakest keys from per_key)."""

    wpm_samples: tuple[float, ...] = ()
    accuracy: float = 0.0
    kills: int = 0
    wave: int = 0
    score: int = 0
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        """Reject out-of-range accuracy, negative tallies, and WPM samples."""
        if not 0.0 <= self.accuracy <= 1.0:
            msg = f"accuracy {self.accuracy} outside 0..1"
            raise ProfileError(msg)
        if self.kills < 0 or self.wave < 0 or self.score < 0:
            msg = f"negative run tally: kills={self.kills} wave={self.wave}"
            raise ProfileError(msg)
        if self.duration_s < 0.0 or any(sample < 0.0 for sample in self.wpm_samples):
            msg = f"negative run timing: duration={self.duration_s}"
            raise ProfileError(msg)


class Profile(BaseModel):
    """Save-file boundary: the only Pydantic model; the rest is stdlib."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    version: int = Field(default=1, ge=1)
    gold: int = Field(default=0, ge=0)
    shop: dict[str, int] = Field(default_factory=dict)
    hiscores: tuple[int, ...] = ()
    settings: Settings = Field(default_factory=Settings)
    per_key: dict[str, KeyStat] = Field(default_factory=dict)
    runs: tuple[RunSummary, ...] = ()
    base_wpm: float | None = Field(default=None, ge=0.0)
    skill_wpm: float = Field(default=40.0, ge=1.0)
    """Persistent Glicko-style estimate; seeds the deal target on run start."""
    skill_rd: float = Field(default=60.0, ge=8.0)
    """Estimate uncertainty; shrinks with banked runs, floors at 8."""
    skill_kills: int = Field(default=0, ge=0)
    """Banked-kill observation count behind the estimate."""

    @field_validator("shop", mode="before")
    @classmethod
    def _migrate_shop(cls, value: object) -> object:
        """Accept the v0 perk-id list (each owned once); v1 stores ranks."""
        if isinstance(value, dict):
            return cast("dict[str, int]", value)
        if isinstance(value, (list, tuple)):
            raw_ids = cast("list[object] | tuple[object, ...]", value)
            migrated: dict[str, int] = {str(item_id): 1 for item_id in raw_ids}
            return migrated
        return value

    @model_validator(mode="after")
    def _check_palette(self) -> Self:
        """Re-validate the palette enum on load (exhaustive over Palette)."""
        match self.settings.palette:
            case Palette.STANDARD | Palette.PROTAN | Palette.DEUTAN | Palette.TRITAN:
                return self
            case _:
                assert_never(self.settings.palette)


def load_profile(profile_dir: Path) -> Profile:
    """Load the profile, defaulting only when no save file exists yet."""
    path = profile_dir / PROFILE_FILENAME
    if not path.exists():
        return Profile()
    try:
        return Profile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        msg = f"cannot load profile from {path}: {exc}"
        raise ProfileError(msg) from exc


def atomic_write_text(path: Path, payload: str) -> None:
    """Durable save: fsynced tmp file, previous payload kept in .bak, then replace.

    The .bak copy lands before the replace, so a crash mid-write leaves
    either the old or the new payload intact — never a torn file. The .bak
    itself is best-effort (no fsync); the live file carries the guarantee.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    _ = tmp.write_text(payload, encoding="utf-8")
    with tmp.open("rb") as handle:
        os.fsync(handle.fileno())
    if path.is_file():
        _ = shutil.copyfile(path, path.with_name(f"{path.name}.bak"))
    _ = tmp.replace(path)


def save_profile(profile_dir: Path, profile: Profile) -> None:
    """Atomically write the profile so a crash never corrupts the save."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_text(
            profile_dir / PROFILE_FILENAME,
            profile.model_dump_json(),
        )
    except OSError as exc:
        msg = f"cannot save profile to {profile_dir / PROFILE_FILENAME}: {exc}"
        raise ProfileError(msg) from exc


def confidence(stat: KeyStat, target_ms: float) -> float:
    """Keybr-style confidence: target/smoothed, capped at 1.0, 0.0 with no data."""
    if target_ms <= 0.0:
        msg = f"confidence target must be > 0.0, got {target_ms}"
        raise ProfileError(msg)
    if stat.ema_ms is None:
        return 0.0
    return min(1.0, target_ms / stat.ema_ms) if stat.ema_ms > 0.0 else 1.0


def _smooth_timing(stat: KeyStat, dt_ms: float, *, correct: bool) -> KeyStat:
    """Fold one latency into the EMA; typos bump misses, outliers are dropped."""
    if not correct:
        return replace(stat, misses=stat.misses + 1)
    if not LATENCY_MIN_MS <= dt_ms <= LATENCY_MAX_MS:
        return stat
    if stat.ema_ms is None:
        ema = dt_ms
    else:
        ema = stat.ema_ms + CONFIDENCE_ALPHA * (dt_ms - stat.ema_ms)
    best = ema if stat.best_ms is None else min(stat.best_ms, ema)
    return replace(stat, ema_ms=ema, best_ms=best)


def review_interval_s(step: int) -> float:
    """Seconds until the next review for a ladder step (clamped to the ladder)."""
    return REVIEW_INTERVALS_S[min(max(step, 0), len(REVIEW_INTERVALS_S) - 1)]


def _note_review_attempt(stat: KeyStat, *, correct: bool, now: float | None) -> KeyStat:
    """Count one review attempt; full windows promote/demote and reset."""
    attempts = stat.review_attempts + 1
    hits = stat.review_correct + (1 if correct else 0)
    if attempts < REVIEW_MIN_ATTEMPTS:
        return replace(stat, review_attempts=attempts, review_correct=hits)
    accuracy = hits / attempts
    step = stat.review_step
    if accuracy >= REVIEW_PROMOTE_ACC:
        step = min(step + 1, len(REVIEW_INTERVALS_S) - 1)
    elif accuracy < REVIEW_DEMOTE_ACC:
        step = max(step - 1, 0)
    return replace(
        stat,
        review_step=step,
        review_attempts=0,
        review_correct=0,
        last_review=now,
    )


def review_due(stat: KeyStat, now: float) -> bool:
    """Report whether a key's review interval has elapsed (never-seen is due)."""
    if stat.last_review is None:
        return True
    return now - stat.last_review >= review_interval_s(stat.review_step)


def overdue_by(stat: KeyStat, now: float) -> float:
    """Seconds past a key's review interval (never-seen counts from epoch)."""
    seen = stat.last_review if stat.last_review is not None else 0.0
    return now - seen - review_interval_s(stat.review_step)


def weak_keys_for_spawn(profile: Profile, now: float) -> tuple[str, ...]:
    """Due weak keys, most overdue first, for the spawn-weighting hook."""
    due = [
        (overdue_by(stat, now), key)
        for key, stat in profile.per_key.items()
        if stat.presses > 0 and review_due(stat, now)
    ]
    return tuple(key for _, key in sorted(due, reverse=True))


def record_keystroke(
    profile: Profile,
    key: str,
    correct: bool,  # noqa: FBT001 - brief pins (profile, key, correct, dt)
    dt: float,
    *,
    now: float | None = None,
) -> Profile:
    """Fold one keystroke into per-key stats, returning a new profile."""
    if len(key) != 1:
        msg = f"keystroke must be one character, got {key!r}"
        raise ProfileError(msg)
    if dt < 0.0:
        msg = f"keystroke dt must be >= 0.0, got {dt}"
        raise ProfileError(msg)
    stat = profile.per_key.get(key, KeyStat())
    counted = replace(
        stat,
        presses=stat.presses + 1,
        correct=stat.correct + (1 if correct else 0),
        total_time=stat.total_time + dt,
    )
    timed = _smooth_timing(counted, dt * 1000.0, correct=correct)
    updated = _note_review_attempt(timed, correct=correct, now=now)
    return profile.model_copy(update={"per_key": {**profile.per_key, key: updated}})
