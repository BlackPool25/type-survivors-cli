"""Tests for profile persistence: save/load round-trip, per-key stats, palette."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tsurv.profile import (
    PROFILE_FILENAME,
    KeyStat,
    Palette,
    Profile,
    ProfileError,
    RunSummary,
    Settings,
    load_profile,
    record_keystroke,
    save_profile,
)

if TYPE_CHECKING:
    from pathlib import Path

_GOLD = 5
"""Wallet balance used by the save-dir test."""


def test_load_missing_returns_default(tmp_path: Path) -> None:
    """A missing file loads a fresh default profile, never an error."""
    profile = load_profile(tmp_path / "new-player")
    assert profile == Profile()


def test_round_trip_save_load(tmp_path: Path) -> None:
    """Gold, settings, per-key stats, and runs survive a save/load cycle."""
    profile = record_keystroke(Profile(gold=250), "a", correct=True, dt=0.12)
    profile = record_keystroke(profile, "a", correct=False, dt=0.30)
    run = RunSummary(
        wpm_samples=(40.0, 44.5),
        accuracy=0.97,
        kills=12,
        wave=3,
        score=1500,
        duration_s=95.0,
    )
    profile = profile.model_copy(
        update={
            "shop": ("second-wind",),
            "hiscores": (1500,),
            "settings": Settings(palette=Palette.DEUTAN, sound_on=False),
            "runs": (run,),
        },
    )
    save_profile(tmp_path, profile)
    assert load_profile(tmp_path) == profile


def test_load_corrupt_json_raises(tmp_path: Path) -> None:
    """Garbage bytes never silently reset history — they raise ProfileError."""
    _ = (tmp_path / PROFILE_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileError):
        _ = load_profile(tmp_path)


def test_load_non_utf8_bytes_raises(tmp_path: Path) -> None:
    """Binary garbage never leaks raw UnicodeDecodeError — ProfileError instead."""
    _ = (tmp_path / PROFILE_FILENAME).write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ProfileError):
        _ = load_profile(tmp_path)


def test_load_bad_palette_raises(tmp_path: Path) -> None:
    """An unknown palette string fails load with ProfileError, not a default."""
    _ = (tmp_path / PROFILE_FILENAME).write_text(
        '{"gold": 10, "settings": {"palette": "NEON", "sound_on": true}}',
        encoding="utf-8",
    )
    with pytest.raises(ProfileError):
        _ = load_profile(tmp_path)


def test_all_palettes_round_trip(tmp_path: Path) -> None:
    """Every palette mode survives save/load (exercises each match arm)."""
    for palette in (Palette.STANDARD, Palette.PROTAN, Palette.DEUTAN, Palette.TRITAN):
        profile = Profile(settings=Settings(palette=palette))
        save_profile(tmp_path, profile)
        assert load_profile(tmp_path).settings.palette is palette


def test_per_key_accuracy_aggregates() -> None:
    """Per-key stats count presses, hits, time, and report accuracy."""
    profile = Profile()
    profile = record_keystroke(profile, "e", correct=True, dt=0.10)
    profile = record_keystroke(profile, "e", correct=True, dt=0.20)
    profile = record_keystroke(profile, "e", correct=False, dt=0.40)
    stat = profile.per_key["e"]
    assert (stat.presses, stat.correct) == (3, 2)
    assert stat.total_time == pytest.approx(0.70)
    assert stat.accuracy == pytest.approx(2.0 / 3.0)


def test_record_keystroke_leaves_original_alone() -> None:
    """Profiles are immutable: recording returns a new profile."""
    before = Profile()
    after = record_keystroke(before, "q", correct=True, dt=0.05)
    assert before.per_key == {}
    assert after.per_key["q"] == KeyStat(presses=1, correct=1, total_time=0.05)


def test_record_keystroke_rejects_bad_input() -> None:
    """Empty/multi-char keys and negative timings raise ProfileError."""
    with pytest.raises(ProfileError):
        _ = record_keystroke(Profile(), "", correct=True, dt=0.1)
    with pytest.raises(ProfileError):
        _ = record_keystroke(Profile(), "ab", correct=True, dt=0.1)
    with pytest.raises(ProfileError):
        _ = record_keystroke(Profile(), "a", correct=True, dt=-0.1)


def test_save_creates_dir_and_leaves_no_tmp(tmp_path: Path) -> None:
    """Save makes missing dirs and never leaves a tmp file behind."""
    target = tmp_path / "nested" / "player"
    save_profile(target, Profile(gold=_GOLD))
    assert (target / PROFILE_FILENAME).is_file()
    assert list(target.glob("*.tmp")) == []
    assert load_profile(target).gold == _GOLD
