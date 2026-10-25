"""Player profile + persistence: Pydantic at the save boundary, stdlib elsewhere."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, Self, assert_never

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

if TYPE_CHECKING:
    from pathlib import Path

PROFILE_FILENAME: Final = "profile.json"
"""Save file name inside the player data dir."""


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
    """Per-key coaching stats: presses, hits, and total press time in seconds."""

    presses: int = 0
    correct: int = 0
    total_time: float = 0.0

    def __post_init__(self) -> None:
        """Reject negative counts, hits above presses, and negative time."""
        if self.presses < 0 or self.correct < 0 or self.correct > self.presses:
            msg = f"invalid key counts: {self.presses} presses, {self.correct} hits"
            raise ProfileError(msg)
        if self.total_time < 0.0:
            msg = f"invalid key time: {self.total_time}"
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

    gold: int = Field(default=0, ge=0)
    shop: tuple[str, ...] = ()
    hiscores: tuple[int, ...] = ()
    settings: Settings = Field(default_factory=Settings)
    per_key: dict[str, KeyStat] = Field(default_factory=dict)
    runs: tuple[RunSummary, ...] = ()

    @model_validator(mode="after")
    def _check_palette(self) -> Self:
        """Re-validate the palette enum on load (exhaustive over Palette)."""
        match self.settings.palette:
            case Palette.STANDARD | Palette.PROTAN | Palette.DEUTAN:
                return self
            case _ as other:
                if other is Palette.TRITAN:
                    return self
                assert_never(other)


def load_profile(profile_dir: Path) -> Profile:
    """Load the profile, defaulting only when no save file exists yet."""
    path = profile_dir / PROFILE_FILENAME
    if not path.exists():
        return Profile()
    try:
        return Profile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        msg = f"cannot load profile from {path}: {exc}"
        raise ProfileError(msg) from exc


def save_profile(profile_dir: Path, profile: Profile) -> None:
    """Atomically write the profile so a crash never corrupts the save."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / PROFILE_FILENAME
    tmp = path.with_name(f"{PROFILE_FILENAME}.tmp")
    try:
        _ = tmp.write_text(profile.model_dump_json(), encoding="utf-8")
        _ = tmp.replace(path)
    except OSError as exc:
        msg = f"cannot save profile to {path}: {exc}"
        raise ProfileError(msg) from exc


def record_keystroke(
    profile: Profile,
    key: str,
    correct: bool,  # noqa: FBT001 - brief pins (profile, key, correct, dt)
    dt: float,
) -> Profile:
    """Fold one keystroke into per-key stats, returning a new profile."""
    if len(key) != 1:
        msg = f"keystroke must be one character, got {key!r}"
        raise ProfileError(msg)
    if dt < 0.0:
        msg = f"keystroke dt must be >= 0.0, got {dt}"
        raise ProfileError(msg)
    stat = profile.per_key.get(key, KeyStat())
    updated = KeyStat(
        presses=stat.presses + 1,
        correct=stat.correct + (1 if correct else 0),
        total_time=stat.total_time + dt,
    )
    return profile.model_copy(update={"per_key": {**profile.per_key, key: updated}})
