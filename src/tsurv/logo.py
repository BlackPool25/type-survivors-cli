"""Baked logo art, decrypt title motion, and alpha-hub footer copy.

The PNG in ``assets/`` is the art source of truth; this module only bakes it
to terminal cells deterministically (same file plus width always yields the
same string) and owns the hub footer/decrypt helpers.
"""

from __future__ import annotations

import io
from importlib import resources
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Final, NewType, assert_never

from PIL import Image
from rich.console import Console
from rich_pixels import HalfcellRenderer, Pixels
from terminaltexteffects.effects.effect_decrypt import Decrypt

if TYPE_CHECKING:
    from tsurv.profile import Profile

RenderedLogo = NewType("RenderedLogo", str)
"""Baked logo cells: ANSI half-blocks in color, plain blocks in mono."""

TAGLINE: Final = "╰~-~-~-~-~── ※ TYPE FAST OR BE EATEN BY THE VOID ※ ──~-~-~-~-~╯"
"""Hub subtitle; the decrypt-in effect settles on exactly this line."""

_LOGO_PNG: Final = Path(str(resources.files("tsurv") / "assets" / "logo.png"))
"""Pre-sized art source; resolved from the package location, never CWD."""

_MIN_CELLS: Final = 8
_MONO_RAMP: Final = "@%#*+=-:. "
"""Dark-to-light ASCII ramp for the NO_COLOR bake."""


class LogoError(ValueError):
    """Bad bake width or an unreadable logo asset."""


def _luminance_cell(value: int) -> str:
    """Map one 0-255 luminance sample to the mono bake ramp."""
    bands = len(_MONO_RAMP)
    return _MONO_RAMP[min(value * bands // 256, bands - 1)]


def _block_mean(
    raw: bytes,
    src_w: int,
    cell: tuple[int, int],
    grid: tuple[int, int],
) -> int:
    """Mean luminance of the source block behind one mono-bake cell."""
    cx, cy = cell
    cells_w, rows = grid
    src_h = len(raw) // src_w
    x0, x1 = cx * src_w // cells_w, (cx + 1) * src_w // cells_w
    y0, y1 = cy * src_h // rows, (cy + 1) * src_h // rows
    total = sum(raw[y * src_w + x] for y in range(y0, y1) for x in range(x0, x1))
    return total // max((x1 - x0) * (y1 - y0), 1)


def render_logo(cells_w: int, *, mono: bool = False) -> RenderedLogo:
    """Bake the logo PNG to exactly ``cells_w`` wide terminal cells.

    Color uses rich-pixels half-cells; mono maps luminance to ASCII blocks.
    """
    if cells_w < _MIN_CELLS:
        msg = f"logo width {cells_w} below minimum {_MIN_CELLS}"
        raise LogoError(msg)
    try:
        with Image.open(_LOGO_PNG) as handle:
            image = handle.convert("RGB")
    except OSError as exc:
        msg = f"cannot load logo art from {_LOGO_PNG}: {exc}"
        raise LogoError(msg) from exc
    rows = max(1, round(image.height * cells_w / image.width / 2))
    match mono:
        case True:
            gray = image.convert("L")
            src_w = gray.size[0]
            raw: bytes = bytes(gray.tobytes())
            lines: list[str] = [
                "".join(
                    _luminance_cell(_block_mean(raw, src_w, (cx, cy), (cells_w, rows)))
                    for cx in range(cells_w)
                )
                for cy in range(rows)
            ]
            return RenderedLogo("\n".join(lines))
        case False:
            # Halfcell pairs need a 2-rows-per-line image; Pixels downscales
            # with NEAREST, whose odd sampling lands inside the 2px art grid.
            pixels = Pixels.from_image(
                image,
                resize=(cells_w, rows * 2),
                renderer=HalfcellRenderer(),
            )
            buffer = io.StringIO()
            console = Console(
                file=buffer,
                force_terminal=True,
                color_system="truecolor",
                width=cells_w + 4,
            )
            console.print(pixels)
            return RenderedLogo(buffer.getvalue().removesuffix("\n"))
        case _:
            assert_never(mono)


def decrypt_frames(text: str, *, limit: int = 24) -> tuple[str, ...]:
    """Sample TTE decrypt frames for ``text``; the tail is the settled line.

    Only the first ``limit`` frames are generated, so boot stays fast while
    the hub plays the glitch-in and lands on the exact input text.
    """
    if not text:
        return ("",)
    if limit <= 0:
        return (text,)
    sampled = tuple(str(frame) for frame in islice(Decrypt(text), limit))
    return (*sampled, text)


def hub_footer(profile: Profile) -> str:
    """Alpha-dashboard stats line: best WPM, banked gold, top wave level."""
    best = 0
    level = 1
    for run in profile.runs:
        if run.wpm_samples:
            best = max(best, int(sum(run.wpm_samples) / len(run.wpm_samples)))
        level = max(level, run.wave)
    return f"best {best} WPM / {profile.gold}g gold / LV {level}"
