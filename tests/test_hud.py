"""RPG HUD rails: red HP bar, streak, score, ACC, consistency, wave cycle."""

from __future__ import annotations

import asyncio
from typing import Final

from rich.text import Text
from textual.widgets import Label

from tsurv.app import (
    BOSS_EVERY,
    ArenaScreen,
    TypeSurvivorsApp,
    hud_bottom_rail,
    hud_top_rail,
    marker_plate,
)
from tsurv.arena import EnemyKind
from tsurv.metrics import Consistency
from tsurv.stage import CELL_ART, art_origin, crown_origin
from tsurv.words import Tier

_SIZES: Final = ((80, 24), (120, 30))
_FULL_HP: Final = 100.0
_HALF_HP: Final = 50.0
_HP_BAR_CELLS: Final = 10
_WAVE_THREE: Final = 3
_WAVE_SIX: Final = 6
_STREAK_THREE: Final = 3
_SCORE: Final = 1234
_ACC: Final = 0.96
_CONSIST_VALUE: Final = 82.0
_WAVE_BAR_CELLS: Final = 5
"""Bottom-rail bar width, mirrored from the app: one block per cycle wave."""


def _top(*, hp: float = _FULL_HP, mono: bool = True) -> str:
    """Top rail plain text at full health unless told otherwise."""
    return hud_top_rail(
        hp=hp,
        max_hp=_FULL_HP,
        streak=_STREAK_THREE,
        score=_SCORE,
        accuracy=_ACC,
        consist=Consistency(value=_CONSIST_VALUE, rough=False),
        mono=mono,
    ).plain


def test_hud_rails_at_80x24_and_120x30() -> None:
    """All six rail elements read at both sizes; bars fill proportionally."""
    top = _top()
    assert "HP" in top
    assert "100/100" in top
    assert "×3" in top  # noqa: RUF001 - intentional streak glyph, not letter x
    assert "score 1234" in top
    assert "ACC 96%" in top
    assert "CONS 82" in top
    assert top.count("█") == _HP_BAR_CELLS
    assert "░" not in top
    half = _top(hp=_HALF_HP)
    assert "50/100" in half
    assert half.count("█") == _HP_BAR_CELLS // 2
    assert half.count("░") == _HP_BAR_CELLS // 2
    bottom = hud_bottom_rail(wave=_WAVE_THREE).plain
    assert "WAVE 3" in bottom
    assert "3/5" in bottom
    assert "BOSS IN 2" in bottom
    assert "LV 3" in bottom
    assert bottom.count("█") == _WAVE_THREE
    assert bottom.count("█") + bottom.count("░") == _WAVE_BAR_CELLS
    for width, _ in _SIZES:
        assert len(top) < width
        assert len(bottom) < width


def test_hud_top_rail_mono_strips_color() -> None:
    """Color rails carry style spans; mono rails carry shape only."""
    tinted = hud_top_rail(
        hp=_FULL_HP,
        max_hp=_FULL_HP,
        streak=_STREAK_THREE,
        score=_SCORE,
        accuracy=_ACC,
        consist=Consistency(value=_CONSIST_VALUE, rough=False),
        mono=False,
    )
    assert len(tinted.spans) > 0
    assert _top(mono=True) == _top(mono=True)
    mono_text = hud_top_rail(
        hp=_FULL_HP,
        max_hp=_FULL_HP,
        streak=_STREAK_THREE,
        score=_SCORE,
        accuracy=_ACC,
        consist=Consistency(value=_CONSIST_VALUE, rough=False),
        mono=True,
    )
    assert mono_text.spans == []


def test_hud_rough_consistency_never_confident() -> None:
    """Under-10-sample consistency reads ~, never a confident number."""
    rough = hud_top_rail(
        hp=_FULL_HP,
        max_hp=_FULL_HP,
        streak=0,
        score=0,
        accuracy=1.0,
        consist=Consistency(value=None, rough=True),
        mono=True,
    ).plain
    assert "CONS ~" in rough


def test_boss_countdown_ticks() -> None:
    """Wave 3 reads BOSS IN 2; the boss wave names itself; wave 6 restarts."""
    assert "BOSS IN 2" in hud_bottom_rail(wave=_WAVE_THREE).plain
    boss_wave = hud_bottom_rail(wave=BOSS_EVERY).plain
    assert "BOSS WAVE" in boss_wave
    assert "5/5" in boss_wave
    restarted = hud_bottom_rail(wave=_WAVE_SIX).plain
    assert "BOSS IN 4" in restarted
    assert "1/5" in restarted


def test_marker_plate_supersedes_pips() -> None:
    """Plates wear the tier circle (not pips); bosses add the crown."""
    grunt = marker_plate(kind=EnemyKind.GRUNT, tier=Tier.T1, word="cat", mono=True)
    assert grunt.plain == "○ cat"
    assert "●" not in grunt.plain
    boss = marker_plate(
        kind=EnemyKind.BOSS,
        tier=Tier.T3,
        word="overlord",
        mono=True,
    )
    assert boss.plain == "♛ ◑ overlord"
    elite = marker_plate(
        kind=EnemyKind.ELITE,
        tier=Tier.T2,
        word="hex",
        mono=True,
    )
    assert "◯" in elite.plain
    tinted = marker_plate(
        kind=EnemyKind.GRUNT,
        tier=Tier.T1,
        word="cat",
        mono=False,
    )
    assert len(tinted.spans) > 0


def test_crown_origin_centers_above_art() -> None:
    """The crown sits on the sprite center, one row above its top row."""
    assert crown_origin(10, 5, ("#####", "#####")) == (10, 4)
    boss = CELL_ART[EnemyKind.BOSS]
    tx, ty = art_origin(40, 12, boss)
    assert crown_origin(40, 12, boss) == (40, ty - 1)
    assert crown_origin(40, 12, boss)[0] == tx + len(boss[0]) // 2


def test_pilot_rails_render_top_and_bottom() -> None:
    """The arena screen paints the top rail and the wave bottom rail."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            top = screen.query_one("#topbar", Label).content
            plain_top = top.plain if isinstance(top, Text) else str(top)
            assert "HP" in plain_top
            assert "ACC" in plain_top
            bottom = screen.query_one("#botrail", Label).content
            plain_bottom = bottom.plain if isinstance(bottom, Text) else str(bottom)
            assert "BOSS IN" in plain_bottom
            assert "LV" in plain_bottom

    asyncio.run(_scenario())
