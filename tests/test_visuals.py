"""Visual overhaul: sprite frames, juice overlays, hub chrome, pilot wiring."""

from __future__ import annotations

import asyncio
import math
import random
from dataclasses import replace
from itertools import pairwise
from typing import TYPE_CHECKING, Final

from par_textual_image import TerminalImage
from rich.text import Text
from textual import events
from textual.containers import Vertical
from textual.widgets import Label

from tsurv.app import BOSS_EVERY, ArenaScreen, HubScreen, TypeSurvivorsApp
from tsurv.arena import EnemyKind
from tsurv.juice import PARTICLE_BURST, JuiceState, burst, step_juice, trigger_bar_break
from tsurv.profile import Profile
from tsurv.stage import ArenaCanvas
from tsurv.visuals import (
    AMBIENT_SEEDS,
    APPROACH_MAX,
    HUB_BANNER,
    HUB_ENTRIES,
    ambient_line,
    approach_indent,
    boss_portal_mark,
    core_sprite_file,
    foe_hit_showing,
    foe_mark,
    foe_sprite_file,
    fx_line,
    hub_banner_text,
    hub_greeting,
    hub_list_text,
    juice_overlay,
    particle_layer,
    portal_mark,
    shop_row_text,
    tier_pips,
)
from tsurv.words import Corruption, Tier

if TYPE_CHECKING:
    import pytest

_SEED: Final = 7
_NOW: Final = 100.0
_BOSS_GAP_TICK: Final = 3.5
_BANNER_ROWS: Final = 3
_CORE_PLUS_TWO: Final = 3
_CORE_PLUS_ONE: Final = 2
_NARROW_WIDTH: Final = 80
_FIELD_ROWS_MIN: Final = 6
"""Foe field keeps at least two rows visible at the smallest viewport."""
_GUARD_CELLS: Final = 2
"""True-pixel guard: widget content must clear 2 cells on every protocol."""
_CORE_OFF_TOLERANCE: Final = 8
"""Core sprite center may trail the row center by half a word chip."""
_CORE_CELLS_W: Final = 12
"""Core widget width: the Sanctuary Core renders large, never a label."""
_CORE_CELLS_H: Final = 4
"""Core widget height: the Sanctuary Core renders large, never a label."""
_CORE_CENTER_TOL: Final = 2
"""Core sprite center sits on the viewport centre within two cells."""
_RING_SPAWNS: Final = 8
"""Ring-spread pilot fills every foe slot."""
_RING_MIN_GAP: Final = 0.25
"""Golden-angle spawn ring keeps neighbours well apart (measured 0.54)."""


def test_foe_frames_alternate_idle_and_bob() -> None:
    """Even ticks show the idle frame, odd ticks the bob frame."""
    assert foe_sprite_file(EnemyKind.GRUNT, hit=False, tick=0) == "grunt_0.png"
    assert foe_sprite_file(EnemyKind.GRUNT, hit=False, tick=1) == "grunt_1.png"
    assert foe_sprite_file(EnemyKind.BOSS, hit=False, tick=5) == "boss_1.png"
    assert foe_sprite_file(EnemyKind.BOSS, hit=False, tick=6) == "boss_0.png"


def test_foe_hit_frame_wins_over_bob() -> None:
    """Damage shows the hit frame no matter the bob phase."""
    assert foe_sprite_file(EnemyKind.MITE, hit=True, tick=0) == "mite_hit.png"
    assert foe_sprite_file(EnemyKind.MITE, hit=True, tick=1) == "mite_hit.png"
    juice = trigger_bar_break(JuiceState(), _NOW, random.Random(_SEED))  # noqa: S311
    assert foe_hit_showing(juice, _NOW)
    assert not foe_hit_showing(JuiceState(), _NOW)


def test_elite_reuses_hex_art_without_new_assets() -> None:
    """No elite PNG ships, so elites wear hex frames (glyph stays distinct)."""
    assert foe_sprite_file(EnemyKind.ELITE, hit=False, tick=0) == "hex_0.png"
    assert foe_sprite_file(EnemyKind.ELITE, hit=True, tick=0) == "hex_hit.png"


def test_core_pulse_and_critical_frame() -> None:
    """The core breathes through its frames and flashes hit when critical."""
    assert core_sprite_file(hit=False, tick=0) == "core_0.png"
    assert core_sprite_file(hit=False, tick=3) == "core_1.png"
    assert core_sprite_file(hit=True, tick=0) == "core_hit.png"


def test_approach_indent_glides_with_distance() -> None:
    """Far foes start right and glide core-ward; compact halves the travel."""
    far = approach_indent(9.0, compact=False)
    near = approach_indent(1.0, compact=False)
    assert len(far) > len(near)
    assert approach_indent(9.0, compact=True) == " " * (9 // 2)
    assert approach_indent(999.0, compact=False) == " " * APPROACH_MAX
    assert approach_indent(0.5, compact=False) == ""


def test_quiet_juice_renders_no_overlay() -> None:
    """No windows open, no particles: the fx ribbon stays empty."""
    overlay = juice_overlay(JuiceState(), _NOW)
    assert overlay == juice_overlay(JuiceState(), _NOW)
    assert overlay.beam == ""
    assert overlay.burst == ""
    assert not overlay.ring
    assert not overlay.flash
    assert overlay.shake == 0
    assert not overlay.slow
    assert fx_line(overlay) == ""


def test_bar_break_renders_beam_burst_and_ring() -> None:
    """A bar break shows the beam, the burst, the ring, and the shake."""
    juice = trigger_bar_break(JuiceState(), _NOW, random.Random(_SEED))  # noqa: S311
    overlay = juice_overlay(juice, _NOW)
    assert "DIRECT HIT" in overlay.beam
    assert overlay.burst == "*" * PARTICLE_BURST
    assert overlay.ring
    assert overlay.flash
    assert overlay.shake > 0
    ribbon = fx_line(overlay)
    assert "DIRECT HIT" in ribbon
    assert "SHOCKWAVE" in ribbon
    assert juice_overlay(juice, _NOW + 1.0).beam == ""


def test_ambient_line_is_deterministic_and_sized() -> None:
    """Void specks tile exactly to width and drift with the tick."""
    assert len(ambient_line(_NARROW_WIDTH, 0)) == _NARROW_WIDTH
    assert ambient_line(_NARROW_WIDTH, 0) == ambient_line(_NARROW_WIDTH, 0)
    assert ambient_line(_NARROW_WIDTH, 0) != ambient_line(_NARROW_WIDTH, 60)
    assert ambient_line(10, 0).count("·") == AMBIENT_SEEDS


def test_banner_prerendered_once_and_reused_by_value() -> None:
    """Three pre-rendered rows; every call copies by value, never by reference."""
    assert len(HUB_BANNER) == _BANNER_ROWS
    assert all(row.strip(" █") == "" and row.strip() for row in HUB_BANNER)
    first = hub_banner_text(mono=True)
    second = hub_banner_text(mono=True)
    assert first.plain == second.plain
    assert first is not second
    assert "\n".join(HUB_BANNER) == first.plain
    assert len(first.spans) == 0
    assert len(hub_banner_text(mono=False).spans) == len(HUB_BANNER)


def test_hub_list_highlights_selected_row() -> None:
    """The selected row carries the marker; mono keeps the marker, drops color."""
    text = hub_list_text(HUB_ENTRIES, 0, mono=True)
    assert "▶ S start" in text.plain
    assert len(text.spans) == 0
    moved = hub_list_text(HUB_ENTRIES, 1, mono=True)
    assert "▶ P practice" in moved.plain
    assert "▶ S start" not in moved.plain
    styled = hub_list_text(HUB_ENTRIES, 0, mono=False)
    assert len(styled.spans) > 0


def test_hub_greeting_separates_fresh_and_returning() -> None:
    """Empty profiles get marching orders; veterans get their tallies."""
    assert "fresh soul" in hub_greeting(gold=0, runs=0)
    assert "welcome back" in hub_greeting(gold=10, runs=0)
    assert "3 runs" in hub_greeting(gold=0, runs=3)


def test_shop_row_shows_price_or_owned_beside_blurb() -> None:
    """Rows stay readable: price or OWNED always beside the perk blurb."""
    row = shop_row_text("Blood Vial Cache", 100, "begin holding a heal", owned=False)
    assert row == "Blood Vial Cache — 100g · begin holding a heal"
    assert "OWNED" in shop_row_text("Blood Vial Cache", 100, "heal", owned=True)


def test_pilot_arena_mounts_sprite_widgets_for_foes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each spawned foe (plus the core) gets a loaded TerminalImage widget."""

    async def _scenario() -> None:
        monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
        app = TypeSurvivorsApp(initial_words=("cat", "dog"), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            shown = [w for w in screen.query(TerminalImage) if w.display]
            assert len(shown) == _CORE_PLUS_TWO
            assert all(widget.image is not None for widget in shown)

    asyncio.run(_scenario())


def test_pilot_kill_flash_shows_beam_and_burst() -> None:
    """Burning a boss bar paints the beam, burst, and ring onto the fx ribbon."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=_SEED)
        async with app.run_test() as pilot:
            del pilot
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.set_restored(replace(screen.arena_state, wave=BOSS_EVERY))
            screen.tick(_BOSS_GAP_TICK)
            foe = screen.arena_state.enemies[0]
            assert foe.kind is EnemyKind.BOSS
            for char in str(foe.word.text):
                await screen.on_key(events.Key(char, char))
            assert screen.knockback_active
            content = screen.query_one("#fx", Label).content
            plain = content.plain if isinstance(content, Text) else str(content)
            assert "DIRECT HIT" in plain
            assert "*" in plain
            assert "SHOCKWAVE" in plain

    asyncio.run(_scenario())


def test_pilot_hub_shows_banner_list_and_greeting() -> None:
    """The hub paints its banner, six-row list, and the fresh-soul greeting."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile=Profile(),
            start_at_hub=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HubScreen)
            banner = screen.query_one("#hub-banner", Label).content
            assert isinstance(banner, Text)
            assert banner.plain == "\n".join(HUB_BANNER)
            greeting = screen.query_one("#hub-greeting", Label).content
            assert "fresh soul" in str(greeting)
            listed = screen.query_one("#hub-list", Label).content
            assert isinstance(listed, Text)
            assert "▶ S start" in listed.plain
            assert screen.selected == 0
            await pilot.press("j")
            assert screen.selected == 1
            await pilot.press("k")
            assert screen.selected == 0
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ArenaScreen)

    asyncio.run(_scenario())


def test_pilot_hub_greets_returning_player() -> None:
    """Banked gold flips the greeting to the welcome-back line."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile=Profile(gold=10),
            start_at_hub=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HubScreen)
            greeting = screen.query_one("#hub-greeting", Label).content
            assert "welcome back" in str(greeting)

    asyncio.run(_scenario())


def test_pilot_compact_layout_keeps_sprites_and_words_legible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At 80 cols the compact layout still shows words beside their sprites."""

    async def _scenario() -> None:
        monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert "cat" in screen.foes_text
            shown = [w for w in screen.query(TerminalImage) if w.display]
            assert len(shown) == _CORE_PLUS_ONE
            assert all(widget.image is not None for widget in shown)

    asyncio.run(_scenario())


def test_pilot_slow_mo_paints_tint_marker() -> None:
    """The x8 streak arms slow-mo and the topbar carries the tint marker."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=False, seed=_SEED)
        async with app.run_test() as pilot:
            del pilot
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            words = ("cat", "dog", "bat", "rat", "hat", "mat", "sat", "fat")
            for word in words:
                screen.spawn_test_enemy(word, distance=5.0)
            for word in words:
                for char in word:
                    await screen.on_key(events.Key(char, char))
            assert screen.slow_mo_active
            topbar = screen.query_one("#topbar", Label).content
            assert "SLO-MO" in str(topbar)

    asyncio.run(_scenario())


def test_pilot_hub_centered_bordered_panels() -> None:
    """Banner text centers full-width; menu/header sit in bordered panels."""

    async def _scenario(size: tuple[int, int]) -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile=Profile(),
            start_at_hub=True,
        )
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HubScreen)
            width, height = size
            banner = screen.query_one("#hub-banner", Label)
            assert banner.region.width == width
            assert banner.styles.text_align == "center"
            panel = screen.query_one("#hub-panel", Vertical)
            assert panel.styles.border_top[0] == "solid"
            assert screen.query_one("#hub-list", Label).parent is panel
            header = screen.query_one("#hub-header", Vertical)
            assert header.styles.border_top[0] == "solid"
            assert screen.query_one("#hub-greeting", Label).parent is header
            assert screen.query_one("#gold", Label).parent is header
            hint = screen.query_one("#hub-hint", Label)
            assert hint.region.bottom == height
            assert hint.region.width == width

    asyncio.run(_scenario((80, 24)))
    asyncio.run(_scenario((120, 30)))


def test_pilot_stage_stacks_under_topbar() -> None:
    """Topbar/stage/fx/input stack edge-to-edge; the stage fills the rest."""

    async def _scenario(size: tuple[int, int]) -> None:
        app = TypeSurvivorsApp(initial_words=("cat", "dog"), spawn_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            width, height = size
            topbar = screen.query_one("#topbar", Label)
            arena = screen.query_one("#arena", Vertical)
            stage = screen.query_one("#stage", Vertical)
            typing = screen.query_one("#typing", Label)
            assert topbar.region.width == width
            assert arena.region.y == topbar.region.y + topbar.region.height
            assert arena.region.height > stage.region.height
            assert stage.region.height >= _FIELD_ROWS_MIN
            assert typing.region.bottom == height
            assert typing.region.width == width

    asyncio.run(_scenario((80, 24)))
    asyncio.run(_scenario((120, 30)))


def test_pilot_kitty_core_centers_on_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kitty core widget anchors on the stage midpoint, both sizes."""

    async def _scenario(size: tuple[int, int]) -> None:
        monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            stage = screen.query_one("#stage", Vertical)
            core = screen.query_one("#core-sprite", TerminalImage)
            core_cx = core.region.x + core.region.width // 2
            core_cy = core.region.y + core.region.height // 2
            stage_cx = stage.region.x + stage.region.width // 2
            stage_cy = stage.region.y + stage.region.height // 2
            assert abs(core_cx - stage_cx) <= _CORE_CENTER_TOL
            assert abs(core_cy - stage_cy) <= _CORE_CENTER_TOL

    asyncio.run(_scenario((80, 24)))
    asyncio.run(_scenario((120, 30)))


def test_pilot_cells_core_centers_on_canvas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cells core art sits on the canvas midpoint; chips name the foes."""

    async def _scenario(size: tuple[int, int]) -> None:
        monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.pixdiag_text == "pixels: cells (TSURV_TRUEPIXEL=0)"
            canvas = screen.query_one("#field", ArenaCanvas)
            rows = canvas.rendered.plain.split("\n")
            assert "cat" in canvas.rendered.plain
            middle = rows[len(rows) // 2 - 2 : len(rows) // 2 + 3]
            assert any("█" in row or "▀" in row or "▄" in row for row in middle)

    asyncio.run(_scenario((80, 24)))
    asyncio.run(_scenario((120, 30)))


def test_pilot_kitty_sprite_bound_to_foe_chip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each kitty slot pairs its own sprite with its chip; kills free slots."""

    async def _scenario() -> None:
        monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
        app = TypeSurvivorsApp(initial_words=("cat", "dog"), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            foes = screen.arena_state.enemies
            assert [str(foe.word.text) for foe in foes] == ["cat", "dog"]
            for index, foe in enumerate(foes):
                sprite = screen.query_one(f"#foe-sprite-{index}", TerminalImage)
                assert sprite.display
                assert sprite.image is not None
                content = screen.query_one(f"#foe-word-{index}", Label).content
                plain = content.plain if isinstance(content, Text) else str(content)
                assert str(foe.word.text) in plain
            assert screen.query_one("#foe-sprite-2", TerminalImage).display is False
            for char in str(foes[0].word.text):
                await screen.on_key(events.Key(char, char))
            await pilot.pause()
            assert len(screen.arena_state.enemies) == 1
            survivor = str(screen.arena_state.enemies[0].word.text)
            content = screen.query_one("#foe-word-0", Label).content
            plain = content.plain if isinstance(content, Text) else str(content)
            assert survivor in plain
            freed = screen.query_one("#foe-sprite-1", TerminalImage)
            assert freed.display is False
            assert freed.image is None

    asyncio.run(_scenario())


def test_pilot_cells_field_tracks_kills_without_sprites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cells canvas names every foe chip and drops victims on kill."""

    async def _scenario() -> None:
        monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
        app = TypeSurvivorsApp(initial_words=("cat", "dog"), spawn_enabled=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert len(screen.query(TerminalImage)) == 0
            canvas = screen.query_one("#field", ArenaCanvas)
            assert "cat" in canvas.rendered.plain
            assert "dog" in canvas.rendered.plain
            for char in "cat":
                await screen.on_key(events.Key(char, char))
            await pilot.pause()
            assert len(screen.arena_state.enemies) == 1
            assert "dog" in canvas.rendered.plain

    asyncio.run(_scenario())


def test_pilot_guard_names_the_fix() -> None:
    """Narrow windows name the 80-column fix; the message fits the guard."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False)
        async with app.run_test(size=(60, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            guard = screen.query_one("#guard", Label)
            assert guard.display is True
            content = guard.content
            plain = content.plain if isinstance(content, Text) else str(content)
            assert plain.strip() != ""
            assert "80" in plain
            assert len(plain.strip()) < _NARROW_WIDTH

    asyncio.run(_scenario())


def test_foe_mark_covers_every_corruption_and_kind() -> None:
    """Plate marks never blank: corruption wins, kind is the fallback."""
    for corruption in Corruption:
        for kind in EnemyKind:
            assert foe_mark(kind, corruption) != ""
    for tier in Tier:
        assert tier_pips(tier) >= 1


def test_pilot_core_centered_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Sanctuary Core renders large at the stage centre, never a label."""

    async def _scenario(size: tuple[int, int]) -> None:
        monkeypatch.setenv("TSURV_TRUEPIXEL", "1")
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False, seed=_SEED)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            stage = screen.query_one("#stage", Vertical)
            core = screen.query_one("#core-sprite", TerminalImage)
            assert core.display
            assert core.image is not None
            assert core.region.width >= _CORE_CELLS_W
            assert core.region.height >= _CORE_CELLS_H
            center = core.region.x + core.region.width // 2
            stage_cx = stage.region.x + stage.region.width // 2
            assert abs(center - stage_cx) <= _CORE_CENTER_TOL

    asyncio.run(_scenario((80, 24)))
    asyncio.run(_scenario((120, 30)))


def test_pilot_foe_angles_surround_core() -> None:
    """Spawn ring angles spread around the core instead of stacking."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=False, seed=_SEED)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            for word in ("aa", "bb", "cc", "dd", "ee", "ff", "gg", "hh"):
                screen.spawn_test_enemy(word, distance=5.0)
            angles = screen.foe_angles
            assert len(angles) == _RING_SPAWNS
            assert all(0.0 <= angle < 2 * math.pi for angle in angles)
            ordered = sorted(angles)
            gaps = [later - early for early, later in pairwise(ordered)]
            gaps.append(ordered[0] + 2 * math.pi - ordered[-1])
            assert min(gaps) > _RING_MIN_GAP

    asyncio.run(_scenario())


def test_pilot_plate_shows_circle_word_and_crown() -> None:
    """Plates read `[circle] word`; the boss wears its crown and circle."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            initial_boss="overlord",
            spawn_enabled=False,
            seed=_SEED,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert "○ cat" in screen.foes_text
            assert "♛ ◑ overlord" in screen.foes_text

    asyncio.run(_scenario())


def test_pilot_portal_precedes_plate() -> None:
    """The spawn portal marks the foe before it settles into the ring."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=False, seed=_SEED)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.spawn_test_enemy("cat", distance=5.0)
            assert portal_mark() in screen.foes_text
            await asyncio.sleep(0.35)
            screen.tick(0.0)
            assert portal_mark() not in screen.foes_text
            assert "cat" in screen.foes_text

    asyncio.run(_scenario())


def test_pilot_boss_banner_and_shake() -> None:
    """The boss entrance names itself full-width and rattles the frame."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=_SEED)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.set_restored(replace(screen.arena_state, wave=BOSS_EVERY))
            screen.tick(_BOSS_GAP_TICK)
            assert screen.arena_state.boss_wave
            assert "OVERLORD APPROACHES" in screen.boss_banner_text
            banner = screen.query_one("#bossbanner", Label)
            assert banner.display
            content = banner.content
            plain = content.plain if isinstance(content, Text) else str(content)
            assert "OVERLORD APPROACHES" in plain
            assert screen.shake_active
            boss = next(
                foe for foe in screen.arena_state.enemies if foe.kind is EnemyKind.BOSS
            )
            plate = f"♛ ◑ {boss.word.text}"
            assert plate in screen.foes_text
            assert boss_portal_mark() in screen.foes_text
            assert boss_portal_mark() != portal_mark()

    asyncio.run(_scenario())


def test_pilot_wave_clear_steps_core_forward() -> None:
    """A cleared wave steps the core forward and pans the background."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=("cat",), spawn_enabled=False, seed=_SEED)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            assert not screen.advance_active
            screen.set_restored(
                replace(screen.arena_state, wave=screen.arena_state.wave + 1),
            )
            screen.tick(0.0)
            assert screen.advance_active
            ribbon = screen.query_one("#fx", Label).content
            plain = ribbon.plain if isinstance(ribbon, Text) else str(ribbon)
            assert "ADVANCES" in plain

    asyncio.run(_scenario())


_EAST_X: Final = 2.0
_WEST_X: Final = -2.0
_LAYER_W: Final = 40
_LAYER_H: Final = 20
_EAST_CELL: Final = (_LAYER_W // 2 + 4, _LAYER_H // 2)
_WEST_CELL: Final = (_LAYER_W // 2 - 4, _LAYER_H // 2)


def test_bursts_at_distinct_sites_paint_distinct_cells() -> None:
    """Kills at different sites render at visibly different screen positions."""
    east_burst = burst(_EAST_X, 0.0)
    west_burst = burst(_WEST_X, 0.0)
    east = particle_layer(east_burst, width=_LAYER_W, height=_LAYER_H, mono=True)
    west = particle_layer(west_burst, width=_LAYER_W, height=_LAYER_H, mono=True)
    assert {(mote.chip_x, mote.chip_y) for mote in east} == {_EAST_CELL}
    assert {(mote.chip_x, mote.chip_y) for mote in west} == {_WEST_CELL}
    tinted = particle_layer(east_burst, width=_LAYER_W, height=_LAYER_H, mono=False)
    assert all(mote.chip.plain == "*" for mote in tinted)
    assert all(len(mote.chip.spans) == 1 for mote in tinted)
    assert tinted[0].chip.spans[0].style == "#FFD23F"
    assert all(mote.chip.spans == [] for mote in east)
    aged = step_juice(JuiceState(particles=east_burst), 0.2).particles
    faded = particle_layer(aged, width=_LAYER_W, height=_LAYER_H, mono=True)
    assert all(mote.chip.plain == "·" for mote in faded)
