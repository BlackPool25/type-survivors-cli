"""Polyphonic audio engine: dynamic music tracks, tactile SFX, and platform fallback."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import pygame

from tsurv.visuals import ASSETS_DIR

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

AUDIO_DIR: Final = ASSETS_DIR / "audio"
MUSIC_DIR: Final = AUDIO_DIR / "music"
SFX_DIR: Final = AUDIO_DIR / "sfx"

_PLAYERS: Final = ("afplay", "aplay", "paplay", "pw-play")
"""Platform players probed in order: macOS, ALSA, PulseAudio, PipeWire."""

_PIN_ENV: Final = "TSURV_AUDIO"
"""TSURV_AUDIO=1 forces audio on, =0 forces it off (hermetic tests)."""

_SAMPLE_RATE: Final = 44100
_AUDIO_CHANNELS: Final = 2
_BUFFER_SIZE: Final = 512
_CLICK_VARIANTS: Final = 5
_MUSIC_DEFAULT_VOL: Final = 0.75
_MUSIC_DUCK_VOL: Final = 0.35


@dataclass(slots=True)
class _MixerState:
    """Internal mutable audio state encapsulated without global statements."""

    initialized: bool = False
    click_index: int = 0
    sound_cache: dict[str, pygame.mixer.Sound] = field(default_factory=dict)


_STATE: Final = _MixerState()


class Sound(StrEnum):
    """Playable game sounds; every member maps to a shipped audio asset."""

    AMBIENT = "ambient"
    KILL = "kill"
    BOSS = "boss"
    CLICK = "click"
    WORD_POP = "word_pop"
    TYPO_JAM = "typo_jam"
    BACKSPACE = "backspace"
    BOSS_BAR_BREAK = "boss_bar_break"
    BLOOD_SPLATTER = "blood_splatter"
    WAVE_CLEAR = "wave_clear"
    NOVA = "nova"


class MusicTrack(StrEnum):
    """Loopable game soundtrack themes across game stages."""

    MENU = "menu"
    TIER_1 = "level_tier1"
    TIER_2 = "level_tier2"
    TIER_3 = "level_tier3"
    BOSS = "boss"
    PRACTICE = "practice"


def sound_file(sound: Sound) -> Path:
    """Resolve a sound to its audio asset (exhaustive: no silent unknowns)."""
    if sound is Sound.CLICK:
        _STATE.click_index = (_STATE.click_index + 1) % _CLICK_VARIANTS + 1
        path = SFX_DIR / f"click_{_STATE.click_index}.wav"
        return path if path.is_file() else AUDIO_DIR / "kill.wav"

    sfx_paths: dict[Sound, Path] = {
        Sound.AMBIENT: AUDIO_DIR / "ambient.wav",
        Sound.KILL: AUDIO_DIR / "kill.wav",
        Sound.BOSS: AUDIO_DIR / "boss.wav",
        Sound.WORD_POP: SFX_DIR / "word_pop.wav",
        Sound.TYPO_JAM: SFX_DIR / "typo_jam.wav",
        Sound.BACKSPACE: SFX_DIR / "backspace_reset.wav",
        Sound.BOSS_BAR_BREAK: SFX_DIR / "boss_bar_break.wav",
        Sound.BLOOD_SPLATTER: SFX_DIR / "blood_splatter.wav",
        Sound.WAVE_CLEAR: SFX_DIR / "wave_clear.wav",
        Sound.NOVA: SFX_DIR / "nova.wav",
    }
    candidate = sfx_paths.get(sound)
    if candidate is not None and candidate.is_file():
        return candidate
    return AUDIO_DIR / ("boss.wav" if sound is Sound.BOSS_BAR_BREAK else "kill.wav")


def music_file(track: MusicTrack) -> Path | None:
    """Resolve a music track to its OGG/WAV audio asset."""
    ogg = MUSIC_DIR / f"{track.value}.ogg"
    if ogg.is_file():
        return ogg
    wav = MUSIC_DIR / f"{track.value}.wav"
    if wav.is_file():
        return wav
    return None


@dataclass(frozen=True, slots=True)
class AudioConfig:
    """Resolved audio state: profile toggle AND a probed platform player."""

    enabled: bool
    player: str | None


def _init_pygame() -> bool:
    """Initialize pygame mixer once safely; returns True on success."""
    if _STATE.initialized:
        return True
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(
                frequency=_SAMPLE_RATE,
                size=-16,
                channels=_AUDIO_CHANNELS,
                buffer=_BUFFER_SIZE,
            )
        _STATE.initialized = True
    except (pygame.error, OSError):
        return False
    else:
        return True


def find_player() -> str | None:
    """Return the first usable platform player, else None (silent game)."""
    for name in _PLAYERS:
        path = shutil.which(name)
        if path is not None:
            return path
    return None


def default_enabled() -> bool:
    """Audio defaults ON when a player exists; the env pin overrides either way."""
    pin = os.environ.get(_PIN_ENV)
    if pin == "1":
        return True
    if pin == "0":
        return False
    return find_player() is not None


def _run(player: str, path: Path) -> None:
    """Play one file via subprocess fallback, swallowing failures."""
    with contextlib.suppress(OSError):
        _ = subprocess.run(  # noqa: S603 - probed platform binary
            [player, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def play_event(config: AudioConfig, sound: Sound) -> None:
    """Play an audio sound event with polyphony and zero frame-lock."""
    if not config.enabled or config.player is None:
        return
    path = sound_file(sound)
    if not path.is_file():
        return
    # Fast path: pygame mixer
    if _init_pygame():
        try:
            str_path = str(path)
            if str_path not in _STATE.sound_cache:
                _STATE.sound_cache[str_path] = pygame.mixer.Sound(str_path)
            snd = _STATE.sound_cache[str_path]
            # Duck music on heavy impacts
            if sound in (Sound.BOSS_BAR_BREAK, Sound.NOVA):
                duck_music(0.3)
            _ = snd.play()
        except (pygame.error, OSError):
            pass
        else:
            return

    # Subprocess fallback
    thread = threading.Thread(
        target=_run,
        args=(config.player, path),
        daemon=True,
    )
    thread.start()


def play_music_track(track: MusicTrack, *, loop: bool = True) -> None:
    """Stream a background music track with looping and volume control."""
    path = music_file(track)
    if path is None or not _init_pygame():
        return
    with contextlib.suppress(pygame.error, OSError):
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(_MUSIC_DEFAULT_VOL)
        pygame.mixer.music.play(-1 if loop else 0)


def stop_music_track() -> None:
    """Stop the currently playing background music track."""
    if _STATE.initialized:
        with contextlib.suppress(pygame.error, OSError):
            pygame.mixer.music.stop()


def duck_music(duration_s: float = 0.25) -> None:
    """Briefly dip the music volume for heavy impacts to cut through the mix."""
    if not _STATE.initialized:
        return
    with contextlib.suppress(pygame.error, OSError):
        pygame.mixer.music.set_volume(_MUSIC_DUCK_VOL)

        def _restore() -> None:
            time.sleep(duration_s)
            with contextlib.suppress(pygame.error, OSError):
                pygame.mixer.music.set_volume(_MUSIC_DEFAULT_VOL)

        threading.Thread(target=_restore, daemon=True).start()


def start_ambient(
    player: str | None,
    enabled: Callable[[], bool],
) -> Callable[[], None] | None:
    """Loop the drone on a daemon thread; returns a stop, or None when silent."""
    if player is None or not enabled():
        return None
    stop = threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            if not enabled():
                break
            with contextlib.suppress(OSError):
                _ = subprocess.run(  # noqa: S603 - probed platform binary
                    [player, str(AUDIO_DIR / "ambient.wav")],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            if stop.wait(timeout=0.2):
                break

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return stop.set
