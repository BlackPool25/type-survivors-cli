"""Visual overhaul: sprite frames, juice overlays, hub chrome, pilot wiring."""

from __future__ import annotations

import asyncio
import random
from dataclasses import replace
from typing import Final

from par_textual_image import TerminalImage
from rich.text import Text
from textual import events
from textual.widgets import Label

from tsurv.app import BOSS_EVERY, ArenaScreen, HubScreen, TypeSurvivorsApp
from tsurv.arena import EnemyKind
from tsurv.juice import PARTICLE_BURST, JuiceState, trigger_bar_break
from tsurv.profile import Profile
from tsurv.visuals import (
    AMBIENT_SEEDS,
    APPROACH_MAX,
    HUB_BANNER,
    HUB_ENTRIES,
    ambient_line,
    approach_indent,
    core_sprite_file,
    foe_hit_showing,
    foe_sprite_file,
    fx_line,
    hub_banner_text,
    hub_greeting,
    hub_list_text,
    juice_overlay,
    shop_row_text,
)

_SEED: Final = 7
_NOW: Final = 100.0
_BOSS_GAP_TICK: Final = 3.5
_BANNER_ROWS: Final = 3
_CORE_PLUS_TWO: Final = 3
_CORE_PLUS_ONE: Final = 2
_NARROW_WIDTH: Final = 80


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


def test_pilot_arena_mounts_sprite_widgets_for_foes() -> None:
    """Each spawned foe (plus the core) gets a loaded TerminalImage widget."""

    async def _scenario() -> None:
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


def test_pilot_compact_layout_keeps_sprites_and_words_legible() -> None:
    """At 80 cols the compact layout still shows words beside their sprites."""

    async def _scenario() -> None:
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
