"""Synthesize the game's tiny WAV assets (stdlib only, no hand-made binaries).

Run: `uv run python scripts/gen_audio.py`. Writes three loopable mono WAVs
into assets/audio/: a 2s ambient drone (integer-cycle layered sines, so the
loop is seamless), a 0.12s kill blip (downward sweep with decay), and a 1s
boss roar (detuned low stack with a deterministic inharmonic edge). Every
asset stays under 100KB at 22050Hz 16-bit mono.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Final

RATE: Final = 22050
"""Sample rate: voice-grade, keeps the 2s drone under 100KB."""

AMPLITUDE: Final = 16000
"""Peak int16 swing: loud enough on laptop speakers, never clipping."""

AUDIO_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "audio"
"""Asset home: the game resolves these at runtime, never hand-edited."""


def _to_int16(samples: list[float]) -> bytes:
    """Pack float samples to int16 mono frames (deterministic bytes).

    Gain normalization caps the peak at AMPLITUDE, so every rounded sample
    already fits int16: no clamp branch, no silent saturation.
    """
    peak = max((abs(sample) for sample in samples), default=0.0)
    peak = max(peak, 1e-9)
    gain = AMPLITUDE / peak if peak > AMPLITUDE else 1.0
    return struct.pack(
        f"<{len(samples)}h",
        *(round(sample * gain) for sample in samples),
    )


def _write(name: str, samples: list[float]) -> Path:
    """Write one mono WAV into the audio assets directory."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / name
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(_to_int16(samples))
    return path


def _ambient() -> list[float]:
    """Two-second drone: 55/82.5/110/165Hz complete whole cycles, so it loops."""
    seconds = 2.0
    count = int(RATE * seconds)
    partials = ((55.0, 0.30), (82.5, 0.22), (110.0, 0.15), (165.0, 0.10))
    samples = []
    for index in range(count):
        moment = index / RATE
        tremolo = 0.8 + 0.2 * math.sin(2.0 * math.pi * 0.5 * moment)
        tone = sum(
            level * math.sin(2.0 * math.pi * freq * moment) for freq, level in partials
        )
        samples.append(AMPLITUDE * tone * tremolo)
    return samples


def _kill() -> list[float]:
    """Kill blip: 880 to 520Hz sweep with exponential decay."""
    seconds = 0.12
    count = int(RATE * seconds)
    samples = []
    for index in range(count):
        moment = index / RATE
        freq = 880.0 - (360.0 * moment / seconds)
        decay = math.exp(-moment * 28.0)
        samples.append(AMPLITUDE * math.sin(2.0 * math.pi * freq * moment) * decay)
    return samples


def _boss() -> list[float]:
    """Boss roar: detuned low stack plus an inharmonic edge, swelling in."""
    seconds = 1.0
    count = int(RATE * seconds)
    partials = ((55.0, 0.35), (58.3, 0.30), (82.5, 0.18), (123.0, 0.12))
    samples = []
    for index in range(count):
        moment = index / RATE
        swell = min(1.0, moment / 0.15) * math.exp(-moment * 1.8)
        tone = sum(
            level * math.sin(2.0 * math.pi * freq * moment) for freq, level in partials
        )
        samples.append(AMPLITUDE * tone * swell)
    return samples


def main() -> None:
    """Render all three assets and report their byte sizes."""
    for name, synth in (
        ("ambient.wav", _ambient),
        ("kill.wav", _kill),
        ("boss.wav", _boss),
    ):
        path = _write(name, synth())
        print(f"{path.name}: {path.stat().st_size} bytes")  # noqa: T201 - CLI report


if __name__ == "__main__":
    main()
