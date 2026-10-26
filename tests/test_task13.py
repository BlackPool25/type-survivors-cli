"""Task 13: halo-free sprites, outside-edge spawns, minimal audio."""

from __future__ import annotations

import asyncio
import shutil
import time
import wave
from typing import Final

import pytest
from textual.widgets import Label

from tsurv.app import (
    SPAWN_OUTSIDE_MARGIN,
    ArenaScreen,
    SettingsScreen,
    TypeSurvivorsApp,
    sprite_image,
)
from tsurv.arena import spawn_radius_for_level
from tsurv.audio import (
    AudioConfig,
    Sound,
    default_enabled,
    find_player,
    play_event,
    start_ambient,
)
from tsurv.profile import Profile
from tsurv.stage import canvas_xy, edge_spawn_distance
from tsurv.visuals import ASSETS_DIR

_WIDE_SIZE: Final = (200, 50)
"""Ghostty-wide pilot viewport from the screenshot evidence."""

_SMALL_SIZE: Final = (80, 24)
"""Compact pilot viewport: the floor guard must survive here."""

_SPAWN_TICK_S: Final = 4.0
"""Public tick step that trips the idle spawn gap exactly once."""

_EDGE_CELLS: Final = 2
"""Spawn ring tolerance: clamped chips sit this close to the field border."""

_WAV_BYTES_CAP: Final = 100 * 1024
"""Each synthesized asset stays under 100KB."""

_WAV_CHANNELS: Final = 1
"""All assets are mono: no stereo image to spatialize in a terminal."""

_WAV_WIDTH: Final = 2
"""16-bit samples: 8-bit quantization noise would ride the drone loop."""

_WAV_RATE: Final = 22050
"""Voice-grade rate: matches the synth script, keeps the drone under 100KB."""

_PLAY_DISPATCH_S: Final = 5.0
"""Fire-and-forget budget: dispatch must return far inside one frame batch."""

_WAV_ROSTER: Final = ("ambient.wav", "kill.wav", "boss.wav")
"""Shipped synth assets: drone loop, kill blip, boss roar."""


def _border_gap(x: int, y: int, width: int, height: int) -> int:
    """Closest distance of a canvas cell to any field border."""
    return min(x, width - 1 - x, y, height - 1 - y)


def test_sprite_corners_match_rendered_stage_bg() -> None:
    """H1: baked void corners must equal the stage's computed background.

    Task 12 composited onto assumed Screen #0B0B12, but the theme wins and
    the stage renders neutral #121212 — the navy mismatch is the halo.
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
            stage = screen.query_one("#stage")
            region = stage.region
            bgcolor = screen.get_style_at(region.x, region.y).bgcolor
            assert bgcolor is not None
            triplet = bgcolor.triplet
            rendered = f"#{triplet.red:02X}{triplet.green:02X}{triplet.blue:02X}"
            pic = sprite_image("grunt_0.png")
            assert pic is not None
            shown = pic.convert("RGB")
            corner = shown.getpixel((0, 0))
            assert isinstance(corner, tuple)
            baked = f"#{corner[0]:02X}{corner[1]:02X}{corner[2]:02X}"
            assert baked == rendered

    asyncio.run(_scenario())


@pytest.mark.parametrize("size", [_WIDE_SIZE, _SMALL_SIZE])
def test_spawned_foes_start_outside_edge(
    size: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H2: fresh foes spawn off-screen by the margin, chips clamp to the edge."""

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
            assert screen.query_one("#guard", Label).display is False
            for foe in foes:
                want = edge_spawn_distance(
                    angle=foe.angle,
                    width=width,
                    height=height,
                )
                floor = max(spawn_radius_for_level(1), want)
                assert foe.distance == pytest.approx(floor + SPAWN_OUTSIDE_MARGIN)
                assert foe.distance > want
                x, y = canvas_xy(
                    angle=foe.angle,
                    distance=foe.distance,
                    width=width,
                    height=height,
                )
                assert _border_gap(x, y, width, height) <= _EDGE_CELLS

    monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
    asyncio.run(_scenario())


@pytest.mark.parametrize("size", [_WIDE_SIZE, _SMALL_SIZE])
def test_outside_foe_stays_typable(
    size: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H2: an off-screen foe locks on its first letter (no visibility gate)."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=11)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.tick(_SPAWN_TICK_S)
            foes = screen.arena_state.enemies
            assert len(foes) == 1
            await pilot.press(str(foes[0].word.text)[0])
            await pilot.pause()
            assert screen.arena_state.current == foes[0].id

    monkeypatch.setenv("TSURV_TRUEPIXEL", "0")
    asyncio.run(_scenario())


def test_wav_assets_are_tiny_valid_mono() -> None:
    """H3: the synth script's assets exist, stay small, and parse as WAV."""
    for name in _WAV_ROSTER:
        path = ASSETS_DIR / "audio" / name
        assert path.is_file()
        assert path.stat().st_size < _WAV_BYTES_CAP
        with wave.open(str(path)) as handle:
            assert handle.getnchannels() == _WAV_CHANNELS
            assert handle.getsampwidth() == _WAV_WIDTH
            assert handle.getframerate() == _WAV_RATE


def test_missing_player_degrades_silently() -> None:
    """H3: no platform player means no-op audio, never an exception."""
    config = AudioConfig(enabled=True, player=None)
    play_event(config, Sound.KILL)
    play_event(config, Sound.BOSS)
    assert start_ambient(player=None, enabled=lambda: True) is None
    disabled = AudioConfig(enabled=False, player="/usr/bin/aplay")
    play_event(disabled, Sound.KILL)


def test_player_probe_and_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H3: default is ON with a player around, OFF without one."""
    monkeypatch.delenv("TSURV_AUDIO", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert find_player() is None
    assert default_enabled() is False
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/aplay")
    assert find_player() == "/usr/bin/aplay"
    assert default_enabled() is True


def test_env_pin_overrides_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """H3: TSURV_AUDIO pins the default either way (hermetic tests)."""
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/aplay")
    monkeypatch.setenv("TSURV_AUDIO", "0")
    assert default_enabled() is False
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setenv("TSURV_AUDIO", "1")
    assert default_enabled() is True


def test_play_event_never_blocks() -> None:
    """H3: fire-and-forget dispatch returns at once (game loop never waits)."""
    if shutil.which("true") is None:
        pytest.skip("no POSIX true for the no-op player stand-in")
    config = AudioConfig(enabled=True, player="true")
    start = time.monotonic()
    play_event(config, Sound.KILL)
    assert time.monotonic() - start < _PLAY_DISPATCH_S


def test_ambient_start_stop_roundtrip() -> None:
    """H3: the drone loop starts only when enabled and hands back a stop."""
    assert start_ambient(player="true", enabled=lambda: False) is None
    assert start_ambient(player=None, enabled=lambda: True) is None
    if shutil.which("true") is None:
        pytest.skip("no POSIX true for the no-op player stand-in")
    stop = start_ambient(player="true", enabled=lambda: True)
    assert stop is not None
    stop()


def test_settings_toggle_flips_sound() -> None:
    """H3: the Settings screen's S key flips the stored sound toggle."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=("cat",),
            spawn_enabled=False,
            seed=11,
            profile=Profile(),
        )
        async with app.run_test(size=_SMALL_SIZE) as pilot:
            await pilot.pause()
            app.open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            assert app.profile.settings.sound_on is True
            await pilot.press("s")
            await pilot.pause()
            assert app.profile.settings.sound_on is False
            await pilot.press("s")
            await pilot.pause()
            assert app.profile.settings.sound_on is True

    asyncio.run(_scenario())
