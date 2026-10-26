"""Polyphonic audio engine: dynamic music tracks, tactile SFX, and platform fallback."""

from __future__ import annotations

import contextlib
import os
import random
import shutil
import subprocess
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

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

_pygame_initialized: bool = False
_sound_cache: dict[str, object] = {}
_click_index: int = 0


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
    match sound:
        case Sound.AMBIENT:
            return AUDIO_DIR / "ambient.wav"
        case Sound.KILL:
            return AUDIO_DIR / "kill.wav"
        case Sound.BOSS:
            return AUDIO_DIR / "boss.wav"
        case Sound.CLICK:
            global _click_index
            _click_index = (_click_index + 1) % 5 + 1
            path = SFX_DIR / f"click_{_click_index}.wav"
            return path if path.is_file() else AUDIO_DIR / "kill.wav"
        case Sound.WORD_POP:
            path = SFX_DIR / "word_pop.wav"
            return path if path.is_file() else AUDIO_DIR / "kill.wav"
        case Sound.TYPO_JAM:
            path = SFX_DIR / "typo_jam.wav"
            return path if path.is_file() else AUDIO_DIR / "kill.wav"
        case Sound.BACKSPACE:
            path = SFX_DIR / "backspace_reset.wav"
            return path if path.is_file() else AUDIO_DIR / "kill.wav"
        case Sound.BOSS_BAR_BREAK:
            path = SFX_DIR / "boss_bar_break.wav"
            return path if path.is_file() else AUDIO_DIR / "boss.wav"
        case Sound.BLOOD_SPLATTER:
            path = SFX_DIR / "blood_splatter.wav"
            return path if path.is_file() else AUDIO_DIR / "kill.wav"
        case Sound.WAVE_CLEAR:
            path = SFX_DIR / "wave_clear.wav"
            return path if path.is_file() else AUDIO_DIR / "kill.wav"
        case Sound.NOVA:
            path = SFX_DIR / "nova.wav"
            return path if path.is_file() else AUDIO_DIR / "boss.wav"


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
    global _pygame_initialized
    if _pygame_initialized:
        return True
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        _pygame_initialized = True
        return True
    except Exception:
        return False


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
        _ = subprocess.run(
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
            import pygame
            str_path = str(path)
            if str_path not in _sound_cache:
                _sound_cache[str_path] = pygame.mixer.Sound(str_path)
            snd = _sound_cache[str_path]
            # Duck music on heavy impacts
            if sound in (Sound.BOSS_BAR_BREAK, Sound.NOVA):
                duck_music(0.3)
            if isinstance(snd, pygame.mixer.Sound):
                _ = snd.play()
            return
        except Exception:
            pass

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
    try:
        import pygame
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(0.75)
        pygame.mixer.music.play(-1 if loop else 0)
    except Exception:
        pass


def stop_music_track() -> None:
    """Stop the currently playing background music track."""
    if _pygame_initialized:
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass


def duck_music(duration_s: float = 0.25) -> None:
    """Briefly dip the music volume for heavy impacts to cut through the mix."""
    if not _pygame_initialized:
        return
    try:
        import pygame
        pygame.mixer.music.set_volume(0.35)

        def _restore() -> None:
            import time
            time.sleep(duration_s)
            with contextlib.suppress(Exception):
                pygame.mixer.music.set_volume(0.75)

        threading.Thread(target=_restore, daemon=True).start()
    except Exception:
        pass


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
                _ = subprocess.run(
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
