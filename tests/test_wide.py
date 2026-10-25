"""Task 8 acceptance: ultrawide layout, pause menu, crash autosuspend."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from rich.text import Text
from textual import events
from textual.containers import Vertical
from textual.widgets import Label

from tsurv.app import (
    HUB_COLUMN_MAX,
    PAUSE_ENTRIES,
    ArenaScreen,
    HubScreen,
    PauseAction,
    TypeSurvivorsApp,
    pause_action_for,
)
from tsurv.screens import CHECKPOINT_FILENAME, load_checkpoint
from tsurv.stage import canvas_xy

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_WIDE: Final = (200, 50)
_FIELD_SHARE: Final = 0.7
_PAUSE_LABELS: Final = ("Resume", "How to Play", "Settings", "Suspend & Hub", "Quit")


def _plain(label: Label) -> str:
    """Label text whether the content is styled Text or a plain string."""
    content = label.content
    return content.plain if isinstance(content, Text) else str(content)


def test_pause_entries_cover_brief() -> None:
    """The pause menu names the five brief options in order."""
    assert [entry.label for entry in PAUSE_ENTRIES] == list(_PAUSE_LABELS)
    assert [entry.key for entry in PAUSE_ENTRIES] == ["R", "H", "E", "S", "Q"]


def test_pause_action_parse() -> None:
    """Pause keys map case-insensitively; anything else is not an action."""
    assert pause_action_for("r") is PauseAction.RESUME
    assert pause_action_for("H") is PauseAction.HOW_TO
    assert pause_action_for("e") is PauseAction.SETTINGS
    assert pause_action_for("S") is PauseAction.SUSPEND_HUB
    assert pause_action_for("q") is PauseAction.QUIT
    assert pause_action_for("z") is None
    assert pause_action_for("") is None


def test_hub_stays_centered_at_200x50() -> None:
    """Ultrawide hub: column capped (no dead acres), nothing overflows."""

    async def _scenario() -> tuple[int, int]:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            spawn_enabled=False,
            start_at_hub=True,
        )
        async with app.run_test(size=_WIDE) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HubScreen)
            column = screen.query_one("#hub-column", Vertical)
            header = screen.query_one("#hub-header", Vertical)
            for widget in screen.query(Label):
                assert widget.content_size.width <= _WIDE[0]
            return column.content_size.width, header.content_size.width

    column_w, header_w = asyncio.run(_scenario())
    assert column_w <= HUB_COLUMN_MAX
    assert header_w <= HUB_COLUMN_MAX


def test_arena_centered_no_overflow_at_200x50() -> None:
    """Ultrawide arena: MC centered, rails docked, field fills most of it."""

    async def _scenario() -> tuple[int, int, int, int, int]:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=_WIDE) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            stage = screen.query_one("#stage", Vertical)
            width, height = stage.content_size.width, stage.content_size.height
            assert width >= int(_WIDE[0] * _FIELD_SHARE)
            assert canvas_xy(angle=0.0, distance=0.0, width=width, height=height) == (
                width // 2,
                height // 2,
            )
            top = screen.query_one("#topbar", Label).content_size.width
            bottom = screen.query_one("#botrail", Label).content_size.width
            top_len = len(_plain(screen.query_one("#topbar", Label)))
            bottom_len = len(_plain(screen.query_one("#botrail", Label)))
            assert top_len <= _WIDE[0]
            assert bottom_len <= _WIDE[0]
            return width, height, top, bottom, len(screen.foes_text)

    width, height, top, bottom, _ = asyncio.run(_scenario())
    assert width >= int(_WIDE[0] * _FIELD_SHARE)
    assert top >= int(_WIDE[0] * _FIELD_SHARE)
    assert bottom >= int(_WIDE[0] * _FIELD_SHARE)
    assert height > 0


def test_pause_menu_freezes_sim_and_resumes() -> None:
    """P opens the option overlay; sim clocks hold; R resumes the run."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            await pilot.press("P")
            assert screen.paused is True
            overlay = screen.query_one("#pause", Label)
            assert overlay.display is True
            menu = _plain(overlay)
            for label in _PAUSE_LABELS:
                assert label in menu
            clock = screen.clock
            held = screen.arena_state.enemies[0].distance
            screen.tick(1.0)
            screen.tick(1.0)
            assert screen.clock == clock
            assert screen.arena_state.enemies[0].distance == held
            await pilot.press("c")
            assert screen.arena_state.typed == 0
            await pilot.press("R")
            assert screen.paused is False
            assert screen.query_one("#pause", Label).display is False
            screen.tick(0.5)
            assert screen.clock > clock

    asyncio.run(_scenario())


def test_pause_enter_activates_selected() -> None:
    """Enter on the default Resume row resumes without a hotkey."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            await screen.on_key(events.Key("P", "P"))
            assert screen.paused is True
            await screen.on_key(events.Key("enter", None))
            assert screen.paused is False

    asyncio.run(_scenario())


def test_pause_suspend_writes_checkpoint_and_shows_hub(tmp_path: Path) -> None:
    """S from the pause menu saves the wave and lands on the hub."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            spawn_enabled=False,
            profile_dir=tmp_path,
        )
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            await pilot.press("P")
            await pilot.press("E")
            await pilot.pause()
            assert type(app.screen).__name__ == "SettingsScreen"
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, ArenaScreen)
            assert screen.paused is True
            await pilot.press("S")
            await pilot.pause()
            assert (tmp_path / CHECKPOINT_FILENAME).is_file()
            assert isinstance(app.screen, HubScreen)

    asyncio.run(_scenario())


def test_tick_panic_autosuspends_and_shows_hub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raise inside tick saves the checkpoint and lands on the hub."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            spawn_enabled=False,
            profile_dir=tmp_path,
        )
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, ArenaScreen)

            def _boom(*_args: object, **_kwargs: object) -> object:
                msg = "boom"
                raise RuntimeError(msg)

            monkeypatch.setattr("tsurv.app.advance", _boom)
            screen.tick(0.1)
            await pilot.pause()
            assert (tmp_path / CHECKPOINT_FILENAME).is_file()
            assert load_checkpoint(tmp_path).wave == screen.arena_state.wave
            assert isinstance(app.screen, HubScreen)
            message = _plain(app.screen.query_one("#hub-message", Label))
            assert "resume where you left off" in message

    asyncio.run(_scenario())
