"""Pure visual mapping: sprite frames, juice overlays, hub chrome, void drift.

Widget-free on purpose: every helper here is a pure function of game state,
so tests pin the display without a terminal. The arena screen mounts the PNGs
through par-textual-image; this module only selects *what* shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos
from pathlib import Path
from typing import TYPE_CHECKING, Final, assert_never

from rich.text import Text

from tsurv.arena import EnemyKind
from tsurv.stage import FieldSprite, world_to_cell
from tsurv.words import Corruption, Tier

if TYPE_CHECKING:
    from tsurv.juice import JuiceState, Particle

ASSETS_DIR: Final = Path(__file__).resolve().parent.parent.parent / "assets"
"""Repo sprite art: boss/grunt/mite/hex/core PNGs plus the void backdrop."""

APPROACH_MAX: Final = 16
"""Widest approach indent in cells: far foes start right, glide core-ward."""

COMPACT_WIDTH: Final = 120
"""Below this width the arena halves approach indents, sprites stay legible."""

AMBIENT_SEEDS: Final = 6
"""Void specks per ambient line: deterministic in tick, never a state system."""

BURST_GLYPHS: Final = 12
"""Cap on death-burst glyphs so one kill never floods the fx line."""

SHAKE_CELLS: Final = 2
"""Max jitter cells at full trauma: rattle reads without hiding words."""

_BEAM_LINE: Final = "═✦═ DIRECT HIT ═✦═"
"""Kill-beam ribbon: Core to the fallen foe, shown inside the flash window."""

_RING_LINE: Final = "((SHOCKWAVE))"
"""Knockback ring text raised while a bar break blasts outward."""

_BURST_CELL: Final = "*"
"""One death-burst mote: ASCII so mono terminals keep the burst."""

_SLOW_MARK: Final = "SLO-MO"
"""Slow-mo tint marker: text first, color never the only signal."""

_FADE_CELL: Final = "·"
"""Fading mote: small speck once size drops to half, mono-safe."""

_FADE_SIZE: Final = 0.5
"""Mote shrink point: below half size the burst speck replaces the star."""

BOB_FPS: Final = 6
"""Sprite bob rate: idle/bob frames alternate six times a second."""

AGITATED_DISTANCE: Final = 2.0
"""Inside this distance a foe is agitated: double bob plus a warning mark."""

RADIAL_STEP: Final = 2
"""Cells of ring radius per distance unit: foes ring the centered core."""

_PORTAL_MARK: Final = "◌"
"""Spawn-portal glyph: shown while a foe scales in, before it closes in."""

_AGITATED_MARK: Final = "»"
"""Close-in warning: plain glyph so the threat reads in mono too."""

_CORE_PULSE: Final = 4
"""Core pulse period in ticks: frame swap reads as breathing."""

_GLYPH_FONT: Final[dict[str, tuple[str, str, str]]] = {
    "E": ("███", "██ ", "███"),
    "I": (" █ ", " █ ", " █ "),
    "O": (" █ ", "█ █", " █ "),
    "P": ("███", "█ █", "███"),
    "R": ("███", "███", "█ █"),
    "S": (" ██", "███", "██ "),
    "T": ("███", " █ ", " █ "),
    "U": ("█ █", "█ █", "███"),
    "V": ("█ █", "█ █", " █ "),
    "Y": ("█ █", " █ ", " █ "),
}
"""3x3 block capitals for the hub banner (only banner letters, nothing else)."""

BANNER_GRADIENT: Final[tuple[str, str, str]] = ("#FF2A2A", "#FFD23F", "#24AEEB")
"""Banner row colors, top to bottom: red rage, gold glory, void blue."""


def _render_word(word: str) -> tuple[str, str, str]:
    """Set one word in the block font, single-space letter separators."""
    glyphs = [_GLYPH_FONT[char] for char in word]
    rows = [" ".join(parts) for parts in zip(*glyphs, strict=True)]
    return (rows[0], rows[1], rows[2])


def _render_banner(words: tuple[str, ...]) -> tuple[str, str, str]:
    """Set banner words in the block font, triple-space word separators."""
    rendered = [_render_word(word) for word in words]
    rows = ["   ".join(parts) for parts in zip(*rendered, strict=True)]
    return (rows[0], rows[1], rows[2])


HUB_BANNER: Final[tuple[str, str, str]] = _render_banner(("TYPE", "SURVIVORS"))
"""FIGlet-style title, pre-rendered once at import; callers copy by value."""


@dataclass(frozen=True, slots=True)
class HubEntry:
    """One hub menu row: its hotkey, label, and hint (all plain text)."""

    key: str
    label: str
    hint: str


HUB_ENTRIES: Final[tuple[HubEntry, ...]] = (
    HubEntry(key="S", label="start", hint="survive timed waves"),
    HubEntry(key="P", label="practice", hint="no-death typing drills"),
    HubEntry(key="R", label="resume", hint="restore the suspended run"),
    HubEntry(key="H", label="shop", hint="spend run gold on perks"),
    HubEntry(key="E", label="settings", hint="palette, sound, shake"),
    HubEntry(key="Q", label="quit", hint="leave the void quietly"),
)
"""Menu rows in hotkey order; the hub screen highlights one at a time."""


@dataclass(frozen=True, slots=True)
class JuiceOverlay:
    """Text-level attack juice derived from live JuiceState (no new state)."""

    beam: str
    burst: str
    ring: bool
    flash: bool
    shake: int
    slow: bool


_MIN_RUNIC_W: Final = 20
_MIN_RUNIC_H: Final = 10
_MIN_BRAZIER_W: Final = 30
_MIN_BRAZIER_H: Final = 12
_FLAME_ANIM_HALF_PERIOD: Final = 2


@dataclass(frozen=True, slots=True)
class BloodSplatter:
    """One persistent floor decal left behind by a fallen foe."""

    x: int
    y: int
    glyph: str
    color: str
    expires_at: float


def runic_floor_layer(
    *,
    width: int,
    height: int,
    cx: int,
    cy: int,
    mono: bool,
) -> tuple[FieldSprite, ...]:
    """Ornate runic circle around the core, low-contrast so words stay readable."""
    if width < _MIN_RUNIC_W or height < _MIN_RUNIC_H:
        return ()
    sprites: list[FieldSprite] = []
    r_x = max(min(width // 4, 12), 4)
    r_y = max(min(height // 4, 5), 2)
    style = "" if mono else "#232338"
    for deg in range(0, 360, 20):
        rad = deg * 0.0174532925
        px = cx + round(cos(rad) * r_x)
        py = cy + round(cos(rad) * r_y)
        if 0 <= px < width and 0 <= py < height:
            glyph = "✦" if deg % 60 == 0 else "·"
            chip = Text(glyph, style=style)
            sprites.append(
                FieldSprite(
                    x=0,
                    y=0,
                    art=(),
                    color=None,
                    chip=chip,
                    chip_x=px,
                    chip_y=py,
                ),
            )
    return tuple(sprites)


def braziers_layer(
    *,
    width: int,
    height: int,
    tick: int,
    mono: bool,
) -> tuple[FieldSprite, ...]:
    """Four flickering corner braziers anchoring the arena boundaries."""
    if width < _MIN_BRAZIER_W or height < _MIN_BRAZIER_H:
        return ()
    sprites: list[FieldSprite] = []
    flame_glyph = "▲" if tick % 4 < _FLAME_ANIM_HALF_PERIOD else "*"
    flame_style = "" if mono else "#FF7A00 bold"
    base_style = "" if mono else "#555577"
    corners = (
        (3, 2),
        (max(width - 4, 0), 2),
        (3, max(height - 3, 0)),
        (max(width - 4, 0), max(height - 3, 0)),
    )
    for bx, by in corners:
        flame_chip = Text(flame_glyph, style=flame_style)
        base_chip = Text("╩", style=base_style)
        sprites.append(
            FieldSprite(
                x=0,
                y=0,
                art=(),
                color=None,
                chip=flame_chip,
                chip_x=bx,
                chip_y=by,
            ),
        )
        sprites.append(
            FieldSprite(
                x=0,
                y=0,
                art=(),
                color=None,
                chip=base_chip,
                chip_x=bx,
                chip_y=by + 1,
            ),
        )
    return tuple(sprites)


def foe_sprite_file(kind: EnemyKind, *, hit: bool, tick: int) -> str:
    """PNG filename for a foe: hit-flash on damage, else idle/bob per tick.

    shortcut: ELITE reuses hex art (no elite PNG ships), upgrade when it lands.
    """
    suffix = "hit" if hit else ("0" if tick % 2 == 0 else "1")
    match kind:
        case EnemyKind.GRUNT:
            stem = "grunt"
        case EnemyKind.MITE:
            stem = "mite"
        case EnemyKind.HEX | EnemyKind.ELITE:
            stem = "hex"
        case EnemyKind.BOSS:
            stem = "boss"
        case _:
            assert_never(kind)
    return f"{stem}_{suffix}.png"


def core_sprite_file(*, hit: bool, tick: int) -> str:
    """PNG filename for the Sanctuary Core: pulse swap, hit frame when critical."""
    if hit:
        return "core_hit.png"
    return "core_0.png" if tick % _CORE_PULSE < _CORE_PULSE // 2 else "core_1.png"


def sprite_path(filename: str) -> Path:
    """Resolve a sprite filename against the repo assets directory."""
    return ASSETS_DIR / filename


def foe_hit_showing(juice: JuiceState, now: float) -> bool:
    """Report whether foes should wear the hit frame (inside the flash window)."""
    return now < juice.flash_until


def tier_pips(tier: Tier) -> int:
    """Level pips for a word tier: harder tiers wear more filled pips."""
    match tier:
        case Tier.T1:
            return 1
        case Tier.T2:
            return 2
        case Tier.T3:
            return 3
        case Tier.CODE:
            return 4
        case Tier.BOSS:
            return 3
        case _:
            assert_never(tier)


_CORRUPTION_MARKS: Final[dict[Corruption, str]] = {
    Corruption.CLEAN: "",
    Corruption.REVERSED: "~",
    Corruption.GLITCH: "※",
    Corruption.ROT13: "§",
}
"""Corruption wins the plate mark; CLEAN falls through to the kind glyph."""


def foe_mark(kind: EnemyKind, corruption: Corruption) -> str:
    """One difficulty/corruption glyph: corruption wins, kind is the default."""
    mark = _CORRUPTION_MARKS[corruption]
    if mark:
        return mark
    match kind:
        case EnemyKind.GRUNT:
            return ">"
        case EnemyKind.MITE:
            return "»"
        case EnemyKind.HEX:
            return "◆"
        case EnemyKind.ELITE:
            return "◈"
        case EnemyKind.BOSS:
            return "☠"
        case _:
            assert_never(kind)


_ELITE_RING: Final = "◯"
"""Elite ring: a large circle worn around the tier circle."""

_BOSS_CROWN: Final = "♛"
"""Boss crown: worn above the art, red in color, shape alone in mono."""

_BOSS_CROWN_COLOR: Final = "#FF2A2A"
"""Crown red: matches the boss body color."""


@dataclass(frozen=True, slots=True)
class Marker:
    """Circle tier marker: tinted circle, elite ring, boss crown above.

    The circle phase encodes the tier so shape alone separates tiers in
    mono; color is None exactly when mono strips the tint.
    """

    glyph: str
    color: str | None
    ring: str
    crown: str
    crown_color: str | None


def marker(
    kind: EnemyKind,
    tier: Tier,
    *,
    elite: bool,
    boss: bool,
    mono: bool,
) -> Marker:
    """Circle marker for a foe: tier circle, elite ring, boss crown above.

    The ring rides the tier tint; the crown is always boss red. Kind
    backstops the flags so ELITE/BOSS foes wear their marks regardless.
    """
    match tier:
        case Tier.T1:
            glyph, color = "○", "#24AEEB"
        case Tier.T2:
            glyph, color = "◔", "#39FF6A"
        case Tier.T3:
            glyph, color = "◑", "#FFD23F"
        case Tier.CODE:
            glyph, color = "◕", "#B57CFF"
        case Tier.BOSS:
            glyph, color = "◉", "#FF2A2A"
        case _:
            assert_never(tier)
    crowned = boss or kind is EnemyKind.BOSS
    return Marker(
        glyph=glyph,
        color=None if mono else color,
        ring=_ELITE_RING if (elite or kind is EnemyKind.ELITE) else "",
        crown=_BOSS_CROWN if crowned else "",
        crown_color=None if (mono or not crowned) else _BOSS_CROWN_COLOR,
    )


def foe_plate_text(
    word: str,
    *,
    kind: EnemyKind,
    tier: Tier,
    corruption: Corruption,
    hp_words: int,
) -> str:
    """Enemy plate: `[pips] word [symbol]` in plain glyphs, mono-safe.

    Bosses wear one pip per remaining HP bar instead of the tier count.
    """
    pips = hp_words if kind is EnemyKind.BOSS else tier_pips(tier)
    return f"{'●' * pips} {word} {foe_mark(kind, corruption)}"


def agitated(distance: float) -> bool:
    """Report whether a foe is close enough to read as agitated."""
    return distance < AGITATED_DISTANCE


def radial_indent(  # noqa: PLR0913 - ring math needs angle, radius, framing
    *,
    angle: float,
    distance: float,
    width: int,
    plate_len: int,
    compact: bool,
    scroll: int = 0,
) -> str:
    """Ring offset around the centered core: cos(angle) pushes east/west.

    The plate centers on the viewport middle at zero radius; `scroll` adds
    the wave-advance drift so the background pans as the core steps forward.
    """
    radius = min(int(distance * RADIAL_STEP), APPROACH_MAX)
    if compact:
        radius //= 2
    center = max(width, 1) // 2 - plate_len // 2
    return " " * max(0, center + round(cos(angle) * radius) + scroll)


def portal_mark() -> str:
    """Spawn-portal glyph for a foe still scaling into the ring."""
    return _PORTAL_MARK


def boss_portal_mark() -> str:
    """Boss spawn-portal: doubled glyph, larger and distinct, mono-safe."""
    return _PORTAL_MARK * 2


def agitated_mark() -> str:
    """Close-in warning glyph for an agitated foe."""
    return _AGITATED_MARK


def approach_indent(distance: float, *, compact: bool) -> str:
    """Spaces pushing far foes right so positions visibly glide core-ward."""
    steps = min(int(distance), APPROACH_MAX)
    if compact:
        steps //= 2
    return " " * steps


def juice_overlay(juice: JuiceState, now: float) -> JuiceOverlay:
    """Map live juice windows onto text overlays (beam/burst/ring/flash/shake)."""
    motes = min(len(juice.particles), BURST_GLYPHS)
    return JuiceOverlay(
        beam=_BEAM_LINE if now < juice.flash_until else "",
        burst=_BURST_CELL * motes,
        ring=now < juice.knockback_until,
        flash=now < juice.flash_until,
        shake=round(juice.trauma * SHAKE_CELLS),
        slow=now < juice.slow_mo_until,
    )


_ADVANCE_LINE: Final = "▲ ▲ ▲ SANCTUARY ADVANCES ▲ ▲ ▲"
"""Wave-clear ribbon: the step-forward names itself while drift pans."""


def particle_layer(
    particles: tuple[Particle, ...],
    *,
    width: int,
    height: int,
    mono: bool,
    shake: int = 0,
) -> tuple[FieldSprite, ...]:
    """One chip-glyph sprite per live mote, camera-mapped to canvas cells.

    Fresh motes paint the burst star in their blood tint; fading motes
    shrink to a speck. Mono drops the tint, keeping the glyph.
    """
    sprites: list[FieldSprite] = []
    for mote in particles:
        cx, cy = world_to_cell(x=mote.x, y=mote.y, width=width, height=height)
        glyph = _BURST_CELL if mote.size > _FADE_SIZE else _FADE_CELL
        chip = Text()
        _ = chip.append(glyph, style=None if mono else mote.color)
        sprites.append(
            FieldSprite(
                x=0,
                y=0,
                art=(),
                color=None,
                chip=chip,
                chip_x=min(max(cx + shake, 0), max(width - 1, 0)),
                chip_y=cy,
            ),
        )
    return tuple(sprites)


def fx_line(overlay: JuiceOverlay, *, advancing: bool = False) -> str:
    """Combine one tick of overlays into the single fx ribbon line."""
    parts = [overlay.beam, overlay.burst]
    if overlay.ring:
        parts.append(_RING_LINE)
    if overlay.slow:
        parts.append(_SLOW_MARK)
    if advancing:
        parts.append(_ADVANCE_LINE)
    return " ".join(part for part in parts if part)


def ambient_line(width: int, tick: int, *, boost: int = 1) -> str:
    """Slow drifting void specks: deterministic in tick, behind gameplay."""
    cells = [" "] * max(width, 1)
    span = max(width, 1)
    for seed in range(AMBIENT_SEEDS * boost):
        cells[(seed * 13 + tick // BOB_FPS) % span] = "·"
    return "".join(cells)


def hub_banner_text(*, mono: bool) -> Text:
    """Fresh banner copy per call: gradient spans in color, plain in mono."""
    text = Text()
    for index, row in enumerate(HUB_BANNER):
        if index:
            _ = text.append("\n")
        if mono:
            _ = text.append(row)
        else:
            _ = text.append(row, style=BANNER_GRADIENT[index % len(BANNER_GRADIENT)])
    return text


def hub_list_text(
    entries: tuple[HubEntry, ...],
    selected: int,
    *,
    mono: bool,
) -> Text:
    """Styled menu list: ▶ marker plus highlight on the selected row."""
    text = Text()
    for index, entry in enumerate(entries):
        if index:
            _ = text.append("\n")
        marker = "▶ " if index == selected % len(entries) else "  "
        row = f"{marker}{entry.key} {entry.label} — {entry.hint}"
        if mono or index != selected % len(entries):
            _ = text.append(row)
        else:
            _ = text.append(row, style="reverse bold")
    return text


def hub_greeting(*, gold: int, runs: int) -> str:
    """Empty-profile send-off versus returning-player welcome (plain text)."""
    if gold == 0 and runs == 0:
        return "fresh soul — S to begin the first run"
    return f"welcome back — {runs} runs, {gold}g banked"


def shop_row_text(name: str, price: int, blurb: str, *, owned: bool) -> str:
    """One shop row: OWNED tag or gold price, always beside the blurb."""
    tag = "OWNED" if owned else f"{price}g"
    return f"{name} — {tag} · {blurb}"
