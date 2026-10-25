"""Task 6: baked logo determinism, decrypt settle, and alpha-hub pilots."""

from __future__ import annotations

import asyncio
import re
from typing import Final

from rich.text import Text
from textual.containers import Middle
from textual.widgets import Label

from tsurv.app import HubScreen, TypeSurvivorsApp
from tsurv.logo import decrypt_frames, hub_footer, render_logo
from tsurv.profile import Profile, RunSummary

_LOGO_W = 40
_FULL_W = 48
"""Full hub logo width at viewport height >= 30 (matches app column budget)."""
_DECRYPT_LIMIT = 4
_VIEW_W = 80
_VIEW_H = 24
_SHORT_LOGO_ROWS = 5
"""Compact logo height: the 24-cell bake at 80x24 must fit, not clip."""


def test_bake_deterministic() -> None:
    """Same PNG + width bakes the same cells twice (color and mono)."""
    assert render_logo(_LOGO_W) == render_logo(_LOGO_W)
    assert render_logo(_LOGO_W, mono=True) == render_logo(_LOGO_W, mono=True)


def test_render_logo_width_matches_cells() -> None:
    """Every baked row spans exactly the requested cell width."""
    rows = render_logo(_LOGO_W, mono=True).splitlines()
    assert len(rows) >= 1
    assert all(len(row) == _LOGO_W for row in rows)
    color = Text.from_ansi(render_logo(_LOGO_W))
    assert all(len(row) == _LOGO_W for row in color.plain.splitlines())


def test_decrypt_frames_settle_on_input() -> None:
    """Sampled TTE frames are text and the last one is the settled input."""
    frames = decrypt_frames("AB", limit=_DECRYPT_LIMIT)
    assert 1 <= len(frames) <= _DECRYPT_LIMIT + 1
    assert all(isinstance(frame, str) for frame in frames)
    assert frames[-1] == "AB"


def test_hub_footer_shows_best_gold_level() -> None:
    """Footer carries best WPM, banked gold, and top wave."""
    profile = Profile(
        gold=10,
        runs=(
            RunSummary(
                wpm_samples=(40.0, 44.0),
                accuracy=0.9,
                kills=5,
                wave=3,
                score=100,
                duration_s=60.0,
            ),
        ),
    )
    footer = hub_footer(profile)
    assert "42 WPM" in footer
    assert "10" in footer
    assert "LV 3" in footer


def test_hub_footer_empty_profile() -> None:
    """A fresh profile still shows a zeroed footer."""
    footer = hub_footer(Profile())
    assert "0 WPM" in footer
    assert "LV 1" in footer


def test_color_bake_terminal_rows_match_mono() -> None:
    """Color half-cell bake spans the same terminal rows as the mono bake."""
    mono_rows = render_logo(_LOGO_W, mono=True).splitlines()
    color_rows = Text.from_ansi(render_logo(_LOGO_W)).plain.splitlines()
    assert len(color_rows) == len(mono_rows)


_BG_CUTOFF = 60
_RED_FLOOR = 200
_BLUE_FLOOR = 150
_GREEN_FLOOR = 150
_BLUE_PURITY = 100
_RED_PURITY = 150


def _cell_map(text: Text, cells_w: int, rows: int) -> list[str]:
    """Foreground color family per cell: R(ed), G(old), B(lue), .(bg), ?(halo)."""
    bucketed: list[str] = []
    for i in range(rows):
        row_chars: list[str] = []
        for x in range(cells_w):
            offset = i * (cells_w + 1) + x
            style = next(
                (span.style for span in text.spans if span.start <= offset < span.end),
                "",
            )
            triple = re.search(r"#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})", str(style))
            r, g, b = (int(v, 16) for v in triple.groups()) if triple else (0, 0, 0)
            cell = (
                "."
                if max(r, g, b) < _BG_CUTOFF
                else "R"
                if r > _RED_FLOOR and b < _BLUE_PURITY and g < _RED_PURITY
                else "G"
                if r > _RED_FLOOR and g > _GREEN_FLOOR
                else "B"
                if b > _BLUE_FLOOR
                else "?"
            )
            row_chars.append(cell)
        bucketed.append("".join(row_chars))
    return bucketed


_COLOR_MAP: Final = (
    "..............................................RB",
    "................RRR.G.G.RRR.GGG...............RB",
    ".................R...G..RRR.GGG...............RB",
    "..............................................RB",
    ".......BB.B.B.BBB.B.B..B..B.B..B..BBB..BB.....RB",
    "......BB..BBB.B.B..B...B...B...B..B.B.BB......RB",
    "..............................................RB",
    "..............................................RB",
    "..............................................RB",
    "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
)
"""Baked TYPE/SURVIVORS foreground map at 48 cells: solid runs, not mush."""


def test_color_bake_keeps_solid_glyph_runs() -> None:
    """TYPE capitals bake as solid runs, not sparse NEAREST-decimation mush."""
    assert _cell_map(Text.from_ansi(render_logo(_FULL_W)), 48, 10) == list(_COLOR_MAP)


_MONO_SNAPSHOT: Final = (
    "##%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#\n"
    "##@@@@@@@@@@@@##%#*#%##@-=%@@@@@@@@@@@@#\n"
    "##@@@@@@@@@@@@@%@@*@%%%@**%@@@@@@@@@@@@#\n"
    "##@@@@%#@%%%%#%%%%@%%@%@%@%%@##%@#%@@@@#\n"
    "##@@@#+*@**#*#*%##@%#@%#%%##@**#*+%@@@@#\n"
    "##@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@#\n"
    "##@@@@@@%%%%%%%%%%%%%%%%%%%%%%%%@@@@@@@#\n"
    "##%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#"
)
"""Mono bake of assets/logo.png at 40 cells: frame, TYPE, SURVIVORS, rule."""


def test_mono_bake_matches_logo_snapshot() -> None:
    """Box-downsampled mono bake keeps the pixel logo legible, not mush."""
    assert render_logo(_LOGO_W, mono=True) == _MONO_SNAPSHOT


def test_hub_has_all_sections_at_80x24() -> None:
    """Hub shows logo, six buttons, and stats footer, vertically centered."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile=Profile(),
            start_at_hub=True,
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HubScreen)
            assert screen.query_one("#hub-middle", Middle) is not None
            logo = screen.query_one("#hub-logo", Label)
            assert logo.content
            listed = str(screen.query_one("#hub-list", Label).content)
            for key in ("S", "P", "R", "H", "E", "Q"):
                assert key in listed
            stats = str(screen.query_one("#hub-stats", Label).content)
            assert "WPM" in stats
            assert "gold" in stats
            assert "LV" in stats
            logo_y = logo.region.y
            list_y = screen.query_one("#hub-list", Label).region.y
            stats_y = screen.query_one("#hub-stats", Label).region.y
            assert logo_y <= list_y <= stats_y

    asyncio.run(_scenario())


def test_hub_fits_80x24_no_clipping() -> None:
    """Every hub section sits fully inside the 80x24 viewport, logo shrunk."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile=Profile(),
            start_at_hub=True,
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HubScreen)
            for selector in (
                "#hub-logo",
                "#hub-banner",
                "#subtitle",
                "#hub-header",
                "#hub-panel",
                "#hub-stats",
                "#hub-hint",
            ):
                region = screen.query_one(selector).region
                assert region.y >= 0, selector
                assert region.bottom <= _VIEW_H, selector
                assert region.x >= 0, selector
                assert region.right <= _VIEW_W, selector
            logo_height = screen.query_one("#hub-logo", Label).region.height
            assert logo_height <= _SHORT_LOGO_ROWS

    asyncio.run(_scenario())
