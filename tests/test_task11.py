"""Task 11: viewport-scaled edge spawns, kitty sprites that paint, leak guard."""

from __future__ import annotations

import asyncio
from typing import Final

import pytest
from par_textual_image import TerminalImage
from rich.console import Console

from tsurv.app import ArenaScreen, TypeSurvivorsApp
from tsurv.arena import (
    LEAK_DAMAGE,
    EnemyKind,
    seconds_to_impact,
    spawn_radius_for_level,
)
from tsurv.stage import canvas_xy, edge_spawn_distance

_SQUASH: Final = 2
"""Cell aspect squash, mirroring the stage ring math (cells are ~2x tall)."""

_WIDE_SIZE: Final = (200, 50)
"""Ghostty-wide pilot viewport: the spawn collapse was reported here."""

_SMALL_SIZE: Final = (80, 24)
"""Compact pilot viewport: the floor must preserve typing travel."""

_CELL_FRAC: Final = 0.7
"""Spawn canvas radius must reach this share of the inscribed reach."""

_FAR_FRAC: Final = 0.5
"""After seconds of travel the foe must still hold this share of the reach."""

_TRAVEL_FLOOR: Final = 8.0
"""World units a fresh wide-screen foe still holds after seconds of ticks."""

_OFFSET_TOL: Final = 3
"""Sprite widget origin must land within these cells of the foe canvas cell."""

_CORE_TOL: Final = 1
"""Core paint origin must land within this many cells of the stage center."""

_TICK_S: Final = 1.0
"""Public tick step driving travel (sim-neutral, render-owned assertions)."""

_SPAWN_TICK_S: Final = 4.0
"""Public tick step that always trips the idle spawn gap (3.2s) exactly once."""

_LEAK_COST: Final = 10.0
"""Pinned core-HP leak cost: the balance surface this task must not move."""

_LEVEL1_RADIUS: Final = 5.0
"""Pinned level-1 ring radius: the floor the edge scale never shrinks."""

_SPEED_SPAN: Final = 7.0
"""Speed probe span: seconds_to_impact(speed * span) must equal the span."""


def _reach(width: int, height: int) -> int:
    """Inscribed-circle reach in cells (independent copy of the ring formula)."""
    return max(min(width, height * _SQUASH) // _SQUASH - _SQUASH, 0)


def _cell_radius(x: int, y: int, cx: int, cy: int) -> float:
    """Unsquashed cell distance from the core (vertical cells count double)."""
    return float(abs(x - cx) + abs(y - cy) * _SQUASH)


def _paint_text(widget: TerminalImage) -> str:
    """Flatten one widget's render to plain text (blank when nothing paints)."""
    console = Console(width=40, height=10, record=True)
    rendered = widget.render()
    if isinstance(rendered, str):
        return rendered
    console.print(rendered, end="")
    return console.export_text().strip()


def _canvas_pos(
    screen: ArenaScreen,
    index: int,
    width: int,
    height: int,
) -> tuple[int, int]:
    """Canvas cell of one foe through the public ring math."""
    foe = screen.arena_state.enemies[index]
    return canvas_xy(
        angle=foe.angle,
        distance=foe.distance,
        width=width,
        height=height,
    )


async def _fresh_wave1_foe(size: tuple[int, int]) -> tuple[float, float, int, int]:
    """Drive the public spawner once; return foe distance, angle, stage size.

    The spawner path (not a hand-placed foe) is what must sit at the edge.
    The last enemy is always the fresh one, even if a pause tick spawned first.
    """
    app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=11)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ArenaScreen)
        screen.tick(_SPAWN_TICK_S)
        foes = screen.arena_state.enemies
        assert foes
        foe = foes[-1]
        stage = screen.query_one("#stage")
        return (
            foe.distance,
            foe.angle,
            stage.content_size.width,
            stage.content_size.height,
        )


def test_edge_spawn_distance_grows_with_viewport_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wave-1 foe spawns near the field edge on a wide viewport, not the core."""

    async def _scenario() -> None:
        distance, angle, width, height = await _fresh_wave1_foe(_WIDE_SIZE)
        edge = edge_spawn_distance(angle=angle, width=width, height=height)
        assert distance == pytest.approx(max(spawn_radius_for_level(1), edge))
        x, y = canvas_xy(
            angle=angle,
            distance=distance,
            width=width,
            height=height,
        )
        assert _cell_radius(x, y, width // 2, height // 2) >= _CELL_FRAC * _reach(
            width,
            height,
        )

    monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
    asyncio.run(_scenario())


def test_edge_spawn_distance_keeps_floor_small(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Small screens keep at least level-1 travel: the floor never shrinks."""

    async def _scenario() -> None:
        distance, angle, width, height = await _fresh_wave1_foe(_SMALL_SIZE)
        edge = edge_spawn_distance(angle=angle, width=width, height=height)
        assert distance == pytest.approx(max(spawn_radius_for_level(1), edge))

    monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
    asyncio.run(_scenario())


def test_fresh_foe_travels_long_and_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh wave-1 foe survives seconds of ticks, visibly gliding core-ward."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=11)
        async with app.run_test(size=_WIDE_SIZE) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.tick(_SPAWN_TICK_S)
            stage = screen.query_one("#stage")
            width = stage.content_size.width
            height = stage.content_size.height
            reach = _reach(width, height)
            before = screen.arena_state.enemies[-1].distance
            screen.tick(_TICK_S)
            after_state = screen.arena_state
            assert after_state.hp == after_state.max_hp
            foe = after_state.enemies[-1]
            assert foe.distance < before
            assert foe.distance >= _TRAVEL_FLOOR
            x, y = _canvas_pos(screen, len(after_state.enemies) - 1, width, height)
            assert _cell_radius(x, y, width // 2, height // 2) >= _FAR_FRAC * reach

    monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
    asyncio.run(_scenario())


def test_kitty_sprites_paint_at_foe_and_core_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kitty mode paints PNG widgets with nonzero size at foe/core cells."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            spawn_enabled=False,
            seed=11,
        )
        async with app.run_test(size=_WIDE_SIZE) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.pixdiag_text.startswith("pixels: kitty")
            stage = screen.query_one("#stage")
            width = stage.content_size.width
            height = stage.content_size.height
            core = screen.query_one("#core-sprite", TerminalImage)
            assert core.display
            assert core.image is not None
            assert core.size.width > 0
            assert core.size.height > 0
            assert _paint_text(core) != ""
            stage_cx = stage.region.x + stage.region.width // 2
            stage_cy = stage.region.y + stage.region.height // 2
            assert abs(core.region.x + _CORE_TOL - stage_cx) <= _OFFSET_TOL
            assert abs(core.region.y + _CORE_TOL - stage_cy) <= _OFFSET_TOL
            sprite = screen.query_one("#foe-sprite-0", TerminalImage)
            assert sprite.display
            assert sprite.image is not None
            assert _paint_text(sprite) != ""
            x, y = _canvas_pos(screen, 0, width, height)
            assert abs(sprite.styles.offset.x.value - x) <= _OFFSET_TOL
            assert abs(sprite.styles.offset.y.value - y) <= _OFFSET_TOL

    monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
    asyncio.run(_scenario())


def test_kitty_sprites_paint_small(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kitty mode paints the core and foe sprites on compact screens too."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            spawn_enabled=False,
            seed=11,
        )
        async with app.run_test(size=_SMALL_SIZE) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            core = screen.query_one("#core-sprite", TerminalImage)
            assert core.display
            assert core.image is not None
            assert _paint_text(core) != ""
            sprite = screen.query_one("#foe-sprite-0", TerminalImage)
            assert sprite.image is not None
            assert _paint_text(sprite) != ""

    monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
    asyncio.run(_scenario())


def test_balance_numbers_untouched() -> None:
    """Leak damage, convergence speeds, and the level-1 radius never move."""
    assert LEAK_DAMAGE == _LEAK_COST
    assert spawn_radius_for_level(1) == _LEVEL1_RADIUS
    speeds = {
        EnemyKind.GRUNT: 1.0,
        EnemyKind.MITE: 1.6,
        EnemyKind.HEX: 0.6,
        EnemyKind.ELITE: 1.0,
        EnemyKind.BOSS: 0.4,
    }
    for kind, speed in speeds.items():
        assert seconds_to_impact(kind, speed * _SPEED_SPAN) == pytest.approx(
            _SPEED_SPAN,
        )
