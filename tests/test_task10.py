"""Task 10 follow-up: Ghostty probe fallback, wave spawns, death recap."""

from __future__ import annotations

import asyncio
import math
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from par_textual_image import TerminalImage
from textual.containers import Center, Middle
from textual.widgets import Button, Label, Sparkline

from tsurv.app import (
    SPAWN_OUTSIDE_MARGIN,
    ArenaScreen,
    ReportScreen,
    TypeSurvivorsApp,
    report_stats_text,
)
from tsurv.arena import (
    initial_arena,
    spawn_count_for_level,
    spawn_radius_for_level,
    world_xy,
)
from tsurv.stage import (
    RendererKind,
    edge_spawn_distance,
    probe_renderer,
    select_renderer,
    world_to_cell,
)

if TYPE_CHECKING:
    import pytest

_UNADVERTISED_ENV: Final = {"TERM": "tmux-256color"}
"""Ghostty behind tmux/ssh: TERM_PROGRAM stripped, TERM generic, no ads."""

_MIN_SEPARATION: Final = 0.25
"""Brief floor: simultaneous foes land at least 0.25 rad apart."""

_MIN_CELLS_OUT: Final = 5
"""Travel reads: a fresh wave sits at least this far from the core."""


def test_unadvertised_terminal_stays_cells_without_query() -> None:
    """No allowlist hit and no TTY answer: cells with an honest reason."""
    pick = select_renderer(term_program="tmux", term="tmux-256color")
    assert pick.kind is RendererKind.CELLS
    assert pick.label == "pixels: cells (no graphics protocol)"


def test_tty_query_true_selects_kitty() -> None:
    """A TTY that answers the kitty query reads as kitty, env or no env."""
    pick = select_renderer(
        term_program="tmux",
        term="tmux-256color",
        tty_kitty=True,
    )
    assert pick.kind is RendererKind.KITTY
    assert pick.label == "pixels: kitty (tty-query)"


def test_probe_consults_tty_query_on_unknown_cells() -> None:
    """Ghostty-behind-tmux answers the query: kitty despite the bare env."""
    pick = probe_renderer(_UNADVERTISED_ENV, query_tty=lambda: True)
    assert pick.kind is RendererKind.KITTY
    assert pick.label == "pixels: kitty (tty-query)"


def test_probe_query_timeout_stays_cells() -> None:
    """A silent TTY keeps the cells fallback and its honest reason."""
    pick = probe_renderer(_UNADVERTISED_ENV, query_tty=lambda: False)
    assert pick.kind is RendererKind.CELLS
    assert pick.label == "pixels: cells (no graphics protocol)"


def test_explicit_pins_beat_tty_query() -> None:
    """Force flags and par hints win over a chatty TTY either way."""
    assert (
        probe_renderer({"TSURV_TRUEPIXEL": "0"}, query_tty=lambda: True).kind
        is RendererKind.CELLS
    )
    assert (
        probe_renderer({"PAR_TERM_GRAPHICS": "sixel"}, query_tty=lambda: True).kind
        is RendererKind.SIXEL
    )
    assert (
        probe_renderer({"TSURV_TRUEPIXEL": "1"}, query_tty=lambda: False).kind
        is RendererKind.KITTY
    )


def _angular_gap(first: float, second: float) -> float:
    """Shortest circular distance between two ring angles."""
    return abs((first - second + math.pi) % (2.0 * math.pi) - math.pi)


def test_spawn_foe_deals_simultaneous_wave() -> None:
    """One spawn tick at wave 3 deals the whole ring wave at radius R(3)."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=1)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.set_restored(replace(initial_arena(), wave=3))
            for _ in range(10):
                screen.tick(0.5)
                if screen.arena_state.enemies:
                    break
            foes = screen.arena_state.enemies
            assert len(foes) == spawn_count_for_level(3)
            radius = spawn_radius_for_level(3)
            stage = screen.query_one("#stage")
            width = stage.content_size.width
            height = stage.content_size.height
            for foe in foes:
                edge = edge_spawn_distance(
                    angle=foe.angle,
                    width=width,
                    height=height,
                )
                assert foe.distance == max(radius, edge) + SPAWN_OUTSIDE_MARGIN
            assert _angular_gap(foes[0].angle, foes[1].angle) >= _MIN_SEPARATION

    asyncio.run(_scenario())


def test_spawned_wave_reads_off_core_and_travels() -> None:
    """Fresh foes sit cells away from the core and close in over ticks."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.spawn_test_enemy("cat", distance=spawn_radius_for_level(3))
            foe = screen.arena_state.enemies[0]
            x, y = world_xy(foe)
            cx, cy = world_to_cell(x=x, y=y, width=80, height=24)
            assert max(abs(cx - 40), abs(cy - 12)) >= _MIN_CELLS_OUT
            before = foe.distance
            screen.tick(1.0)
            after = screen.arena_state.enemies[0].distance
            assert after == before - 1.0

    asyncio.run(_scenario())


def test_pilot_kitty_mounts_foe_and_core_sprites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kitty mode: core and live-foe PNG widgets mount with images set."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            core = screen.query_one("#core-sprite", TerminalImage)
            assert core.display
            assert core.image is not None
            screen.spawn_test_enemy("dog", distance=spawn_radius_for_level(2))
            await pilot.pause()
            foe = screen.query_one("#foe-sprite-0", TerminalImage)
            assert foe.display
            assert foe.image is not None

    monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
    asyncio.run(_scenario())


def test_report_stats_text_lists_six_rows() -> None:
    """The recap table names net WPM, accuracy, consistency, streak, kills."""
    text = report_stats_text(
        net=42.5,
        accuracy=0.93,
        consistency=78.0,
        best_streak=7,
        kills=11,
        level=4,
    )
    plain = text.plain
    for row in ("42.5", "93%", "78", "7", "11", "4"):
        assert row in plain


def test_report_stats_text_marks_rough_consistency() -> None:
    """Under-ten samples read as a shrug, never as a confident number."""
    assert (
        "~"
        in report_stats_text(
            net=0.0,
            accuracy=1.0,
            consistency=None,
            best_streak=0,
            kills=0,
            level=1,
        ).plain
    )


def test_report_screen_centered_with_chart_and_retry() -> None:
    """The recap is centered, charts WPM, tables stats, and offers retry."""

    async def _scenario(size: tuple[int, int], *, expect_offset: bool) -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            samples = (12.0, 24.0, 18.0)
            _ = app.push_screen(
                ReportScreen(
                    score=120,
                    kills=3,
                    wave=2,
                    wpm=samples,
                    net=42.5,
                    accuracy=0.93,
                    consistency=78.0,
                    best_streak=7,
                ),
            )
            await pilot.pause()
            report = app.screen
            assert isinstance(report, ReportScreen)
            assert report.query_one(Center)
            assert report.query_one(Middle)
            spark = report.query_one("#report-spark", Sparkline)
            assert tuple(spark.data or ()) == samples
            assert report.query_one("#report-stats", Label)
            assert report.query_one("#report-retry", Button)
            column = report.query_one("#report-column")
            if expect_offset:
                assert column.region.x > 0
            else:
                assert column.region.x == 0
                assert "text-align: center" in ReportScreen.CSS

    asyncio.run(_scenario((80, 24), expect_offset=False))
    asyncio.run(_scenario((200, 50), expect_offset=True))


def test_retry_key_starts_fresh_run() -> None:
    """Death recap: R drops the dead run and deals a fresh wave-1 arena."""

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
            await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, ReportScreen)
            await pilot.press("r")
            await pilot.pause()
            fresh = app.screen
            assert isinstance(fresh, ArenaScreen)
            assert fresh.arena_state.wave == 1
            assert fresh.arena_state.hp == fresh.arena_state.max_hp

    asyncio.run(_scenario())


def test_retry_button_starts_fresh_run() -> None:
    """Death recap: clicking Retry also deals a fresh wave-1 arena."""

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
            await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, ReportScreen)
            _ = await pilot.click("#report-retry")
            await pilot.pause()
            fresh = app.screen
            assert isinstance(fresh, ArenaScreen)
            assert fresh.arena_state.wave == 1

    asyncio.run(_scenario())


def test_report_builder_feeds_wpm_trail() -> None:
    """The death card charts the run's own per-second WPM, never a blank."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            await pilot.press("c", "a", "t")
            await pilot.pause()
            for _ in range(10):
                screen.spawn_test_enemy("zz", distance=0.05)
                screen.tick(5.0)
            await pilot.pause()
            report = app.report_screen()
            assert report.wpm_trail != ()
            for line in report.card_text.split("\n"):
                if line.startswith("wpm "):
                    assert "—" not in line

    asyncio.run(_scenario())
