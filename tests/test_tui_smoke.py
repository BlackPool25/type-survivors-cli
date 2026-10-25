"""Pilot smoke tests for the Textual arena (kill, stun, guard, NO_COLOR)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from textual import events
from textual.containers import Vertical
from textual.widgets import Label

from tsurv.app import (
    GOLD_NEXT,
    HP_GREEN,
    MAX_BOSS_BARS,
    ArenaScreen,
    ReportScreen,
    TypeSurvivorsApp,
)

if TYPE_CHECKING:
    import pytest

_GOLD_PROBE: Final = "cat"


def test_pilot_kills_grunt_and_scores() -> None:
    """Typing the on-screen word kills the grunt and raises the score."""

    async def _scenario() -> int:
        app = TypeSurvivorsApp(initial_words=(_GOLD_PROBE,), spawn_enabled=False)
        async with app.run_test() as pilot:
            for char in _GOLD_PROBE:
                await pilot.press(char)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.score_value > 0
            assert _GOLD_PROBE not in screen.foes_text
            return screen.score_value

    assert asyncio.run(_scenario()) > 0


def test_pilot_typo_shows_stun_flag() -> None:
    """A wrong char on a live lock makes the stun flag visible."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(_GOLD_PROBE,), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.press("c")
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            # Direct key: the 0.6s flag would expire during slow pilot waits.
            await screen.on_key(events.Key("x", "x"))
            assert screen.stun_visible is True

    asyncio.run(_scenario())


def test_narrow_window_shows_guard() -> None:
    """Windows under 80 cols show the guard screen instead of the arena."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(_GOLD_PROBE,), spawn_enabled=False)
        async with app.run_test(size=(60, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.query_one("#guard", Label).display is True
            assert screen.query_one("#arena", Vertical).display is False

    asyncio.run(_scenario())


def test_no_color_strips_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    """NO_COLOR forces mono rendering: word labels carry no style spans."""

    async def _scenario() -> tuple[bool, int]:
        app = TypeSurvivorsApp(initial_words=(_GOLD_PROBE,), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            return screen.mono, screen.foes_span_count

    monkeypatch.setenv("NO_COLOR", "1")
    mono, spans = asyncio.run(_scenario())
    assert mono is True
    assert spans == 0


def test_color_mode_uses_spans() -> None:
    """Without NO_COLOR the typed prefix is highlighted with spans."""

    async def _scenario() -> tuple[bool, int]:
        app = TypeSurvivorsApp(initial_words=(_GOLD_PROBE,), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            return screen.mono, screen.foes_span_count

    mono, spans = asyncio.run(_scenario())
    assert mono is False
    assert spans > 0


def test_death_stays_on_arena_screen() -> None:
    """Lethal leaks show the death overlay without leaving ArenaScreen."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            for _ in range(10):
                screen.spawn_test_enemy("zz", distance=0.05)
                screen.tick(5.0)
            await pilot.pause()
            assert screen.query_one("#death", Label).display is True
            assert isinstance(app.screen, ArenaScreen)

    asyncio.run(_scenario())


def test_report_screen_shows_tallies() -> None:
    """The second (and only other) screen reports kills/score/wave."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(_GOLD_PROBE,), spawn_enabled=False)
        async with app.run_test() as pilot:
            _ = app.push_screen(ReportScreen(score=120, kills=3, wave=2))
            await pilot.pause()
            report = app.screen
            assert isinstance(report, ReportScreen)
            assert report.score_line == "score 120"
            assert report.kills_line == "kills 3"
            assert report.wave_line == "wave 2"

    asyncio.run(_scenario())


def test_app_reuses_blood_neon_void_palette() -> None:
    """The arena theme reuses the hub.tcss Blood Neon Void hex values."""
    for hex_value in ("#0B0B12", "#CACACA", "#FFD23F", "#FF2A2A"):
        assert hex_value in ArenaScreen.CSS
    assert HP_GREEN == "#39FF6A"
    assert GOLD_NEXT == "#FFD23F"


def test_pause_is_a_flag_not_a_screen() -> None:
    """P toggles the pause flag; the screen stack never grows."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(_GOLD_PROBE,), spawn_enabled=False)
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            await pilot.press("P")
            assert screen.paused is True
            await pilot.press("P")
            assert screen.paused is False

    asyncio.run(_scenario())


def test_escape_releases_lock() -> None:
    """Esc drops the live lock; the foe survives for retyping."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(_GOLD_PROBE,), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.press("c")
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.arena_state.current is not None
            await pilot.press("escape")
            assert screen.arena_state.current is None
            assert _GOLD_PROBE in screen.foes_text

    asyncio.run(_scenario())


def test_pause_then_p_with_p_expecting_lock_unpauses() -> None:
    """P always unpauses, even when the live lock expects a literal P."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("aP",), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.press("a")
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.paused = True
            await pilot.press("P")
            assert screen.paused is False
            assert screen.arena_state.typed == 1

    asyncio.run(_scenario())


def test_boss_bar_pool_fits_max_bars() -> None:
    """The bossbar container sizes to the ProgressBar pool (fixed height)."""
    assert f"#bossbars {{ height: {MAX_BOSS_BARS}; }}" in ArenaScreen.CSS
