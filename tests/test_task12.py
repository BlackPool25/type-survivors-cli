"""Task 12: square kitty sprites, elliptical edge ring, visible core."""

from __future__ import annotations

import asyncio
import io
import math
import re
import sys
from typing import Final

import pytest
from par_textual_image import TerminalImage
from PIL import Image as PILImage
from textual.containers import Vertical

from tsurv.app import (
    MAX_FOES,
    SPAWN_OUTSIDE_MARGIN,
    ArenaScreen,
    TypeSurvivorsApp,
    sprite_image,
)
from tsurv.arena import EnemyKind, seconds_to_impact, spawn_radius_for_level
from tsurv.stage import canvas_xy, edge_spawn_distance
from tsurv.visuals import sprite_path

_SPRITE_PX: Final = 90
"""Every sprite paints at 90px: trimmed art centered on a 45px canvas."""

_WIDE_SIZE: Final = (200, 50)
"""Ghostty-wide pilot viewport from the screenshot evidence."""

_SMALL_SIZE: Final = (80, 24)
"""Compact pilot viewport: the floor guard must survive here."""

_ARENA_BG: Final = (11, 11, 18)
"""Void backdrop RGB: kitty transmits RGB, so sprites must bake this in."""

_EDGE_CELLS: Final = 2
"""Spawn ring tolerance: fresh foes sit this close to the field border."""

_ROSTER: Final = (
    "grunt_0.png",
    "grunt_1.png",
    "grunt_hit.png",
    "mite_0.png",
    "mite_1.png",
    "mite_hit.png",
    "hex_0.png",
    "hex_1.png",
    "hex_hit.png",
    "boss_0.png",
    "boss_1.png",
    "boss_hit.png",
    "core_0.png",
    "core_1.png",
    "core_hit.png",
)
"""Every shipped frame: same art, only background/aspect handling may change."""

_SPAWN_TICK_S: Final = 4.0
"""Public tick step that always trips the idle spawn gap exactly once."""

_SPEEDS: Final = {
    EnemyKind.GRUNT: 1.0,
    EnemyKind.MITE: 1.6,
    EnemyKind.HEX: 0.6,
    EnemyKind.ELITE: 1.0,
    EnemyKind.BOSS: 0.4,
}
"""Pinned convergence speeds: travel semantics must not move."""


def _placement_cells(
    widget: TerminalImage,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, int]:
    """Read back the kitty placement extent (public stdout bytes only).

    Forcing a fresh transmit (via a copy through the public image setter)
    keeps the readback independent of earlier paints and caches.
    """
    pic = widget.image
    assert isinstance(pic, PILImage.Image)
    buf = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", buf)
    widget.image = pic.copy()
    _ = widget.render()
    found: list[tuple[str, str]] = re.findall(r"c=(\d+),r=(\d+)", buf.getvalue())
    assert found, "kitty placement never transmitted"
    return int(found[-1][0]), int(found[-1][1])


def _assert_square_cells(cells: tuple[int, int]) -> None:
    """Kitty placements paint square pixels: cells are ~2x tall (2 cols = 1 row)."""
    cols, rows = cells
    assert (cols, rows) == (4, 2)


def _border_gap(x: int, y: int, width: int, height: int) -> int:
    """Closest distance of a canvas cell to any field border."""
    return min(x, width - 1 - x, y, height - 1 - y)


def test_roster_composites_onto_arena_bg() -> None:
    """Kitty drops alpha (convert RGB): baked bg must match the void.

    The renderer transmits ``image.convert("RGB")``, so transparent corners
    would arrive as pure black halo boxes. Compositing onto the arena void
    at load makes the box blend seamlessly; art pixels stay exact.
    """
    for filename in _ROSTER:
        pic = sprite_image(filename)
        assert pic is not None
        shown = pic.convert("RGB")
        width, height = shown.size
        assert width == height
        for corner in ((0, 0), (width - 1, 0), (0, height - 1)):
            assert shown.getpixel(corner) == _ARENA_BG
        raw = PILImage.open(sprite_path(filename)).convert("RGB")
        rw, rh = raw.size
        assert shown.getpixel((width // 2, height // 2)) == raw.getpixel(
            (rw // 2, rh // 2),
        )


@pytest.mark.parametrize("size", [_WIDE_SIZE, _SMALL_SIZE])
def test_kitty_paint_is_square_at_foe_and_core(
    size: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Square PNGs render square: the widget footprint preserves aspect."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            spawn_enabled=False,
            seed=11,
        )
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.pixdiag_text.startswith("pixels: kitty")
            foe = screen.query_one("#foe-sprite-0", TerminalImage)
            core = screen.query_one("#core-sprite", TerminalImage)
            _assert_square_cells(_placement_cells(foe, monkeypatch))
            _assert_square_cells(_placement_cells(core, monkeypatch))

    monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
    asyncio.run(_scenario())


@pytest.mark.parametrize("size", [_WIDE_SIZE, _SMALL_SIZE])
def test_core_art_paints_nonzero_at_center(
    size: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Sanctuary Core shows art, not an empty frame, at the center."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            spawn_enabled=False,
            seed=11,
        )
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            core = screen.query_one("#core-sprite", TerminalImage)
            assert core.display
            pic = core.image
            assert isinstance(pic, PILImage.Image)
            shown = pic.convert("RGB")
            width, height = shown.size
            assert width == height
            center = [
                shown.getpixel((x, y))
                for x in range(width // 2 - 4, width // 2 + 4)
                for y in range(height // 2 - 4, height // 2 + 4)
            ]
            assert any(pixel != _ARENA_BG for pixel in center)

    monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
    asyncio.run(_scenario())


@pytest.mark.parametrize(
    ("width", "height"),
    [(198, 33), (78, 7), (80, 24), (120, 30), (200, 50)],
)
@pytest.mark.parametrize("angle", [0.0, math.pi])
def test_edge_ring_reaches_long_borders(
    width: int,
    height: int,
    angle: float,
) -> None:
    """Long-axis spawns land at the field edge, not the inscribed circle."""
    distance = edge_spawn_distance(angle=angle, width=width, height=height)
    x, _ = canvas_xy(angle=angle, distance=distance, width=width, height=height)
    old_reach = min(width, height * 2) // 2 - 2
    assert abs(x - width // 2) > old_reach
    assert min(x, width - 1 - x) <= _EDGE_CELLS


@pytest.mark.parametrize(
    ("width", "height"),
    [(198, 33), (78, 7), (80, 24), (120, 30), (200, 50)],
)
@pytest.mark.parametrize("angle", [math.pi / 2, 3 * math.pi / 2])
def test_edge_ring_reaches_short_borders(
    width: int,
    height: int,
    angle: float,
) -> None:
    """Short-axis spawns land at the field edge on every viewport."""
    distance = edge_spawn_distance(angle=angle, width=width, height=height)
    _x, y = canvas_xy(angle=angle, distance=distance, width=width, height=height)
    assert min(y, height - 1 - y) <= _EDGE_CELLS


@pytest.mark.parametrize("size", [_WIDE_SIZE, _SMALL_SIZE])
def test_spawned_foes_land_near_field_edge(
    size: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public spawner deals foes onto the edge ring at any viewport."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=11)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.tick(_SPAWN_TICK_S)
            foes = screen.arena_state.enemies
            assert len(foes) == 1
            stage = screen.query_one("#stage")
            width = stage.content_size.width
            height = stage.content_size.height
            for foe in foes:
                assert foe.distance >= spawn_radius_for_level(1)
                want = edge_spawn_distance(
                    angle=foe.angle,
                    width=width,
                    height=height,
                )
                assert foe.distance == pytest.approx(want + SPAWN_OUTSIDE_MARGIN)
                x, y = canvas_xy(
                    angle=foe.angle,
                    distance=foe.distance,
                    width=width,
                    height=height,
                )
                assert _border_gap(x, y, width, height) <= _EDGE_CELLS

    monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
    asyncio.run(_scenario())


def test_travel_seconds_match_distance_over_speed() -> None:
    """Impact timing stays distance/speed: only spawn geometry moves."""
    for kind, speed in _SPEEDS.items():
        for distance in (1.0, 13.7):
            assert seconds_to_impact(kind, distance) == pytest.approx(
                distance / speed,
            )


def test_roster_crops_transparent_margins() -> None:
    """Tight boxes: clear margins shrink the opaque tile around each foe.

    The protocol layer flattens to RGB, so every sprite is an opaque box.
    Cropping clear margins keeps the box hugging the art: smaller boxes
    overlap the core less and halo less against the void.
    """
    for filename in _ROSTER:
        pic = sprite_image(filename)
        assert pic is not None
        assert pic.size == (_SPRITE_PX, _SPRITE_PX)


def test_core_paints_above_foes_and_below_chips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DOM order stacks foes, then the core, then the word chips on top.

    A foe closing in slides *under* the Sanctuary Core instead of hiding
    it, and the typed word chip is always the topmost paint.
    """

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
            stage = screen.query_one("#stage", Vertical)
            ids = [child.id for child in stage.children]
            core_at = ids.index("core-sprite")
            foe_at = [ids.index(f"foe-sprite-{i}") for i in range(MAX_FOES)]
            chip_at = [ids.index(f"foe-word-{i}") for i in range(MAX_FOES)]
            assert max(foe_at) < core_at < min(chip_at)

    monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
    asyncio.run(_scenario())
