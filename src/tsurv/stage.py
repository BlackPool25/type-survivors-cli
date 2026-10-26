"""True-2D arena stage: renderer probe, canvas coords, hand-built cell art.

The par-textual-image row layout is gone: kitty-capable terminals get PNG
sprites on absolute canvas coords, everything else gets this module's
hand-authored half-block field (``▀`` upper px as FG, lower px as BG, so one
cell carries two vertical pixels). All mapping here is pure and headless-
testable; only :class:`ArenaCanvas` touches Textual.
"""

from __future__ import annotations

import contextlib
import os
import select
import time
from dataclasses import dataclass
from enum import StrEnum
from math import cos, sin
from typing import TYPE_CHECKING, Final, override

from rich.text import Text
from textual.widget import Widget

from tsurv.arena import EnemyKind

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from rich.style import Style

_TRUEPIXEL_ENV: Final = "TSURV_TRUEPIXEL"
"""Force flag: 1 pins kitty PNGs on, 0 pins the cells fallback on."""

_PAR_ENV: Final = "PAR_TERM_GRAPHICS"
"""par-textual-image's own fast path; kitty here agrees with our kitty path."""

_TERM_PROGRAM_ENV: Final = "TERM_PROGRAM"
"""Ghostty/VSCode/WezTerm name themselves here; kitty via TERM."""

_TERM_ENV: Final = "TERM"
"""Kitty advertises xterm-kitty here; xterm-ghostty likewise."""

_GRAPHIC_TERMS: Final = ("ghostty", "kitty", "wezterm", "vscode", "xterm-ghostty")
"""Allowlist: terminals known to speak the kitty graphics protocol."""

_TTY_QUERY: Final = b"\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\"
"""Kitty support probe: a 1px query upload the terminal never stores."""

_TTY_QUERY_TIMEOUT_S: Final = 0.1
"""Probe wait: a local terminal answers in ~1ms; silence reads as cells."""

_TTY_REPLY_MAX: Final = 64
"""Reply cap: the `;OK` verdict lands in the first few bytes or never."""

_UNKNOWN_REASON: Final = "no graphics protocol"
"""Diagnostics reason when nothing advertises true-pixel support."""

_RADIUS_PER_DISTANCE: Final = 2
"""Canvas cells of ring radius per distance unit (foes ring the core)."""

_SQUASH: Final = 2
"""Vertical squash: cells are ~2x tall, so y radius halves for round rings."""


class RendererKind(StrEnum):
    """Active sprite renderer: true-pixel PNGs or hand-built cells."""

    KITTY = "kitty"
    CELLS = "cells"


@dataclass(frozen=True, slots=True)
class RendererPick:
    """Probed renderer plus the human reason shown on the diagnostics line."""

    kind: RendererKind
    reason: str

    @property
    def label(self) -> str:
        """Diagnostics line: `pixels: kitty (ghostty)` / `pixels: cells ...`."""
        return f"pixels: {self.kind.value} ({self.reason})"


def select_renderer(
    *,
    truepixel: str | None = None,
    par_graphics: str | None = None,
    term_program: str = "",
    term: str = "",
    tty_kitty: bool = False,
) -> RendererPick:
    """Pick the sprite renderer: force flag, par hint, allowlist, TTY, cells.

    `tty_kitty` is the live query answer (`query_kitty_graphics`): it only
    fills the allowlist-miss slot, so explicit pins always win. Ghostty behind
    tmux/ssh strips its env ads; the 0.1s query is what still finds it.
    """
    if truepixel == "1":
        kind, reason = RendererKind.KITTY, f"{_TRUEPIXEL_ENV}=1"
    elif truepixel == "0":
        kind, reason = RendererKind.CELLS, f"{_TRUEPIXEL_ENV}=0"
    elif par_graphics == "kitty":
        kind, reason = RendererKind.KITTY, f"{_PAR_ENV}=kitty"
    elif par_graphics in ("sixel", "iterm2", "halfblock"):
        kind, reason = RendererKind.CELLS, f"{_PAR_ENV}={par_graphics}"
    else:
        kind, reason = RendererKind.CELLS, _UNKNOWN_REASON
        hay = f"{term_program} {term}".lower()
        token = next((name for name in _GRAPHIC_TERMS if name in hay), None)
        if token is not None:
            kind, reason = RendererKind.KITTY, token
        elif tty_kitty:
            kind, reason = RendererKind.KITTY, "tty-query"
    return RendererPick(kind, reason)


def query_kitty_graphics(*, timeout_s: float = _TTY_QUERY_TIMEOUT_S) -> bool:
    """Ask the controlling terminal for kitty graphics; silence means no.

    Sends the spec's query action (a 1px upload the terminal neither stores
    nor displays) and waits for the `;OK` reply. Anything unexpected — no
    tty, a short write, a timeout — is a clean False, and no DA1 fence is
    sent, so a silent terminal keeps zero unread bytes behind. A widget-time
    race with Textual's reader degrades to the cells fallback, never worse.
    """
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return False
    try:
        return _await_tty_ok(fd, timeout_s)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


def _await_tty_ok(fd: int, timeout_s: float) -> bool:
    """Write the probe and wait for `;OK` (any I/O surprise reads as no)."""
    try:
        _ = os.write(fd, _TTY_QUERY)
        data = bytearray()
        end = time.monotonic() + timeout_s
        while len(data) < _TTY_REPLY_MAX:
            remaining = end - time.monotonic()
            if remaining <= 0.0:
                break
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                break
            chunk = os.read(fd, _TTY_REPLY_MAX - len(data))
            if not chunk:
                break
            data += chunk
            if b";OK" in data:
                break
    except OSError:
        return False
    return b";OK" in data


def probe_renderer(
    env: Mapping[str, str] | None = None,
    *,
    query_tty: Callable[[], bool] = query_kitty_graphics,
) -> RendererPick:
    """Startup probe: env pins first, then the TTY query, then cells."""
    live = os.environ if env is None else env
    pick = select_renderer(
        truepixel=live.get(_TRUEPIXEL_ENV),
        par_graphics=live.get(_PAR_ENV),
        term_program=live.get(_TERM_PROGRAM_ENV, ""),
        term=live.get(_TERM_ENV, ""),
    )
    if (
        pick.kind is RendererKind.CELLS
        and pick.reason == _UNKNOWN_REASON
        and query_tty()
    ):
        return RendererPick(RendererKind.KITTY, "tty-query")
    return pick


def canvas_xy(  # noqa: PLR0913 - ring math needs angle, distance, framing
    *,
    angle: float,
    distance: float,
    width: int,
    height: int,
    scroll: int = 0,
    compact: bool = False,
) -> tuple[int, int]:
    """Polar foe placement mapped to canvas cells across the whole field.

    Distance zero lands dead-center; radius caps at the largest circle that
    fits, clamped into the viewport. ``scroll`` pans east after a wave
    clears; ``compact`` halves the radius on narrow viewports.
    """
    cx = width // 2
    cy = height // 2
    reach = max(min(width, height * _SQUASH) // _SQUASH - _SQUASH, 0)
    radius = min(int(distance * _RADIUS_PER_DISTANCE), reach)
    if compact:
        radius //= _SQUASH
    x = cx + round(cos(angle) * radius) + scroll
    y = cy + round(sin(angle) * radius / _SQUASH)
    return (
        min(max(x, 0), max(width - 1, 0)),
        min(max(y, 0), max(height - 1, 0)),
    )


def world_to_cell(*, x: float, y: float, width: int, height: int) -> tuple[int, int]:
    """Camera map: world units to canvas cells, core-centered at any viewport.

    Scale matches the ring math (two cells per unit, vertical squash), so one
    world pos lands on the same center-relative cell at 80x24 and 120x30.
    Clamps into the viewport: far rings clip instead of escaping.
    """
    cx = width // 2
    cy = height // 2
    px = cx + round(x * _RADIUS_PER_DISTANCE)
    py = cy + round(y * _RADIUS_PER_DISTANCE / _SQUASH)
    return (
        min(max(px, 0), max(width - 1, 0)),
        min(max(py, 0), max(height - 1, 0)),
    )


def art_origin(x: int, y: int, art: tuple[str, ...]) -> tuple[int, int]:
    """Top-left cell anchoring pixel art centered on a canvas point."""
    return (x - len(art[0]) // 2, y - (len(art) + 1) // 4)


def crown_origin(x: int, y: int, art: tuple[str, ...]) -> tuple[int, int]:
    """Boss-crown anchor: centered above the sprite's top row."""
    return (x, y - (len(art) + 1) // 4 - 1)


def chip_origin(  # noqa: PLR0913 - chip anchor needs sprite box and room
    tx: int,
    ty: int,
    *,
    art_w: int,
    art_h: int,
    chip_len: int,
    width: int,
) -> tuple[int, int]:
    """Word-chip anchor: right of the sprite, flipping left at the edge."""
    row = ty + art_h // 2
    if tx + art_w + 1 + chip_len <= width:
        return (tx + art_w + 1, row)
    return (tx - 1 - chip_len, row)


_GRUNT_ART: Final = (
    " ### ",
    "## ##",
    "#####",
    " ### ",
    "  #  ",
    " # # ",
)
_GRUNT_HIT: Final = (
    "#   #",
    " ### ",
    "# # #",
    "#####",
    " # # ",
    "  #  ",
)
_MITE_ART: Final = (
    " # ",
    "###",
    "# #",
    " # ",
)
_MITE_HIT: Final = (
    "# #",
    " # ",
    "# #",
    " # ",
)
_HEX_ART: Final = (
    " ### ",
    "#   #",
    "# ###",
    "# # #",
    "#   #",
    " ### ",
)
_HEX_HIT: Final = (
    "#####",
    "# # #",
    "## ##",
    "# # #",
    "## ##",
    "#####",
)
_ELITE_ART: Final = (
    "   #   ",
    "  ###  ",
    " # # # ",
    "#######",
    "##   ##",
    " ##### ",
    "  # #  ",
    "   #   ",
)
_ELITE_HIT: Final = (
    "##   ##",
    " ## ## ",
    "  ###  ",
    "#######",
    "# ### #",
    " ##### ",
    " #   # ",
    "   #   ",
)
_BOSS_ART: Final = (
    "    ###    ",
    "   #####   ",
    "  ##   ##  ",
    " ### # ### ",
    "####   ####",
    "###########",
    " ## ### ## ",
    "   #####   ",
    "    ###    ",
    "    # #    ",
)
_BOSS_HIT: Final = (
    "##       ##",
    " ##     ## ",
    "  #######  ",
    " ######### ",
    "#### # ####",
    " ######### ",
    "  ##   ##  ",
    "   #####   ",
    "    ###    ",
    "   ## ##   ",
)
_CORE_ART: Final = (
    "    #    ",
    "   ###   ",
    "  ## ##  ",
    " ### ### ",
    "#### ####",
    " ### ### ",
    "  ## ##  ",
    "   ###   ",
)
_CORE_HIT: Final = (
    "    #    ",
    "  ## ##  ",
    "   ###   ",
    " ##   ## ",
    "##  #  ##",
    " ##   ## ",
    "   ###   ",
    "  ## ##  ",
)
_PORTAL_ART: Final = (
    " ◌ ",
    "◌ ◌",
    " ◌ ",
)
_BOSS_PORTAL_ART: Final = (
    "  ◌  ",
    " ◌ ◌ ",
    "◌   ◌",
    " ◌ ◌ ",
)

CELL_ART: Final[Mapping[EnemyKind, tuple[str, ...]]] = {
    EnemyKind.GRUNT: _GRUNT_ART,
    EnemyKind.MITE: _MITE_ART,
    EnemyKind.HEX: _HEX_ART,
    EnemyKind.ELITE: _ELITE_ART,
    EnemyKind.BOSS: _BOSS_ART,
}
"""Hand-built foe silhouettes: boss dwarfs the grunt, elite stands alone."""

CELL_ART_HIT: Final[Mapping[EnemyKind, tuple[str, ...]]] = {
    EnemyKind.GRUNT: _GRUNT_HIT,
    EnemyKind.MITE: _MITE_HIT,
    EnemyKind.HEX: _HEX_HIT,
    EnemyKind.ELITE: _ELITE_HIT,
    EnemyKind.BOSS: _BOSS_HIT,
}
"""Hit-flash variants: same bounds, spiked pattern, mono still flashes."""

CORE_ART: Final = _CORE_ART
"""Sanctuary Core silhouette for the cells fallback."""

CORE_ART_HIT: Final = _CORE_HIT
"""Core critical frame: same bounds, breached pattern."""


def portal_art(*, boss: bool) -> tuple[str, ...]:
    """Spawn-portal ring: doubled for the boss, mono-safe either way."""
    return _BOSS_PORTAL_ART if boss else _PORTAL_ART


_KIND_COLORS: Final[dict[EnemyKind | None, str]] = {
    EnemyKind.GRUNT: "#24AEEB",
    EnemyKind.MITE: "#B57CFF",
    EnemyKind.HEX: "#952CF5",
    EnemyKind.ELITE: "#FFD23F",
    EnemyKind.BOSS: "#FF2A2A",
    None: "#39FF6A",
}
"""Body colors per kind (None is the core); shape carries mono identity."""

_HIT_COLOR: Final = "#FFFFFF"
"""Hit flash: white reads on every body color."""


def sprite_color(kind: EnemyKind | None, *, hit: bool, mono: bool) -> str | None:
    """Body color for a kind (None kind is the core); None when mono/hit-flash.

    Hit swaps to white so the flash reads even where shapes match; mono
    returns None so the field carries shape only.
    """
    if mono:
        return None
    if hit:
        return _HIT_COLOR
    return _KIND_COLORS[kind]


@dataclass(frozen=True, slots=True)
class FieldSprite:
    """One blit: pixel art at top-left cells plus its anchored word chip."""

    x: int
    y: int
    art: tuple[str, ...]
    color: str | None
    chip: Text
    chip_x: int = 0
    chip_y: int = 0


def _chip_styles(chip: Text) -> list[Style | str | None]:
    """Per-char styles from chip spans (later spans win, console-free)."""
    plain = chip.plain
    styles: list[Style | str | None] = [None] * len(plain)
    for span in chip.spans:
        for index in range(span.start, min(span.end, len(plain))):
            styles[index] = span.style
    return styles


@dataclass(slots=True)
class _FieldBuffers:
    """Mutable blit buffers: half-block colors plus chip glyph overlays."""

    upper: list[list[str | None]]
    lower: list[list[str | None]]
    glyphs: list[list[str]]
    paints: list[list[Style | str | None]]
    height: int
    width: int


def _blit_art(buffers: _FieldBuffers, sprite: FieldSprite) -> None:
    """Stamp art pixel pairs into the half-block buffers (clipped)."""
    rows = sprite.art
    for pair in range((len(rows) + 1) // 2):
        cy = sprite.y + pair
        if cy < 0 or cy >= buffers.height:
            continue
        top = rows[pair * 2] if pair * 2 < len(rows) else ""
        bottom = rows[pair * 2 + 1] if pair * 2 + 1 < len(rows) else ""
        for col in range(max(len(top), len(bottom))):
            cx = sprite.x + col
            if cx < 0 or cx >= buffers.width:
                continue
            if col < len(top) and top[col] != " ":
                buffers.upper[cy][cx] = sprite.color
            if col < len(bottom) and bottom[col] != " ":
                buffers.lower[cy][cx] = sprite.color


def _blit_chip(buffers: _FieldBuffers, sprite: FieldSprite) -> None:
    """Overwrite cells with the word chip (spaces stay transparent)."""
    plain = sprite.chip.plain
    styles = _chip_styles(sprite.chip)
    for index, char in enumerate(plain):
        if char in (" ", "\n"):
            continue
        cx = sprite.chip_x + index
        cy = sprite.chip_y
        if cx < 0 or cx >= buffers.width or cy < 0 or cy >= buffers.height:
            continue
        buffers.glyphs[cy][cx] = char
        buffers.paints[cy][cx] = styles[index]
        buffers.upper[cy][cx] = None
        buffers.lower[cy][cx] = None


def _assemble_field(buffers: _FieldBuffers) -> Text:
    """Fold pixel buffers plus chip glyphs into one half-block Text."""
    text = Text()
    for row in range(buffers.height):
        if row:
            _ = text.append("\n")
        for col in range(buffers.width):
            char = buffers.glyphs[row][col]
            if char != " ":
                _ = text.append(char, style=buffers.paints[row][col])
                continue
            up = buffers.upper[row][col]
            low = buffers.lower[row][col]
            if up is not None and low is not None:
                _ = text.append("█", style=f"{up} on {low}")
            elif up is not None:
                _ = text.append("▀", style=up)
            elif low is not None:
                _ = text.append("▄", style=low)
            else:
                _ = text.append(" ")
    return text


def render_field(
    *,
    width: int,
    height: int,
    sprites: tuple[FieldSprite, ...],
) -> Text:
    """Composite pixel art plus word chips into one half-block Text field.

    Each art pixel pair renders as one cell (``█`` full, ``▀`` upper,
    ``▄`` lower, colored when a color rides along); chips overwrite cells
    as text, flipping handled by the caller. Out-of-bounds blits clip.
    """
    if width <= 0 or height <= 0:
        return Text("")
    buffers = _FieldBuffers(
        upper=[[None] * width for _ in range(height)],
        lower=[[None] * width for _ in range(height)],
        glyphs=[[" "] * width for _ in range(height)],
        paints=[[None] * width for _ in range(height)],
        height=height,
        width=width,
    )
    for sprite in sprites:
        _blit_art(buffers, sprite)
        _blit_chip(buffers, sprite)
    return _assemble_field(buffers)


class ArenaCanvas(Widget):
    """Cells fallback field: shows the latest composited half-block Text."""

    def __init__(self, *, widget_id: str | None = None) -> None:
        """Hold an empty field until the first stage refresh paints it."""
        super().__init__(id=widget_id)
        self._field: Text = Text("")

    @property
    def rendered(self) -> Text:
        """Latest composited field (pilots read chips and core through this)."""
        return self._field

    def set_field(self, field: Text) -> None:
        """Swap in a fresh composite and repaint the widget."""
        self._field = field
        _ = self.refresh()

    @override
    def render(self) -> Text:
        """Paint the latest composite (plain Text, styles ride the spans)."""
        return self._field
