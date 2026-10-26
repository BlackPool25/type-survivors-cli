"""Entry-point tests: flags, help text, and a headless hub boot."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

import pytest

from tsurv.__main__ import build_app, default_profile_dir, main, parse_args
from tsurv.app import ArenaScreen, HubScreen
from tsurv.profile import PROFILE_FILENAME, Profile, save_profile

if TYPE_CHECKING:
    from pathlib import Path

_SAVED_GOLD: Final = 77
"""Wallet written by the save/load round-trip test."""


def test_parse_args_defaults_to_hub() -> None:
    """No flags means the hub menu, not help and not resume."""
    args = parse_args(())
    assert args.resume is False
    assert args.show_help is False


def test_parse_args_resume_and_help() -> None:
    """--resume and --help/-h set their flags."""
    resume_args = parse_args(("--resume",))
    assert resume_args.resume is True
    help_args = parse_args(("--help",))
    assert help_args.show_help is True
    short_args = parse_args(("-h",))
    assert short_args.show_help is True


def test_parse_args_unknown_flag_raises() -> None:
    """Unknown flags are usage errors, not silent ignores."""
    with pytest.raises(ValueError, match="unknown option"):
        _ = parse_args(("--frobnicate",))


def test_help_prints_usage_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--help prints controls, goal, and resume flags, then exits 0."""
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "Usage" in out
    assert "--resume" in out
    assert "80 columns" in out
    assert "boss" in out


def test_entry_boots_to_hub_and_quits_cleanly() -> None:
    """The entry builds an app that reaches the hub and quits via Q."""

    async def _scenario() -> None:
        app = build_app(parse_args(()))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HubScreen)
            await pilot.press("q")
            await pilot.pause()

    asyncio.run(_scenario())


def test_resume_flag_launches_arena_not_hub(tmp_path: Path) -> None:
    """--resume wires to the restore path: it boots the arena directly."""

    async def _scenario() -> None:
        app = build_app(parse_args(("--resume",)), tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, ArenaScreen)

    asyncio.run(_scenario())


def test_default_profile_dir_names_game() -> None:
    """The data home ends in type-survivors on every platform."""
    assert default_profile_dir().name == "type-survivors"


def test_build_app_loads_saved_profile(tmp_path: Path) -> None:
    """A saved wallet greets the player; progress survives restarts."""
    save_profile(tmp_path, Profile(gold=_SAVED_GOLD))
    assert build_app(parse_args(()), tmp_path).profile.gold == _SAVED_GOLD


def test_build_app_falls_back_on_corrupt_profile(tmp_path: Path) -> None:
    """A trashed save never blocks boot; the player starts fresh."""
    _ = (tmp_path / PROFILE_FILENAME).write_text("{nope", encoding="utf-8")
    assert build_app(parse_args(()), tmp_path).profile == Profile(
        settings=build_app(parse_args(()), None).profile.settings,
    )
