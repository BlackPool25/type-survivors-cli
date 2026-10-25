"""Task 6: baked logo determinism, decrypt settle, and alpha-hub pilots."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.containers import Middle
from textual.widgets import Label

from tsurv.app import HubScreen, TypeSurvivorsApp
from tsurv.logo import decrypt_frames, hub_footer, render_logo
from tsurv.profile import Profile, RunSummary

_LOGO_W = 40
_DECRYPT_LIMIT = 4


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
