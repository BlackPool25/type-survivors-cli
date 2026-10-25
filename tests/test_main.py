"""Entry-point tests: flags, help text, and a headless hub boot."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from tsurv.__main__ import build_app, main, parse_args
from tsurv.app import ArenaScreen, HubScreen

if TYPE_CHECKING:
    from pathlib import Path


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
