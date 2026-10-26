"""Stage rebuild: renderer probe, canvas coords, cell art, field pilots."""

from __future__ import annotations

import asyncio
import math
import os
from typing import TYPE_CHECKING, Final

from par_textual_image import TerminalImage
from rich.text import Text

from tsurv.app import ArenaScreen, TypeSurvivorsApp
from tsurv.arena import EnemyKind
from tsurv.stage import (
    CELL_ART,
    CELL_ART_HIT,
    CORE_ART,
    CORE_ART_HIT,
    ArenaCanvas,
    FieldSprite,
    RendererKind,
    art_origin,
    canvas_xy,
    chip_origin,
    edge_spawn_distance,
    probe_renderer,
    render_field,
    select_renderer,
    sprite_color,
)

if TYPE_CHECKING:
    import pytest

_CANVAS_SIZES: Final = ((80, 24), (120, 30))
_RING_SPAWNS: Final = 8
_GOLDEN_ANGLE: Final = math.pi * (3.0 - math.sqrt(5.0))
_SPREAD_MIN: Final = 18
"""Min x-span of the distance-5 ring: the field reads wide, not stacked."""
_Y_SPAN_MIN: Final = 6
"""Min y-span of the distance-5 ring: foes sit above and below the core."""
_DRIFT_CELLS: Final = 3
"""Wave-clear drift used by the scroll pilot (mirrors the app constant)."""
_ART_ROWS_MIN: Final = 4
"""Smallest roster art height in pixels (the mite)."""
_ART_COLS_MIN: Final = 3
"""Smallest roster art width in pixels (the mite)."""
_CORE_PAINT_HALF_W: Final = 2
"""Half the painted core PNG width: square trim leaves a 4x2 paint."""
_CORE_PAINT_HALF_H: Final = 1
"""Half the painted core PNG height: square trim leaves a 4x2 paint."""


def test_force_truepixel_enables_kitty() -> None:
    """TSURV_TRUEPIXEL=1 forces the kitty path and names the reason."""
    pick = select_renderer(truepixel="1")
    assert pick.kind is RendererKind.KITTY
    assert pick.label == "pixels: kitty (TSURV_TRUEPIXEL=1)"


def test_force_zero_disables_truepixel() -> None:
    """TSURV_TRUEPIXEL=0 forces cells even on a graphics terminal."""
    pick = select_renderer(truepixel="0", term_program="ghostty")
    assert pick.kind is RendererKind.CELLS
    assert pick.label == "pixels: cells (TSURV_TRUEPIXEL=0)"


def test_ghostty_term_program_detected() -> None:
    """Ghostty advertises kitty graphics: probe names it, no TTY query."""
    pick = select_renderer(term_program="ghostty")
    assert pick.kind is RendererKind.KITTY
    assert pick.label == "pixels: kitty (ghostty)"


def test_graphics_terminal_variants_detected() -> None:
    """Kitty/WezTerm/VSCode/xterm-ghostty all advertise a graphics protocol."""
    for program in ("kitty", "WezTerm", "vscode", "xterm-ghostty"):
        pick = select_renderer(term_program=program)
        assert pick.kind is RendererKind.KITTY
    assert select_renderer(term="xterm-kitty").kind is RendererKind.KITTY


def test_unknown_terminal_falls_back_to_cells() -> None:
    """No allowlist hit and no force flag: cells with an honest reason."""
    pick = select_renderer(term_program="tmux", term="screen-256color")
    assert pick.kind is RendererKind.CELLS
    assert pick.label == "pixels: cells (no graphics protocol)"


def test_par_env_kitty_honored() -> None:
    """PAR_TERM_GRAPHICS=kitty (par's own fast path) selects kitty."""
    pick = select_renderer(par_graphics="kitty")
    assert pick.kind is RendererKind.KITTY
    assert pick.label == "pixels: kitty (PAR_TERM_GRAPHICS=kitty)"


def test_force_wins_over_everything() -> None:
    """The explicit TSURV_TRUEPIXEL flag beats env hints and allowlists."""
    assert select_renderer(truepixel="0", par_graphics="kitty").kind is (
        RendererKind.CELLS
    )
    pick = select_renderer(truepixel="1", term_program="dumb")
    assert pick.kind is RendererKind.KITTY


def test_par_env_sixel_selects_sixel() -> None:
    """PAR_TERM_GRAPHICS=sixel pins the sixel renderer (Windows Terminal)."""
    pick = select_renderer(par_graphics="sixel")
    assert pick.kind is RendererKind.SIXEL
    assert pick.label == "pixels: sixel (PAR_TERM_GRAPHICS=sixel)"


def test_par_env_iterm2_selects_iterm2() -> None:
    """PAR_TERM_GRAPHICS=iterm2 pins the iTerm2 renderer."""
    pick = select_renderer(par_graphics="iterm2")
    assert pick.kind is RendererKind.ITERM2


def test_windows_terminal_session_selects_sixel() -> None:
    """WT_SESSION advertises sixel even when TERM_PROGRAM is stripped."""
    pick = select_renderer(
        term_program="tmux",
        term="screen-256color",
        wt_session="abc123",
    )
    assert pick.kind is RendererKind.SIXEL
    assert pick.reason == "wt-session"


def test_iterm2_env_selects_iterm2() -> None:
    """LC_TERMINAL=iTerm2 pins the iTerm2 renderer on unknown terms."""
    pick = select_renderer(
        term_program="tmux",
        term="screen-256color",
        lc_terminal="iTerm2",
    )
    assert pick.kind is RendererKind.ITERM2


def test_probe_auto_detect_maps_sixel() -> None:
    """Lib auto-detect of sixel wins before the kitty TTY query."""
    pick = probe_renderer(
        {"TERM_PROGRAM": "tmux", "TERM": "screen-256color"},
        query_tty=lambda: False,
        detect=lambda: "sixel",
    )
    assert pick.kind is RendererKind.SIXEL
    assert pick.label == "pixels: sixel (auto-sixel)"


def test_probe_reads_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """The startup probe reads the live environment (Ghostty path)."""
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("TSURV_TRUEPIXEL", raising=False)
    assert probe_renderer(os.environ).kind is RendererKind.KITTY
    monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
    assert probe_renderer(os.environ).kind is RendererKind.CELLS


def test_canvas_center_at_zero_distance() -> None:
    """Distance zero lands dead-center at both pilot viewports."""
    assert canvas_xy(angle=0.0, distance=0.0, width=80, height=24) == (40, 12)
    assert canvas_xy(angle=1.0, distance=0.0, width=120, height=30) == (60, 15)


def test_canvas_spread_uses_full_field() -> None:
    """Golden-angle ring at distance 5 spans the field on both axes."""
    xs: list[int] = []
    ys: list[int] = []
    width, height = 80, 24
    cx, cy = width // 2, height // 2
    for slot in range(_RING_SPAWNS):
        x, y = canvas_xy(
            angle=slot * _GOLDEN_ANGLE,
            distance=5.0,
            width=width,
            height=height,
        )
        xs.append(x)
        ys.append(y)
    assert min(xs) < cx < max(xs)
    assert max(xs) - min(xs) >= _SPREAD_MIN
    assert min(ys) < cy < max(ys)
    assert max(ys) - min(ys) >= _Y_SPAN_MIN


def test_canvas_clamps_to_viewport() -> None:
    """Extreme distance and scroll never escape the canvas."""
    for width, height in _CANVAS_SIZES:
        x, y = canvas_xy(
            angle=0.0,
            distance=999.0,
            width=width,
            height=height,
            scroll=50,
        )
        assert 0 <= x < width
        assert 0 <= y < height


def test_canvas_caps_radius_at_viewport_edge() -> None:
    """Overshoot distances clamp to the border ellipse (foes spawn on-screen)."""
    width = 80
    height = 24
    edge = canvas_xy(angle=0.0, distance=10_000.0, width=width, height=height)
    assert edge == canvas_xy(
        angle=0.0,
        distance=edge_spawn_distance(angle=0.0, width=width, height=height),
        width=width,
        height=height,
    )
    assert 0 <= edge[0] < width
    assert 0 <= edge[1] < height


def test_canvas_scroll_shifts_east() -> None:
    """Wave-clear drift pans placements east (background pan, not foe sim)."""
    plain = canvas_xy(angle=0.0, distance=4.0, width=80, height=24)
    drifted = canvas_xy(
        angle=0.0,
        distance=4.0,
        width=80,
        height=24,
        scroll=_DRIFT_CELLS,
    )
    assert drifted[0] - plain[0] == _DRIFT_CELLS
    assert drifted[1] == plain[1]


def test_every_roster_member_has_art() -> None:
    """Every kind plus the core ships normal and hit art with clean rows."""
    arts = {**CELL_ART, None: CORE_ART}
    hits = {**CELL_ART_HIT, None: CORE_ART_HIT}
    assert set(CELL_ART) == set(EnemyKind)
    for key, art in arts.items():
        assert len(art) >= _ART_ROWS_MIN
        width = len(art[0])
        assert width >= _ART_COLS_MIN
        assert all(len(row) == width for row in art)
        assert all(set(row) <= {"#", " ", "◌"} for row in art)
        assert key in hits
        assert len(hits[key]) == len(art)
        assert all(len(row) == width for row in hits[key])
        assert hits[key] != art


def test_boss_art_larger_than_grunt() -> None:
    """Size reads as threat: the boss art dwarfs the grunt on both axes."""
    grunt = CELL_ART[EnemyKind.GRUNT]
    boss = CELL_ART[EnemyKind.BOSS]
    assert len(boss[0]) > len(grunt[0])
    assert len(boss) > len(grunt)


def test_roster_shapes_distinct() -> None:
    """No two roster arts share a silhouette (identity is shape, not color)."""
    shapes = [CORE_ART, *[CELL_ART[kind] for kind in EnemyKind]]
    assert len(set(shapes)) == len(shapes)


def test_sprite_colors_distinct_and_mono_blank() -> None:
    """Kinds wear distinct colors, hit flashes white, mono carries no color."""
    colors = {sprite_color(kind, hit=False, mono=False) for kind in EnemyKind} | {
        sprite_color(None, hit=False, mono=False),
    }
    assert None not in colors
    assert len(colors) == len(EnemyKind) + 1
    assert sprite_color(EnemyKind.GRUNT, hit=True, mono=False) == "#FFFFFF"
    assert sprite_color(EnemyKind.BOSS, hit=False, mono=True) is None
    assert sprite_color(None, hit=True, mono=True) is None


def test_art_origin_centers_art() -> None:
    """Art top-left centers the block on the mapped canvas point."""
    tx, ty = art_origin(40, 12, CELL_ART[EnemyKind.GRUNT])
    assert tx == 40 - len(CELL_ART[EnemyKind.GRUNT][0]) // 2
    assert ty == 12 - (len(CELL_ART[EnemyKind.GRUNT]) + 1) // 4


def test_chip_origin_prefers_right_flips_left() -> None:
    """Chips sit right of the sprite, flipping left at the viewport edge."""
    right = chip_origin(10, 5, art_w=5, art_h=3, chip_len=8, width=80)
    assert right == (16, 6)
    left = chip_origin(70, 5, art_w=5, art_h=3, chip_len=8, width=80)
    assert left == (61, 6)


def test_render_field_draws_sprite_and_chip() -> None:
    """The field composites half-block art plus the word chip as text."""
    chip = Text("● cat >")
    width, height = 30, 10
    field = render_field(
        width=width,
        height=height,
        sprites=(
            FieldSprite(
                x=2,
                y=2,
                art=CELL_ART[EnemyKind.GRUNT],
                color="#24AEEB",
                chip=chip,
            ),
        ),
    )
    assert "● cat >" in field.plain
    assert "█" in field.plain or "▀" in field.plain
    assert len(field.plain.split("\n")) == height


def test_render_field_mono_has_no_spans() -> None:
    """Mono fields carry shape only: art glyphs plus chip, zero style spans."""
    width, height = 30, 10
    field = render_field(
        width=width,
        height=height,
        sprites=(
            FieldSprite(
                x=2,
                y=2,
                art=CELL_ART[EnemyKind.MITE],
                color=None,
                chip=Text("● dog »"),
            ),
        ),
    )
    assert len(field.spans) == 0
    assert "● dog »" in field.plain


def test_render_field_clips_at_edges() -> None:
    """Sprites and chips crossing the border clip instead of raising."""
    width, height = 20, 6
    field = render_field(
        width=width,
        height=height,
        sprites=(
            FieldSprite(
                x=16,
                y=4,
                art=CELL_ART[EnemyKind.BOSS],
                color="#FF2A2A",
                chip=Text("●● overlord ☠"),
            ),
        ),
    )
    assert len(field.plain.split("\n")) == height
    assert all(len(row) <= width for row in field.plain.split("\n"))


def test_pilot_cells_field_shows_chips_and_centered_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cells mode: word chips read in the field; core art sits on center."""

    async def _scenario(size: tuple[int, int]) -> None:
        monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.pixdiag_text == "pixels: cells (TSURV_TRUEPIXEL=0)"
            canvas = screen.query_one("#field", ArenaCanvas)
            field = canvas.rendered
            assert "cat" in field.plain
            stage = screen.query_one("#stage")
            rows = field.plain.split("\n")
            cy = stage.size.height // 2
            assert cy < len(rows)
            cx = stage.size.width // 2
            span = rows[cy][max(0, cx - 5) : cx + 6]
            assert span.strip(" ") != ""

    asyncio.run(_scenario((80, 24)))
    asyncio.run(_scenario((120, 30)))


def test_pilot_kitty_mode_positions_sprites_and_diag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kitty mode: PNG widgets ride canvas coords; diag names the reason."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.pixdiag_text == "pixels: kitty (TSURV_TRUEPIXEL=1)"
            stage = screen.query_one("#stage")
            core = screen.query_one("#core-sprite", TerminalImage)
            assert core.display
            assert core.image is not None
            cx = stage.size.width // 2
            cy = stage.size.height // 2
            assert core.styles.offset.x.value == cx - _CORE_PAINT_HALF_W
            assert core.styles.offset.y.value == cy - _CORE_PAINT_HALF_H

    monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
    asyncio.run(_scenario())
