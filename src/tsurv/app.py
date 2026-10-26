"""Textual arena: playable endless loop, two screens, pause flag, 60fps tick."""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import random
import time
from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, assert_never, override

from par_textual_image import TerminalImage
from PIL import Image, ImageOps
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, ProgressBar, Sparkline

from tsurv.arena import (
    ArenaEnemy,
    ArenaState,
    EnemyKind,
    advance,
    apply_pickup,
    boss_cleared,
    chain_lightning,
    corrupted_display,
    handle_keystroke,
    initial_arena,
    mercy_spawn_factor,
    mercy_tier,
    reset_word,
    roll_drop,
    seconds_to_impact,
    set_boss_wave,
    spawn_count_for_level,
    spawn_enemy,
    spawn_radius_for_level,
    spawn_wave,
    world_xy,
)
from tsurv.audio import (
    AudioConfig,
    MusicTrack,
    Sound,
    default_enabled,
    find_player,
    play_event,
    play_music_track,
    start_ambient,
    stop_music_track,
)
from tsurv.combat import Advanced, EnemyId, Kill, TypoStun, rolling_wpm, spawn_interval
from tsurv.grammar import GrammarError, generate_boss_sentence
from tsurv.items import nova_charge, nova_ready
from tsurv.juice import (
    JuiceState,
    apply_calibration,
    calibrate_base_wpm,
    is_bar_break,
    low_hp,
    step_juice,
    telegraph_showing,
    time_scale,
    trigger_bar_break,
    trigger_kill,
)
from tsurv.logo import TAGLINE, decrypt_frames, hub_footer, render_logo
from tsurv.metrics import (
    Consistency,
    Seconds,
    Tally,
    consistency,
    leak_missed,
    net_wpm,
    tally_accuracy,
    tally_of,
)
from tsurv.profile import Profile, RunSummary, Settings, weak_keys_for_spawn
from tsurv.report import render_report
from tsurv.screens import (
    HELP_TEXT,
    SHOP_CATALOG,
    CheckpointError,
    ShopError,
    buy_item,
    load_checkpoint,
    next_palette,
    practice_advance,
    restore,
    save_checkpoint,
    snapshot,
    update_settings,
)
from tsurv.stage import (
    CELL_ART,
    CELL_ART_HIT,
    CORE_ART,
    CORE_ART_HIT,
    ArenaCanvas,
    FieldSprite,
    RendererKind,
    RendererPick,
    art_origin,
    canvas_xy,
    chip_origin,
    edge_spawn_distance,
    portal_art,
    probe_renderer,
    render_field,
    sprite_color,
)
from tsurv.visuals import (
    BOB_FPS,
    HUB_ENTRIES,
    HubEntry,
    agitated,
    agitated_mark,
    ambient_line,
    boss_portal_mark,
    core_sprite_file,
    foe_hit_showing,
    foe_sprite_file,
    fx_line,
    hub_banner_text,
    hub_greeting,
    hub_list_text,
    juice_overlay,
    marker,
    particle_layer,
    portal_mark,
    shop_row_text,
    sprite_path,
)
from tsurv.words import (
    TIER_WORDS,
    Tier,
    Word,
    WordText,
    chunk_boss_sentence,
    pick_word,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from textual import events

GUARD_WIDTH: Final = 80
"""Windows narrower than this show the guard screen instead of the arena."""

_sprite_cache: dict[str, Image.Image] = {}
"""Loaded sprite art, cached so TerminalImage never holds file handles open."""


_ARENA_VOID: Final = (11, 11, 18)
"""Backdrop RGB of the arena void: kitty-safe sprite backing."""


def sprite_image(filename: str) -> Image.Image | None:
    """Load sprite bytes once, cached; art doubles: size reads threat.

    Kitty transmits RGB (alpha arrives as pure black), so art is composited
    onto the arena void here: the frame blends seamlessly, art stays exact.
    Doubling to 96px fills the 10x6 widget's fit box with a square paint.
    """
    if filename not in _sprite_cache:
        path = sprite_path(filename)
        if not path.is_file():
            return None
        with Image.open(path) as handle:
            pic = handle.convert("RGBA")
            _ = pic.load()
        pic = ImageOps.scale(pic, 2, resample=Image.Resampling.NEAREST)
        void = Image.new("RGBA", pic.size, (*_ARENA_VOID, 255))
        _sprite_cache[filename] = Image.alpha_composite(void, pic)
    return _sprite_cache[filename]


MAX_BOSS_BARS: Final = 6
"""Stacked ProgressBar pool; boss HP above this clamps the display."""

HUB_COLUMN_MAX: Final = 120
"""Ultrawide hub cap: the menu column never sprawls past this (mirrors CSS)."""


class PauseAction(StrEnum):
    """Pause menu verbs: resume, help, settings, suspend-and-hub, quit."""

    RESUME = "RESUME"
    HOW_TO = "HOW_TO"
    SETTINGS = "SETTINGS"
    SUSPEND_HUB = "SUSPEND_HUB"
    QUIT = "QUIT"


PAUSE_ENTRIES: Final[tuple[HubEntry, ...]] = (
    HubEntry(key="R", label="Resume", hint="back to the run"),
    HubEntry(key="H", label="How to Play", hint="goal, keys, mercy"),
    HubEntry(key="E", label="Settings", hint="palette, sound, shake"),
    HubEntry(key="S", label="Suspend & Hub", hint="save and leave to menu"),
    HubEntry(key="Q", label="Quit", hint="leave the void quietly"),
)
"""Pause menu rows: the five brief options in row order (j/k + Enter)."""

_PAUSE_KEYS: Final[dict[str, PauseAction]] = {
    "r": PauseAction.RESUME,
    "h": PauseAction.HOW_TO,
    "e": PauseAction.SETTINGS,
    "s": PauseAction.SUSPEND_HUB,
    "q": PauseAction.QUIT,
}


def pause_action_for(key: str) -> PauseAction | None:
    """Map a pause-menu key to its verb; anything else is not an action."""
    return _PAUSE_KEYS.get(key.lower())


MAX_FOES: Final = 8
"""On-screen enemy cap, bounding layout and difficulty."""

SPAWN_OUTSIDE_MARGIN: Final = 1.0
"""Off-screen spawn margin: foes start this many world units past the edge."""

REF_WPM: Final = 40.0
"""Reference WPM for adaptive spawn pacing."""

WAVE_SECONDS: Final = 30.0
"""Timed waves: survive the clock for a checkpoint and breather."""

BOSS_EVERY: Final = 5
"""Boss wave cadence (boss waves end on kill, not on the clock)."""

_SAMPLE_WINDOW_S: Final = 60.0
"""Trailing press history feeding the consistency gate (idle never counts)."""

_WPM_PER_PRESS_SECOND: Final = 12.0
"""Raw WPM sustained by one press in a second (chars/5 per minute)."""

_START_HP: Final = 100.0

_BOSS_GENERATION_ATTEMPTS: Final = 2
"""Grammar tries per boss spawn before falling back to the T3 word list."""
# Wave entered immediately after wave 1 clears: the only calibration point.
_CALIBRATION_WAVE: Final = 2

HP_GREEN: Final = "#39FF6A"
"""Typed-prefix highlight (Blood Neon Void HP green, cf. hub.tcss)."""

GOLD_NEXT: Final = "#FFD23F"
"""Next-char underline (Blood Neon Void gold, cf. hub.tcss)."""


def colors_enabled() -> bool:
    """NO_COLOR strips color: mono rendering when the variable is present."""
    return "NO_COLOR" not in os.environ


def is_narrow(width: int) -> bool:
    """Guard predicate: windows under 80 cols cannot host the arena."""
    return width < GUARD_WIDTH


def boss_word_text(
    rank: int,
    used: set[str],
    rng: random.Random,
    weak_keys: tuple[str, ...] = (),
) -> tuple[str, int]:
    """Build the single-boss word queue: bars chunks over grammar sentences.

    Returns the space-joined phrase plus its bar count (2 + rank). Grammar
    gets a retry, then the T3 word list deals so a boss wave always spawns.
    """
    bars = 2 + rank
    for _ in range(_BOSS_GENERATION_ATTEMPTS):
        try:
            chunks: list[str] = []
            while len(chunks) < bars:
                sentence = generate_boss_sentence(rank, used, rng, weak_keys)
                chunks.extend(chunk_boss_sentence(sentence))
            return " ".join(chunks[:bars]), bars
        except GrammarError:
            continue
    pool = tuple(word for word in TIER_WORDS[Tier.T3] if str(word).isascii())
    fallback = pool or TIER_WORDS[Tier.T1]
    return " ".join(str(rng.choice(fallback)) for _ in range(bars)), bars


def _default_words() -> tuple[str, ...]:
    """Deal three opening T1 words honoring spawn constraints."""
    shown: list[str] = []
    for _ in range(3):
        shown.append(str(pick_word(Tier.T1, (), shown).text))
    return tuple(shown)


def leaked_untyped(before: ArenaState, leaked: tuple[EnemyId, ...]) -> int:
    """Count chars left untyped on leaked foes, matched by stable foe id."""
    gone = set(leaked)
    total = 0
    for foe in before.enemies:
        if foe.id in gone:
            typed = before.typed if foe.id == before.current else 0
            total += leak_missed(str(foe.word.text), typed)
    return total


_HP_BAR_CELLS: Final = 10
"""Top-rail HP bar width: ten blocks, each a tenth of max HP."""

_WAVE_BAR_CELLS: Final = 5
"""Bottom-rail wave bar width: one block per wave in the boss cycle."""

_HP_RED: Final = "#FF2A2A"
"""HP bar red: matches the boss crown and the death banner."""


def _bar_text(*, fraction: float, width: int) -> str:
    """Block bar: filled share of `width`, clamped, mono-safe glyphs."""
    filled = min(max(round(fraction * width), 0), width)
    return "█" * filled + "░" * (width - filled)


def marker_plate(
    *,
    kind: EnemyKind,
    tier: Tier,
    word: str,
    mono: bool,
) -> Text:
    """Circle-marker plate: crown + tier circle + ring + word, tinted.

    Pip plates are gone: the tier circle carries difficulty, the elite ring
    and boss crown ride alongside, and color never works alone (mono keeps
    every glyph, drops every tint).
    """
    mark = marker(
        kind,
        tier,
        elite=kind is EnemyKind.ELITE,
        boss=kind is EnemyKind.BOSS,
        mono=mono,
    )
    text = Text()
    if mark.crown:
        _ = text.append(f"{mark.crown} ", style=mark.crown_color)
    _ = text.append(f"{mark.glyph}{mark.ring} {word}", style=mark.color)
    return text


def hud_top_rail(  # noqa: PLR0913 - a rail needs the full HUD snapshot at once
    *,
    hp: float,
    max_hp: float,
    streak: int,
    score: int,
    accuracy: float,
    consist: Consistency,
    mono: bool,
) -> Text:
    """Top rail: red HP bar `hp/max`, streak ×N, score, net ACC%, consistency."""  # noqa: RUF002 - intentional streak glyph, not letter x
    bar = _bar_text(
        fraction=hp / max_hp if max_hp > 0.0 else 0.0,
        width=_HP_BAR_CELLS,
    )
    text = Text()
    _ = text.append("HP [")
    _ = text.append(bar, style=None if mono else _HP_RED)
    consist_text = (
        "CONS ~"
        if consist.rough or consist.value is None
        else f"CONS {consist.value:.0f}"
    )
    _ = text.append(f"] {hp:.0f}/{max_hp:.0f}  ×{streak}  ")  # noqa: RUF001 - intentional streak glyph, not letter x
    _ = text.append(f"score {score}  ACC {accuracy:.0%}  {consist_text}")
    return text


def hud_bottom_rail(*, wave: int) -> Text:
    """Bottom rail: wave banner, progress n/5, BOSS IN n, LV k."""
    cycle = wave % BOSS_EVERY
    done = BOSS_EVERY if cycle == 0 else cycle
    bar = _bar_text(fraction=done / BOSS_EVERY, width=_WAVE_BAR_CELLS)
    countdown = "BOSS WAVE" if cycle == 0 else f"BOSS IN {BOSS_EVERY - cycle}"
    return Text(f"« WAVE {wave} »  [{bar}] {done}/{BOSS_EVERY}  {countdown}  LV {wave}")


class ArenaScreen(Screen[None]):
    """The playable endless loop; death and pause stay on this screen."""

    # Blood Neon Void values reused from hub.tcss (same hexes). hub.tcss
    # itself is not loaded: its $panel variable collides with Textual 8
    # App.DEFAULT_CSS ("hatch: right $panel") and breaks stylesheet parsing.
    _GOLDEN_ANGLE: ClassVar[float] = math.pi * (3.0 - math.sqrt(5.0))
    """Spawn ring spread: each foe lands ~137.5° from the last, no clumping."""

    _SPAWN_JITTER: ClassVar[float] = 0.3
    """Spawn ring looseness (radians): the ring reads organic, not clockwork."""

    _PORTAL_S: ClassVar[float] = 0.3
    """Spawn portal lifetime: telegraph obeys the >=200ms readability rule."""

    _BOSS_BANNER_S: ClassVar[float] = 2.5
    """Boss banner hold: the OVERLORD warning outlives the screen shake."""

    _ADVANCE_S: ClassVar[float] = 0.5
    """Core advance length: the MC visibly steps forward, drift sells motion."""

    _ADVANCE_DRIFT_CELLS: ClassVar[int] = 3
    """Background pan width after a wave clears, easing back to rest."""

    _ADVANCE_DRIFT_S: ClassVar[float] = 2.0
    """Pan ease length: the drift outlives the step so motion reads."""

    _SPRITE_W: ClassVar[int] = 10
    """Kitty foe sprite widget width: PNGs fit the same box on all kinds."""

    _SPRITE_H: ClassVar[int] = 6
    """Kitty foe sprite widget height: the kitty trim eats 4 rows (see below)."""

    _CORE_W: ClassVar[int] = 12
    """Kitty core sprite widget width: the Sanctuary Core renders large."""

    _CORE_H: ClassVar[int] = 6
    """Kitty core sprite widget height: rows keep the paint transmitting."""

    _PAINT_W: ClassVar[int] = 4
    """Painted PNG footprint: 2x art in a 10x6 widget fits a square 4x2."""

    _PAINT_H: ClassVar[int] = 2
    """Painted PNG height: a 96px sprite covers ~2 cells at terminal pixels."""

    _BOSS_PAINT_W: ClassVar[int] = 4
    """Boss paint width: doubled art covers ~4 cells (same 2-cell height)."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#arena, #stage, #field, .foe-sprite, #core-sprite { background: #0B0B12; }\n"
        "#topbar { width: 1fr; height: 3; border: solid #952CF5; color: #CACACA; }\n"
        "#arena { height: 1fr; border: solid #952CF5; }\n"
        "#stage { height: 1fr; }\n"
        "#field { width: 1fr; height: 1fr; }\n"
        ".foe-sprite { position: absolute; width: 10; height: 6; }\n"
        "#core-sprite { position: absolute; width: 10; height: 6; }\n"
        ".foe-chip { position: absolute; width: auto; height: 1; }\n"
        "#bossbanner { width: 1fr; height: 2; color: #FF2A2A; "
        "text-style: bold; text-align: center; }\n"
        f"#bossbars {{ height: {MAX_BOSS_BARS}; }}\n"
        "#fx { width: 1fr; height: 1; color: #FFD23F; }\n"
        "#pixdiag { width: 1fr; height: 1; color: #24AEEB; text-align: center; }\n"
        "#botrail { width: 1fr; height: 1; color: #CACACA; }\n"
        "#pause { width: 1fr; height: auto; color: #FFD23F; "
        "border: solid #952CF5; text-align: center; }\n"
        "#typing { width: 1fr; height: 3; border: solid #952CF5; dock: bottom; "
        "color: #CACACA; }\n"
        "#stun { height: 1; color: #FFD23F; }\n"
        "#guard { height: 1; color: #FF2A2A; text-align: center; }\n"
        "#death { height: 2; color: #FF2A2A; text-style: bold; }\n"
    )

    def __init__(  # noqa: PLR0913 - arena config is one flat tested surface
        self,
        initial_words: tuple[str, ...] = ("cat",),
        initial_boss: str | None = None,
        app: TypeSurvivorsApp | None = None,
        *,
        spawn_enabled: bool = True,
        weak_keys: tuple[str, ...] = (),
        seed: int | None = None,
        practice: bool = False,
        checkpoint_dir: Path | None = None,
    ) -> None:
        """Seed the arena; tests inject words and disable the spawner."""
        super().__init__()
        self._spawned_total: int = 0
        self._spawned_at: dict[EnemyId, float] = {}
        self._rng: random.Random = random.Random(seed)  # noqa: S311 - gameplay RNG
        self._juice: JuiceState = JuiceState()
        self._boss_banner_until: float = 0.0
        state = initial_arena(hp=_START_HP)
        for text in initial_words:
            state = spawn_enemy(
                state,
                Word(text=WordText(text), tier=Tier.T1),
                distance=5.0,
            )
            state = self._place_last(state)
        if initial_boss is not None:
            state = set_boss_wave(state, flag=True)
            state = spawn_enemy(
                state,
                Word(text=WordText(initial_boss), tier=Tier.T3),
                kind=EnemyKind.BOSS,
                hp_words=2,
                distance=8.0,
            )
            state = self._place_last(state)
            now = time.monotonic()
            self._boss_banner_until = now + self._BOSS_BANNER_S
            self._juice = replace(self._juice, trauma=1.0)
        self._arena: ArenaState = state
        self._app_ref: TypeSurvivorsApp | None = app
        self._spawn_enabled: bool = spawn_enabled
        self._weak_keys: tuple[str, ...] = weak_keys
        self._boss_sentences: set[str] = set()
        self.paused: bool = False
        self._practice: bool = practice
        self._checkpoint_dir: Path | None = checkpoint_dir
        self._run_clock: float = 0.0
        self.mono: bool = not colors_enabled()
        self._clock: float = 0.0
        self._wave_clock: float = 0.0
        self._kill_times: list[float] = []
        self._press_times: list[float] = []
        self._best_streak: int = 0
        self._nova_good_seconds: float = 0.0
        self._tally: Tally = Tally()
        self._killer: str | None = None
        self._boss_bars: list[ProgressBar] = [
            ProgressBar(total=1, show_bar=True, show_percentage=False)
            for _ in range(MAX_BOSS_BARS)
        ]
        self._pick: RendererPick = probe_renderer()
        self._ring_seated: bool = False
        self._pre_mount_ids: frozenset[EnemyId] = frozenset(
            foe.id for foe in state.enemies
        )
        self._last_wave: int = state.wave
        self._advance_until: float = 0.0
        self._drift_until: float = 0.0
        self._pause_selected: int = 0
        self._pause_help: bool = False
        self._audio_player: str | None = None
        self._stop_ambient: Callable[[], None] | None = None

    @property
    def arena_state(self) -> ArenaState:
        """Current pure arena state (tests read score/foes through this)."""
        return self._arena

    @property
    def advance_active(self) -> bool:
        """Whether the core's wave-clear step-forward is still playing."""
        return time.monotonic() < self._advance_until

    @property
    def boss_banner_text(self) -> str:
        """Live boss banner line (empty once the announce window lapses)."""
        if time.monotonic() >= self._boss_banner_until:
            return ""
        names = [
            str(foe.word.text).upper()
            for foe in self._arena.enemies
            if foe.kind is EnemyKind.BOSS
        ]
        return f"OVERLORD APPROACHES{f' - {names[0]}' if names else ''}"

    @property
    def foe_angles(self) -> tuple[float, ...]:
        """Spawn-ring angles in enemy order (render-owned, sim-neutral)."""
        return tuple(foe.angle for foe in self._arena.enemies)

    @property
    def score_value(self) -> int:
        """Run score as a plain int for assertions."""
        return int(self._arena.score)

    @property
    def foes_text(self) -> str:
        """Plain-text foe listing (word chips, one per line)."""
        frame_tick = int(self._run_clock * BOB_FPS)
        now = time.monotonic()
        return "\n".join(
            self._chip_text(foe, frame_tick, now).plain for foe in self._arena.enemies
        )

    @property
    def foes_span_count(self) -> int:
        """Style span count on the foe chips (zero exactly when mono)."""
        frame_tick = int(self._run_clock * BOB_FPS)
        now = time.monotonic()
        return sum(
            len(self._chip_text(foe, frame_tick, now).spans)
            for foe in self._arena.enemies
        )

    @property
    def pixdiag_text(self) -> str:
        """Active renderer diagnostics line (tests read the probe through this)."""
        return self._pick.label

    @property
    def stun_visible(self) -> bool:
        """Whether the typo gun-jam flag is currently shown."""
        return self.query_one("#stun", Label).display

    @property
    def tally(self) -> Tally:
        """Live keystroke taxonomy (feeds accuracy, HUD, and the recap)."""
        return self._tally

    @property
    def hits(self) -> int:
        """Correct keypresses this run (feeds the recap accuracy)."""
        return self._tally.correct

    @property
    def presses(self) -> int:
        """Total keypresses this run (missed leak chars are not presses)."""
        return self._tally.correct + self._tally.incorrect + self._tally.extra

    def _wpm_samples(self, now: float) -> tuple[float, ...]:
        """Per-second raw WPM over trailing active seconds (idle never counts)."""
        buckets: dict[int, int] = {}
        for moment in self._press_times:
            if now - _SAMPLE_WINDOW_S < moment <= now:
                second = int(moment)
                buckets[second] = buckets.get(second, 0) + 1
        return tuple(
            count * _WPM_PER_PRESS_SECOND for _, count in sorted(buckets.items())
        )

    @property
    def best_streak(self) -> int:
        """Highest streak this run (feeds the recap table)."""
        return self._best_streak

    @property
    def wpm_trail(self) -> tuple[float, ...]:
        """Per-second WPM trail for the recap chart (idle never counts)."""
        return self._wpm_samples(time.monotonic())

    @property
    def nova_armed(self) -> bool:
        """Whether net accuracy charged NOVA through its 95% gate."""
        return nova_ready(tally_accuracy(self._tally), self._nova_good_seconds)

    @property
    def killer(self) -> str | None:
        """Word that dealt the killing leak, if the run is over."""
        return self._killer

    @property
    def clock(self) -> float:
        """Seconds survived this run (feeds the recap duration)."""
        return self._run_clock

    @property
    def hit_stop_active(self) -> bool:
        """Whether bar-break hit-stop currently freezes the sim."""
        return self._juice.frozen_at(time.monotonic())

    @property
    def spectacle_active(self) -> bool:
        """Whether the boss banner holds sim time (spawn/impact clocks stop)."""
        return time.monotonic() < self._boss_banner_until

    def end_spectacle(self) -> None:
        """Dismiss the boss-entrance banner early so sim clocks resume."""
        self._boss_banner_until = 0.0

    @property
    def knockback_active(self) -> bool:
        """Whether the knockback blast window is currently raised."""
        return time.monotonic() < self._juice.knockback_until

    @property
    def slow_mo_active(self) -> bool:
        """Whether the x8 streak slow-mo window is currently armed."""
        return time.monotonic() < self._juice.slow_mo_until

    @property
    def flash_active(self) -> bool:
        """Whether the bar-break white flash is currently showing."""
        return time.monotonic() < self._juice.flash_until

    @property
    def particle_count(self) -> int:
        """Live knockback motes (zero once the one-shot burst dies)."""
        return len(self._juice.particles)

    @property
    def shake_active(self) -> bool:
        """Whether trauma rattles the frame (honors the settings toggle)."""
        if self._app_ref is not None and not self._app_ref.profile.settings.shake:
            return False
        return self._juice.shake_active

    @property
    def low_hp_pulse(self) -> bool:
        """Whether vitals sit at/below the low-HP pulse threshold."""
        return low_hp(self._arena.hp, self._arena.max_hp)

    def set_restored(self, state: ArenaState) -> None:
        """Replace the live arena with a checkpoint-restored snapshot."""
        self._arena = state

    @override
    def compose(self) -> ComposeResult:
        """Header, true-2D stage, boss bars, fx, diagnostics, typing, flags."""
        kitty = self._pick.kind is RendererKind.KITTY
        yield Label("", id="topbar")
        yield Label("", id="bossbanner")
        with Vertical(id="arena"):
            with Vertical(id="stage"):
                if kitty:
                    yield TerminalImage(id="core-sprite")
                    for index in range(MAX_FOES):
                        yield TerminalImage(
                            id=f"foe-sprite-{index}",
                            classes="foe-sprite",
                        )
                        yield Label("", id=f"foe-word-{index}", classes="foe-chip")
                else:
                    yield ArenaCanvas(widget_id="field")
            with Vertical(id="bossbars"):
                yield from self._boss_bars
        yield Label("", id="fx")
        yield Label("", id="pixdiag")
        yield Label("", id="botrail")
        yield Label("", id="pause")
        yield Label("", id="typing")
        yield Label("", id="stun")
        yield Label("widen to 80+ columns to play", id="guard")
        yield Label("", id="death")

    def on_mount(self) -> None:
        """First paint, explicit kitty pin, viewport guard, then 60fps tick."""
        if self._pick.kind is RendererKind.KITTY:
            for widget in self.query(TerminalImage):
                widget.force_protocol("kitty")
        self._audio_player = find_player() if default_enabled() else None
        self._stop_ambient = start_ambient(
            self._audio_player,
            enabled=self._audio_enabled,
        )
        if self._audio_enabled():
            play_music_track(
                MusicTrack.BOSS if self._arena.boss_wave else MusicTrack.TIER_1,
            )
        self._refresh()
        self.check_viewport()
        _ = self.set_interval(1 / 60, self._tick)

    def on_unmount(self) -> None:
        """Silence the drone and music when the arena leaves the stack."""
        stop_music_track()
        if self._stop_ambient is not None:
            self._stop_ambient()
            self._stop_ambient = None

    def _audio_enabled(self) -> bool:
        """Effective sound switch: profile toggle AND a probed player at mount."""
        profile_on = (
            self._app_ref.profile.settings.sound_on
            if self._app_ref is not None
            else True
        )
        return profile_on and self._audio_player is not None

    def _audio_config(self) -> AudioConfig:
        """Snapshot the current audio state for one fire-and-forget dispatch."""
        return AudioConfig(enabled=self._audio_enabled(), player=self._audio_player)

    def on_resize(self, _event: events.Resize) -> None:
        """Re-evaluate the guard breakpoint on every terminal resize."""
        self.check_viewport()

    def check_viewport(self) -> None:
        """Show the guard label (hiding the arena) under 80 columns."""
        narrow = is_narrow(self.size.width)
        self.query_one("#guard", Label).display = narrow
        self.query_one("#arena", Vertical).display = not narrow

    def spawn_test_enemy(self, text: str, distance: float = 5.0) -> None:
        """Spawn one grunt outside the spawner (deterministic tests)."""
        self._arena = spawn_enemy(
            self._arena,
            Word(text=WordText(text), tier=Tier.T1),
            distance=distance,
        )
        self._arena = self._place_last(self._arena)
        self._refresh()

    def _deal_angle(self) -> float:
        """Golden-angle ring slot plus jitter: spawns surround, never stack."""
        angle = self._spawned_total * self._GOLDEN_ANGLE
        angle += self._rng.uniform(-self._SPAWN_JITTER, self._SPAWN_JITTER)
        return angle % (2.0 * math.pi)

    def _place_last(self, state: ArenaState) -> ArenaState:
        """Deal the newest foe its ring angle; sim movement never reads it."""
        if not state.enemies:
            return state
        foe = state.enemies[-1]
        placed = replace(foe, angle=self._deal_angle())
        self._spawned_total += 1
        self._spawned_at[placed.id] = time.monotonic()
        return replace(state, enemies=(*state.enemies[:-1], placed))

    def tick(self, dt: float = 1 / 60) -> None:
        """Advance movement, leaks, waves, and spawns (pause/death gate it).

        The panic path never propagates: a raising update autosuspends the
        run and lands on the hub instead of dumping a traceback.
        """
        try:
            self._step(dt)
        except Exception as exc:  # noqa: BLE001 - panic path catches everything
            self._crash(exc)

    def _edge_floor(self, angle: float) -> float:
        """Per-angle spawn floor: level radius, lifted past the field edge.

        The margin pushes fresh foes off-screen so they walk visibly in;
        typing never gates on visibility, so nothing soft-locks outside.
        """
        if not self.is_mounted:
            return spawn_radius_for_level(self._arena.wave)
        stage = self.query_one("#stage", Vertical)
        width = stage.content_size.width
        height = stage.content_size.height
        if width <= 0 or height <= 0:
            return spawn_radius_for_level(self._arena.wave)
        edge = edge_spawn_distance(angle=angle, width=width, height=height)
        return max(spawn_radius_for_level(self._arena.wave), edge) + (
            SPAWN_OUTSIDE_MARGIN
        )

    def _seat_initial_ring(self) -> None:
        """Push pre-layout foes out to their live per-angle edge (one-shot).

        Only foes dealt before mount move: explicitly placed foes (tests,
        restored runs) keep their exact distance.
        """
        if self._ring_seated:
            return
        stage = self.query_one("#stage", Vertical)
        if stage.content_size.width <= 0 or stage.content_size.height <= 0:
            return
        self._arena = replace(
            self._arena,
            enemies=tuple(
                replace(foe, distance=max(foe.distance, self._edge_floor(foe.angle)))
                if foe.id in self._pre_mount_ids
                else foe
                for foe in self._arena.enemies
            ),
        )
        self._ring_seated = True

    def _step(self, dt: float = 1 / 60) -> None:
        if self.paused or self._arena.hp <= 0.0:
            return
        self._juice = step_juice(self._juice, dt)
        if self.spectacle_active or self._juice.frozen_at(time.monotonic()):
            # Boss entrance and hit-stop: overlay only, sim clocks hold.
            self._refresh()
            return
        self._seat_initial_ring()
        now = time.monotonic()
        dt *= time_scale(self._juice, now)
        self._run_clock += dt
        self._press_times = [
            moment for moment in self._press_times if now - moment < _SAMPLE_WINDOW_S
        ]
        self._nova_good_seconds = nova_charge(
            self._nova_good_seconds,
            tally_accuracy(self._tally),
            dt,
        )
        before_leak = self._arena
        if self._practice:
            self._arena, leaked = practice_advance(self._arena, dt)
        else:
            self._arena, leaked = advance(self._arena, dt)
        if leaked:
            names = {foe.id: str(foe.word.text) for foe in before_leak.enemies}
            self._killer = names[leaked[0]]
            self._tally = self._tally.add_missed(leaked_untyped(before_leak, leaked))
            self._refresh()
            return
        self._wave_clock += dt
        if self._arena.boss_wave:
            if boss_cleared(self._arena):
                self._arena = replace(
                    set_boss_wave(self._arena, flag=False),
                    wave=self._arena.wave + 1,
                )
                self._wave_clock = 0.0
                play_event(self._audio_config(), Sound.WAVE_CLEAR)
                if self._audio_enabled():
                    play_music_track(
                        MusicTrack.TIER_2 if self._arena.wave >= 6 else MusicTrack.TIER_1,
                    )
        elif self._wave_clock >= WAVE_SECONDS:
            self._arena = replace(self._arena, wave=self._arena.wave + 1)
            self._wave_clock = 0.0
            play_event(self._audio_config(), Sound.WAVE_CLEAR)
            self._calibrate_wave()
        if self._spawn_enabled:
            self._clock += dt
            gap = spawn_interval(REF_WPM, rolling_wpm(self._kill_times, now))
            gap *= mercy_spawn_factor(self._arena.mercy)
            if self._clock >= gap and len(self._arena.enemies) < MAX_FOES:
                self._clock = 0.0
                self._spawn_foe()
        self._refresh()

    def _tick(self) -> None:
        """60fps interval callback (thin wrapper so tests drive tick)."""
        self.tick()

    def _spawn_foe(self) -> None:
        """Spawn foes: one multi-bar boss per boss wave, tier words otherwise."""
        shown = [str(foe.word.text) for foe in self._arena.enemies]
        if self._arena.wave % BOSS_EVERY == 0 and not self._arena.boss_wave:
            self._arena = set_boss_wave(self._arena, flag=True)
            rank = max(1, self._arena.wave // BOSS_EVERY)
            text, bars = boss_word_text(
                rank,
                self._boss_sentences,
                self._rng,
                self._weak_keys,
            )
            self._arena = spawn_enemy(
                self._arena,
                Word(text=WordText(text), tier=Tier.T3),
                kind=EnemyKind.BOSS,
                hp_words=bars,
                distance=spawn_radius_for_level(self._arena.wave),
            )
            self._arena = self._place_last(self._arena)
            boss = self._arena.enemies[-1]
            self._arena = replace(
                self._arena,
                enemies=(
                    *self._arena.enemies[:-1],
                    replace(
                        boss,
                        distance=max(boss.distance, self._edge_floor(boss.angle)),
                    ),
                ),
            )
            now = time.monotonic()
            self._boss_banner_until = now + self._BOSS_BANNER_S
            self._juice = replace(self._juice, trauma=1.0)
            play_event(self._audio_config(), Sound.BOSS)
            if self._audio_enabled():
                play_music_track(MusicTrack.BOSS)
            return
        tier = mercy_tier(
            Tier.T1 if self._arena.wave <= 1 else Tier.T2,
            self._arena.mercy,
        )
        overdue = (
            weak_keys_for_spawn(self._app_ref.profile, time.monotonic())
            if self._app_ref is not None
            else ()
        )
        word = pick_word(
            tier,
            (),
            shown,
            weak_keys=self._weak_keys,
            overdue_keys=overdue,
        )
        kind = EnemyKind.GRUNT if len(shown) % 3 else EnemyKind.MITE
        room = MAX_FOES - len(self._arena.enemies)
        count = min(spawn_count_for_level(self._arena.wave), room)
        if count <= 0:
            return
        dealt = [*shown]
        words: list[Word] = []
        for _ in range(count):
            word = pick_word(
                tier,
                (),
                dealt,
                weak_keys=self._weak_keys,
                overdue_keys=overdue,
            )
            words.append(word)
            dealt.append(str(word.text))
        before = len(self._arena.enemies)
        self._arena = spawn_wave(
            self._arena,
            tuple(words),
            self._arena.wave,
            start_angle=self._deal_angle(),
            kind=kind,
        )
        self._arena = replace(
            self._arena,
            enemies=tuple(
                foe
                if index < before
                else replace(
                    foe,
                    distance=max(foe.distance, self._edge_floor(foe.angle)),
                )
                for index, foe in enumerate(self._arena.enemies)
            ),
        )
        now = time.monotonic()
        for foe in self._arena.enemies[before:]:
            self._spawned_total += 1
            self._spawned_at[foe.id] = now

    async def on_key(self, event: events.Key) -> None:
        """Type-to-target: printable chars feed the arena, P pauses."""
        ch = event.character
        if event.key == "escape":
            if self.paused:
                self.paused = False
                self._pause_help = False
                self._refresh()
                return
            self._arena = reset_word(self._arena)
            self._refresh()
            return
        if event.key in ("backspace", "delete"):
            if not self.paused:
                self._arena = reset_word(self._arena)
                play_event(self._audio_config(), Sound.BACKSPACE)
                self._refresh()
            return
        if event.key == "enter" and self.paused:
            self._activate_selected()
            self._refresh()
            return
        if ch is None or self._handle_command_key(ch):
            return
        if is_narrow(self.size.width):
            return
        now = time.monotonic()
        before = self._arena
        locked = before.current is not None
        self._press_times.append(now)
        state, outcome = handle_keystroke(
            before,
            ch,
            now,
            accuracy=tally_accuracy(self._tally),
            consistency=consistency(self._wpm_samples(now)).value,
        )
        self._arena = state
        self._tally = self._tally.add(tally_of(outcome, locked))
        if isinstance(outcome, Kill):
            self._kill_times.append(now)
            play_event(self._audio_config(), Sound.KILL)
            play_event(self._audio_config(), Sound.WORD_POP)
            self._resolve_drop(before, outcome.target)
            self._juice_hit(before, outcome, now)
        elif isinstance(outcome, Advanced):
            play_event(self._audio_config(), Sound.CLICK)
        elif isinstance(outcome, TypoStun):
            play_event(self._audio_config(), Sound.TYPO_JAM)
        self._refresh()

    def _handle_command_key(self, ch: str) -> bool:
        """Pause menu, suspend, and death-recap keys; True when fully handled."""
        if ch == "P" and (self.paused or not self._expects_upper_p()):
            self.paused = not self.paused
            if not self.paused:
                self._pause_help = False
            self._refresh()
            return True
        if self.paused:
            self._handle_paused_key(ch)
            return True
        if len(ch) != 1 or not ch.isprintable():
            return True
        if self._arena.hp <= 0.0:
            if ch == "r" and self._app_ref is not None:
                _ = self._app_ref.push_screen(self._app_ref.report_screen())
            return True
        return False

    def _handle_paused_key(self, ch: str) -> None:
        """Route one paused key: j/k move, P/R resume, rest hit menu verbs."""
        lowered = ch.lower()
        if lowered in ("p", "r"):
            self.paused = False
            self._pause_help = False
        elif lowered == "j":
            self._pause_selected = (self._pause_selected + 1) % len(PAUSE_ENTRIES)
        elif lowered == "k":
            self._pause_selected = (self._pause_selected - 1) % len(PAUSE_ENTRIES)
        else:
            action = pause_action_for(ch)
            if action is not None:
                self._activate_pause_action(action)
        self._refresh()

    def _activate_selected(self) -> None:
        """Run the highlighted pause row (keys mirror _PAUSE_KEYS)."""
        action = pause_action_for(PAUSE_ENTRIES[self._pause_selected].key)
        if action is None:
            return
        self._activate_pause_action(action)

    def _activate_pause_action(self, action: PauseAction) -> None:
        """Run one pause verb (exhaustive over PauseAction)."""
        match action:
            case PauseAction.RESUME:
                self.paused = False
                self._pause_help = False
            case PauseAction.HOW_TO:
                self._pause_help = not self._pause_help
            case PauseAction.SETTINGS:
                if self._app_ref is not None:
                    self._app_ref.open_settings()
            case PauseAction.SUSPEND_HUB:
                self._suspend()
                if self._app_ref is not None:
                    self._app_ref.suspend_to_hub()
            case PauseAction.QUIT:
                if self._app_ref is not None:
                    self._app_ref.exit()
            case _:
                assert_never(action)
        self._refresh()

    def _crash(self, exc: Exception) -> None:
        """Panic path: save the wave, then land on the hub (never a traceback)."""
        with contextlib.suppress(CheckpointError):
            self._suspend()
        if self._app_ref is not None:
            self._app_ref.crash_to_hub(str(exc) or type(exc).__name__)

    def _expects_upper_p(self) -> bool:
        """Report whether the live lock next expects a literal 'P'."""
        current = self._arena.current
        if current is None:
            return False
        foe = next((item for item in self._arena.enemies if item.id == current), None)
        if foe is None:
            return False
        raw = str(foe.word.text)
        return self._arena.typed < len(raw) and raw[self._arena.typed] == "P"

    def _suspend(self) -> None:
        """Write the wave-start snapshot so resume restores it on launch."""
        if self._checkpoint_dir is None:
            return
        save_checkpoint(self._checkpoint_dir, snapshot(self._arena))

    def _juice_hit(self, before: ArenaState, outcome: Kill, now: float) -> None:
        """Raise the knockback blast for bar breaks, rattle for plain kills."""
        foe = next((item for item in before.enemies if item.id == outcome.target), None)
        if foe is None:
            return
        x, y = world_xy(foe)
        if is_bar_break(foe.kind, foe.hp_words):
            self._juice = trigger_bar_break(self._juice, now, self._rng, x, y)
        else:
            self._juice = trigger_kill(self._juice, outcome.streak, now, x, y)

    def _calibrate_wave(self) -> None:
        """Write the wave-1 measured base rate onto the profile once."""
        if self._arena.wave != _CALIBRATION_WAVE:
            return
        if self._practice or not self._kill_times:
            return
        if self._app_ref is None or self._app_ref.profile.base_wpm is not None:
            return
        base = calibrate_base_wpm(tuple(self._kill_times))
        self._app_ref.apply_profile(apply_calibration(self._app_ref.profile, base))

    def _resolve_drop(self, before: ArenaState, target: EnemyId) -> None:
        """Roll the drop table for a kill and auto-apply the pickup."""
        foe = next((item for item in before.enemies if item.id == target), None)
        if foe is None:
            return
        drop = roll_drop(foe.kind, random.random())  # noqa: S311 - gameplay roll
        if drop is None:
            return
        now = time.monotonic()
        self._arena = apply_pickup(self._arena, drop, now)
        if drop.name == "CHAIN_SPARK":
            self._arena, _ = chain_lightning(
                self._arena,
                foe.id,
                accuracy=tally_accuracy(self._tally),
                consistency=consistency(self._wpm_samples(now)).value,
            )

    def _refresh(self) -> None:
        """Repaint header, sprites, foes, fx ribbon, boss bars, flags."""
        state = self._arena
        self._best_streak = max(self._best_streak, state.streak)
        now = time.monotonic()
        overlay = juice_overlay(self._juice, now)
        frame_tick = int(self._run_clock * BOB_FPS)
        hit = foe_hit_showing(self._juice, now)
        accuracy = tally_accuracy(self._tally)
        rail = hud_top_rail(
            hp=state.hp,
            max_hp=state.max_hp,
            streak=state.streak,
            score=int(state.score),
            accuracy=accuracy,
            consist=consistency(self._wpm_samples(now)),
            mono=self.mono,
        )
        if low_hp(state.hp, state.max_hp):
            _ = rail.append(" LOW")
        if overlay.slow:
            _ = rail.append(" SLO-MO")
        self.query_one("#topbar", Label).update(rail)
        if state.wave != self._last_wave:
            self._last_wave = state.wave
            self._advance_until = now + self._ADVANCE_S
            self._drift_until = now + self._ADVANCE_DRIFT_S
        banner = self.query_one("#bossbanner", Label)
        banner.update(Text(self.boss_banner_text))
        banner.display = self.boss_banner_text != ""
        self._refresh_stage(
            frame_tick,
            now,
            self._drift_scroll(now),
            shake=overlay.shake,
            hit=hit,
        )
        self.query_one("#pixdiag", Label).update(Text(self.pixdiag_text))
        self.query_one("#botrail", Label).update(hud_bottom_rail(wave=state.wave))
        ribbon = fx_line(overlay, advancing=self.advance_active) or ambient_line(
            max(self.size.width, 1),
            frame_tick,
            boost=2 if self.advance_active else 1,
        )
        self.query_one("#fx", Label).update(Text(ribbon))
        self._refresh_boss_bars()
        if state.current is None:
            self.query_one("#typing", Label).update(Text(""))
        else:
            foe = next(
                (item for item in state.enemies if item.id == state.current),
                None,
            )
            raw = str(foe.word.text) if foe is not None else ""
            self.query_one("#typing", Label).update(Text(raw[: state.typed]))
        stunned = now < state.stunned_until
        stun = self.query_one("#stun", Label)
        stun.update(Text("JAMMED" if stunned else ""))
        stun.display = stunned
        death = self.query_one("#death", Label)
        dead = state.hp <= 0.0
        if dead and self._killer is not None:
            death.update(Text(f"YOU DIED - slain by {self._killer} (press R)"))
        death.display = dead
        self._refresh_pause()

    def _refresh_pause(self) -> None:
        """Paint the pause overlay while paused (hidden otherwise)."""
        panel = self.query_one("#pause", Label)
        panel.display = self.paused
        if not self.paused:
            return
        hint = "PAUSED — R resume · H help · E settings · S suspend · Q quit\n"
        menu = Text(hint)
        _ = menu.append_text(
            hub_list_text(PAUSE_ENTRIES, self._pause_selected, mono=self.mono),
        )
        if self._pause_help:
            _ = menu.append(f"\n{HELP_TEXT}")
        panel.update(menu)

    def _drift_scroll(self, now: float) -> int:
        """Background pan after a wave clears: 3 cells easing back to rest."""
        remaining = self._drift_until - now
        if remaining <= 0.0:
            return 0
        return round(self._ADVANCE_DRIFT_CELLS * remaining / self._ADVANCE_DRIFT_S)

    def _telegraph_warn(self, foe: ArenaEnemy) -> str:
        """Return the leak-warning marker for foes inside their 200ms window."""
        if telegraph_showing(seconds_to_impact(foe.kind, foe.distance), foe.kind):
            return "!"
        return ""

    def _chip_text(
        self,
        foe: ArenaEnemy,
        frame_tick: int = 0,
        now: float = 0.0,
        *,
        shake: int = 0,
    ) -> Text:
        """One foe word chip: plate (pips + word + mark), shake-shifted.

        Portal foes show the spawn mark while scaling in; agitated foes
        (inside ``AGITATED_DISTANCE``) keep the warning mark and a red plate.
        The typed-lock highlight survives on the word.
        """
        text = Text()
        raw = str(foe.word.text)
        agit = agitated(foe.distance)
        spawned = self._spawned_at.get(foe.id, 0.0)
        prefix = " " * shake
        if now - spawned < self._PORTAL_S:
            ring = boss_portal_mark() if foe.kind is EnemyKind.BOSS else portal_mark()
            prefix += f"{ring}{self._telegraph_warn(foe)} "
        else:
            prefix += f"{' ' if frame_tick % 2 else ''}"
            if agit:
                prefix += agitated_mark()
            prefix += self._telegraph_warn(foe)
            prefix += " "
        state = self._arena
        locked = foe.id == state.current and 0 < state.typed <= len(raw)
        mark = marker(
            foe.kind,
            foe.word.tier,
            elite=foe.kind is EnemyKind.ELITE,
            boss=foe.kind is EnemyKind.BOSS,
            mono=self.mono,
        )
        if self.mono or not locked:
            # Mono strips color only: circles, rings, and crowns still read.
            globe = corrupted_display(foe.word)
            plated = marker_plate(
                kind=foe.kind,
                tier=foe.word.tier,
                word=globe,
                mono=self.mono,
            )
            if agit and not self.mono:
                _ = text.append(prefix)
                _ = text.append(plated.plain, style="bold #FF2A2A")
            else:
                _ = text.append(prefix)
                _ = text.append_text(plated)
            return text
        _ = text.append(prefix)
        if mark.crown:
            _ = text.append(f"{mark.crown} ", style=mark.crown_color)
        _ = text.append(f"{mark.glyph}{mark.ring} ", style=mark.color)
        _ = text.append(raw[: state.typed], style=HP_GREEN)
        _ = text.append(
            raw[state.typed : state.typed + 1],
            style=f"underline {GOLD_NEXT}",
        )
        _ = text.append(raw[state.typed + 1 :])
        return text

    def _set_sprite_image(
        self,
        widget: TerminalImage,
        filename: str,
    ) -> None:
        """Show one cached sprite; missing art hides without leaking ids."""
        pic = sprite_image(filename)
        if pic is None:
            widget.display = False
            if widget.image is not None:
                widget.image = None
            return
        widget.display = True
        if widget.image is not pic:
            widget.image = pic

    def _refresh_stage(
        self,
        frame_tick: int,
        now: float,
        scroll: int,
        *,
        shake: int,
        hit: bool,
    ) -> None:
        """Paint the true-2D stage: kitty PNGs or the cells canvas.

        Core sits dead-center (stepping forward on wave clear); foes ring it
        by sim angle and distance across the whole field. Hidden kitty slots
        release their textures so pooled slots never hold stale sprites.
        """
        foes = self._arena.enemies
        live = {foe.id for foe in foes}
        self._spawned_at = {
            key: born for key, born in self._spawned_at.items() if key in live
        }
        stage = self.query_one("#stage", Vertical)
        width = stage.content_size.width
        height = stage.content_size.height
        if width <= 0 or height <= 0:
            return
        low = low_hp(self._arena.hp, self._arena.max_hp)
        cx, cy = canvas_xy(angle=0.0, distance=0.0, width=width, height=height)
        if self.advance_active:
            cy = max(cy - 1, 0)
        if self._pick.kind is RendererKind.KITTY:
            self._refresh_kitty(
                cx,
                cy,
                frame_tick,
                now,
                scroll,
                shake=shake,
                hit=hit,
            )
            return
        sprites: list[FieldSprite] = []
        core_art = CORE_ART_HIT if low else CORE_ART
        core_x, core_y = art_origin(cx, cy, core_art)
        sprites.append(
            FieldSprite(
                x=core_x,
                y=core_y,
                art=core_art,
                color=sprite_color(None, hit=low, mono=self.mono),
                chip=Text(""),
            ),
        )
        for foe in foes:
            x, y = canvas_xy(
                angle=foe.angle,
                distance=foe.distance,
                width=width,
                height=height,
                scroll=scroll,
            )
            x = min(max(x + shake, 0), width - 1)
            portal = now - self._spawned_at.get(foe.id, 0.0) < self._PORTAL_S
            art = (
                portal_art(boss=foe.kind is EnemyKind.BOSS)
                if portal
                else (CELL_ART_HIT[foe.kind] if hit else CELL_ART[foe.kind])
            )
            chip = self._chip_text(foe, frame_tick, now, shake=shake)
            tx, ty = art_origin(x, y, art)
            chip_x, chip_y = chip_origin(
                tx,
                ty,
                art_w=len(art[0]),
                art_h=(len(art) + 1) // 2,
                chip_len=len(chip.plain),
                width=width,
            )
            sprites.append(
                FieldSprite(
                    x=tx,
                    y=ty,
                    art=art,
                    color=sprite_color(foe.kind, hit=hit, mono=self.mono),
                    chip=chip,
                    chip_x=chip_x,
                    chip_y=chip_y,
                ),
            )
        sprites.extend(
            particle_layer(
                self._juice.particles,
                width=width,
                height=height,
                mono=self.mono,
                shake=shake,
            ),
        )
        self.query_one("#field", ArenaCanvas).set_field(
            render_field(width=width, height=height, sprites=tuple(sprites)),
        )

    def _refresh_kitty(  # noqa: PLR0913 - kitty rebind needs the render context
        self,
        cx: int,
        cy: int,
        frame_tick: int,
        now: float,
        scroll: int,
        *,
        shake: int,
        hit: bool,
    ) -> None:
        """Bind one absolute sprite+chip pair per foe; free hidden slots."""
        stage = self.query_one("#stage", Vertical)
        width = stage.content_size.width
        core_widget = self.query_one("#core-sprite", TerminalImage)
        self._set_sprite_image(
            core_widget,
            core_sprite_file(
                hit=low_hp(self._arena.hp, self._arena.max_hp),
                tick=frame_tick,
            ),
        )
        core_widget.styles.offset = (
            cx - self._PAINT_W // 2,
            cy - self._PAINT_H // 2,
        )
        foes = self._arena.enemies
        for index in range(MAX_FOES):
            sprite = self.query_one(f"#foe-sprite-{index}", TerminalImage)
            chip_label = self.query_one(f"#foe-word-{index}", Label)
            if index >= len(foes):
                if sprite.display:
                    sprite.display = False
                    chip_label.display = False
                    if sprite.image is not None:
                        sprite.image = None
                continue
            foe = foes[index]
            sprite.display = True
            chip_label.display = True
            self._set_sprite_image(
                sprite,
                foe_sprite_file(foe.kind, hit=hit, tick=frame_tick),
            )
            x, y = canvas_xy(
                angle=foe.angle,
                distance=foe.distance,
                width=width,
                height=stage.content_size.height,
                scroll=scroll,
            )
            x = min(max(x + shake, 0), width - 1)
            if foe.kind is EnemyKind.BOSS:
                paint_w = self._BOSS_PAINT_W
            else:
                paint_w = self._PAINT_W
            tx = max(x - paint_w // 2, 0)
            ty = max(y - self._PAINT_H // 2, 0)
            sprite.styles.offset = (tx, ty)
            chip = self._chip_text(foe, frame_tick, now, shake=shake)
            chip_x, chip_y = chip_origin(
                tx,
                ty,
                art_w=paint_w,
                art_h=self._PAINT_H,
                chip_len=len(chip.plain),
                width=width,
            )
            chip_label.styles.offset = (chip_x, chip_y)
            chip_label.update(chip)

    def _refresh_boss_bars(self) -> None:
        """Stacked ProgressBars: one full bar per remaining boss bar."""
        remaining = sum(
            foe.hp_words for foe in self._arena.enemies if foe.kind is EnemyKind.BOSS
        )
        shown = min(remaining, MAX_BOSS_BARS)
        for index, bar in enumerate(self._boss_bars):
            bar.display = index < shown
            if index < shown:
                bar.update(total=1, progress=1)


def report_stats_text(  # noqa: PLR0913 - a recap row needs the full row
    *,
    net: float,
    accuracy: float,
    consistency: float | None,
    best_streak: int,
    kills: int,
    level: int,
) -> Text:
    """Six recap rows: net WPM, accuracy, consistency, streak, kills, level.

    Under-ten-sample consistency reads as a shrug, never as a number.
    """
    consist = (
        f"consistency {consistency:.0f}" if consistency is not None else "consistency ~"
    )
    text = Text()
    _ = text.append(f"net {net:.1f} wpm\n")
    _ = text.append(f"accuracy {accuracy:.0%}\n")
    _ = text.append(f"{consist}\n")
    _ = text.append(f"best streak {best_streak}\n")
    _ = text.append(f"kills {kills}\n")
    _ = text.append(f"level {level}")
    return text


class ReportScreen(Screen[None]):
    """Post-run recap: centered card, WPM chart, stats, retry, S/Q keys."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#report-center { height: 1fr; }\n"
        "#report-middle { width: 1fr; align-horizontal: center; }\n"
        f"#report-column {{ width: 1fr; height: auto; max-width: {HUB_COLUMN_MAX}; "
        "align: center middle; }\n"
        "#report-score { width: 1fr; height: 1; text-align: center; }\n"
        "#report-kills { width: 1fr; height: 1; text-align: center; }\n"
        "#report-wave { width: 1fr; height: 1; text-align: center; }\n"
        "#report-card { width: 1fr; height: 6; text-align: center; }\n"
        "#report-spark { width: 1fr; height: 3; }\n"
        "#report-stats { width: 1fr; height: 6; text-align: center; }\n"
        "#report-hint { width: 1fr; height: 1; color: #952CF5; "
        "text-align: center; }\n"
    )

    def __init__(  # noqa: PLR0913 - the recap carries the full run snapshot
        self,
        score: int,
        kills: int,
        wave: int,
        *,
        card: str = "",
        app: TypeSurvivorsApp | None = None,
        wpm: tuple[float, ...] = (),
        net: float = 0.0,
        accuracy: float = 1.0,
        consistency: float | None = None,
        best_streak: int = 0,
    ) -> None:
        """Snapshot the run tallies; the app link powers R/S/Q navigation."""
        super().__init__()
        self._score: int = score
        self._kills: int = kills
        self._wave: int = wave
        self._card: str = card
        self._app_ref: TypeSurvivorsApp | None = app
        self._wpm: tuple[float, ...] = wpm
        self._net: float = net
        self._accuracy: float = accuracy
        self._consistency: float | None = consistency
        self._best_streak: int = best_streak

    @property
    def score_line(self) -> str:
        """Score tally line for assertions."""
        return f"score {self._score}"

    @property
    def kills_line(self) -> str:
        """Kills tally line for assertions."""
        return f"kills {self._kills}"

    @property
    def wave_line(self) -> str:
        """Wave tally line for assertions."""
        return f"wave {self._wave}"

    @property
    def wpm_trail(self) -> tuple[float, ...]:
        """Per-second WPM trail feeding the chart (empty reads blank)."""
        return self._wpm

    @property
    def card_text(self) -> str:
        """Recap card body for assertions (carries the WPM graph)."""
        return self._card

    @override
    def compose(self) -> ComposeResult:
        """Centered tallies, card, WPM chart, stats, retry, and the key hint."""
        with (
            Center(id="report-center"),
            Middle(id="report-middle"),
            Vertical(
                id="report-column",
            ),
        ):
            yield Label(self.score_line, id="report-score")
            yield Label(self.kills_line, id="report-kills")
            yield Label(self.wave_line, id="report-wave")
            yield Label(self._card, id="report-card")
            yield Sparkline(self._wpm, id="report-spark")
            yield Label(
                report_stats_text(
                    net=self._net,
                    accuracy=self._accuracy,
                    consistency=self._consistency,
                    best_streak=self._best_streak,
                    kills=self._kills,
                    level=self._wave,
                ),
                id="report-stats",
            )
            yield Button("Retry (R)", id="report-retry")
            yield Label("R retry · S shop · Q back to arena", id="report-hint")

    async def on_key(self, event: events.Key) -> None:
        """R retries fresh; S detours to the shop; Q restarts the arena."""
        if self._app_ref is None:
            return
        if event.key == "r":
            self._app_ref.retry_run()
        elif event.key == "s":
            self._app_ref.open_shop()
        elif event.key == "q":
            self._app_ref.return_to_arena()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Deal a fresh run from the Retry button (same as the R key)."""
        if event.button.id == "report-retry" and self._app_ref is not None:
            self._app_ref.retry_run()


_FULL_LOGO_W: Final = 48
"""Full bake: 10 half-cell rows at the 96x40 source art."""

_COMPACT_LOGO_W: Final = 24
"""Compact bake: 5 rows, the largest that fits an 80x24 hub column."""

_MINI_LOGO_W: Final = 16
"""Fallback bake: 3 rows for viewports shorter than 24 rows."""

_TALL_H: Final = 30
"""Full logo at or above this viewport height (content needs 28 of 29)."""

_SHORT_H: Final = 24
"""Compact logo at or above this height (content needs 23 of 23)."""


def _hub_logo_cells(height: int) -> int:
    """Pick the largest logo bake whose column fits the viewport height."""
    if height >= _TALL_H:
        return _FULL_LOGO_W
    if height >= _SHORT_H:
        return _COMPACT_LOGO_W
    return _MINI_LOGO_W


def _hub_logo_text(cells_w: int) -> Text | str:
    """Baked logo cells: styled text in color, plain blocks in mono."""
    mono = not colors_enabled()
    baked = render_logo(cells_w, mono=mono)
    return baked if mono else Text.from_ansi(baked)


_HUB_DECRYPT_STEP_S: Final = 1 / 30
"""Subtitle decrypt pacing: 30fps playback of the sampled TTE frames."""


class HubScreen(Screen[None]):
    """Blood Neon Void menu: banner, selectable list, wallet, key hints."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#hub-hint { dock: bottom; width: 1fr; height: 1; color: #24AEEB; "
        "text-align: center; }\n"
        "#hub-center { height: 1fr; }\n"
        "#hub-middle { width: 1fr; align-horizontal: center; }\n"
        "#hub-column { width: 1fr; height: auto; align: center middle; }\n"
        f"#hub-column {{ max-width: {HUB_COLUMN_MAX}; }}\n"
        "#hub-logo { width: 1fr; height: auto; text-align: center; }\n"
        "#hub-banner { width: 1fr; height: 3; color: #FF2A2A; "
        "text-style: bold; text-align: center; content-align: center middle; }\n"
        "#subtitle { width: 1fr; height: 1; color: #B57CFF; text-align: center; }\n"
        "#hub-header { width: 80%; height: 4; border: solid #952CF5; background: #12121e; }\n"
        "#gold { width: 1fr; height: 1; color: #FFD23F; text-style: bold; "
        "text-align: center; }\n"
        "#hub-greeting { width: 1fr; height: 1; color: #CACACA; text-align: center; }\n"
        "#hub-panel { width: 80%; height: 9; border: solid #952CF5; background: #12121e; }\n"
        "#hub-list { width: 1fr; height: 6; content-align: center middle; }\n"
        "#hub-message { width: 1fr; height: 1; color: #FFD23F; text-align: center; }\n"
        "#hub-stats { width: 1fr; height: 1; color: #FFD23F; text-align: center; }\n"
    )

    def __init__(self, app: TypeSurvivorsApp) -> None:
        """Hold the app link; every menu key delegates to one app method."""
        super().__init__()
        self._app_ref: TypeSurvivorsApp = app
        self._selected: int = 0

    @property
    def selected(self) -> int:
        """Highlighted menu row (tests drive it via j/k navigation)."""
        return self._selected % len(HUB_ENTRIES)

    @override
    def compose(self) -> ComposeResult:
        """Centered banner, header panel, menu panel, footer hint docked."""
        yield Label(
            "S start  P practice  R resume  H shop  E settings  Q quit",
            id="hub-hint",
        )
        with (
            Center(id="hub-center"),
            Middle(id="hub-middle"),
            Vertical(
                id="hub-column",
            ),
        ):
            yield Label(
                _hub_logo_text(_hub_logo_cells(self.size.height)),
                id="hub-logo",
            )
            yield Label(hub_banner_text(mono=not colors_enabled()), id="hub-banner")
            yield Label(TAGLINE, id="subtitle")
            with Center():
                with Vertical(id="hub-header"):
                    yield Label(f"gold {self._app_ref.profile.gold}", id="gold")
                    yield Label(
                        hub_greeting(
                            gold=self._app_ref.profile.gold,
                            runs=len(self._app_ref.profile.runs),
                        ),
                        id="hub-greeting",
                    )
            with Center():
                with Vertical(id="hub-panel"):
                    yield Label("", id="hub-list")
                    yield Label("", id="hub-message")
            yield Label(hub_footer(self._app_ref.profile), id="hub-stats")

    def on_mount(self) -> None:
        """Paint the list, pin any panic banner, then decrypt the tagline."""
        self._refresh_hub()
        if self._app_ref.profile.settings.sound_on:
            play_music_track(MusicTrack.MENU)
        if self._app_ref.crash_message is not None:
            self.show_crash(self._app_ref.crash_message)
        if self._app_ref.claim_hub_intro():
            self._play_decrypt()

    def on_unmount(self) -> None:
        """Stop menu music when leaving the hub screen."""
        stop_music_track()

    def show_crash(self, message: str) -> None:
        """Pin the panic banner: the error plus the resume-where-you-left-off hint."""
        self.query_one("#hub-message", Label).update(
            f"crashed: {message} — resume where you left off (R)",
        )

    def on_resize(self, _event: events.Resize) -> None:
        """Re-bake the logo so a resized hub keeps the column fitting."""
        for widget in self.query("#hub-logo"):
            if isinstance(widget, Label):
                widget.update(
                    _hub_logo_text(_hub_logo_cells(self.size.height)),
                )

    def _play_decrypt(self) -> None:
        """Glitch the subtitle in via TTE; the task yields so keys stay live."""

        async def _run() -> None:
            frames = await asyncio.to_thread(decrypt_frames, TAGLINE)
            mono = not colors_enabled()
            for frame in frames:
                if not self.is_mounted:
                    return
                styled = Text.from_ansi(frame).plain if mono else Text.from_ansi(frame)
                for widget in self.query("#subtitle"):
                    if isinstance(widget, Label):
                        widget.update(styled)
                await asyncio.sleep(_HUB_DECRYPT_STEP_S)

        _ = self.run_worker(_run(), exclusive=True)

    def _refresh_hub(self) -> None:
        """Repaint the highlighted menu row and the stats footer."""
        self.query_one("#hub-list", Label).update(
            hub_list_text(HUB_ENTRIES, self._selected, mono=not colors_enabled()),
        )
        for stats in self.query("#hub-stats"):
            if isinstance(stats, Label):
                stats.update(hub_footer(self._app_ref.profile))

    def _press(self, key: str) -> None:
        """Route one menu hotkey to its app navigation method."""
        match key:
            case "s":
                self._app_ref.start_run()
            case "p":
                self._app_ref.start_run(practice=True)
            case "r":
                if not self._app_ref.resume_run():
                    self.query_one("#hub-message", Label).update(
                        "no suspended run — start a fresh one",
                    )
            case "h":
                self._app_ref.open_shop()
            case "e":
                self._app_ref.open_settings()
            case "q":
                self._app_ref.exit()
            case _:
                return

    async def on_key(self, event: events.Key) -> None:
        """Route hotkeys; j/k move the highlight, enter activates it."""
        match event.key:
            case "j" | "down":
                self._selected = (self._selected + 1) % len(HUB_ENTRIES)
                self._refresh_hub()
            case "k" | "up":
                self._selected = (self._selected - 1) % len(HUB_ENTRIES)
                self._refresh_hub()
            case "enter":
                self._press(HUB_ENTRIES[self.selected].key.lower())
            case _:
                self._press(event.key)


class ShopScreen(Screen[None]):
    """Meta shop: number keys buy permanent perks, then return to arena."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; border: solid #952CF5; }\n"
        "#shop-title { color: #FF2A2A; text-style: bold; }\n"
        "#shop-gold { color: #FFD23F; text-style: bold; }\n"
        "#shop-message { height: 1; color: #FFD23F; }\n"
        "#shop-hint { color: #24AEEB; }\n"
    )

    def __init__(self, profile: Profile, app: TypeSurvivorsApp) -> None:
        """Snapshot the wallet; buys write back through the app."""
        super().__init__()
        self._profile: Profile = profile
        self._app_ref: TypeSurvivorsApp = app

    @property
    def profile(self) -> Profile:
        """Current wallet snapshot (tests read owned perks through this)."""
        return self._profile

    @override
    def compose(self) -> ComposeResult:
        """Title, wallet, one numbered row per catalog perk, key hint."""
        yield Label("VOID MARKET", id="shop-title")
        yield Label(f"gold {self._profile.gold}", id="shop-gold")
        for index, item in enumerate(SHOP_CATALOG, start=1):
            row = shop_row_text(
                item.name,
                item.price,
                item.blurb,
                owned=item.id in self._profile.shop,
            )
            yield Label(f"{index} {row}", id=f"shop-item-{index}")
        yield Label("", id="shop-message")
        yield Label(
            "1-3 buy and return to arena  Q back without buying",
            id="shop-hint",
        )

    async def on_key(self, event: events.Key) -> None:
        """Buy keys purchase and restart; Q leaves without buying."""
        if event.key == "q":
            _ = self._app_ref.pop_screen()
            return
        if event.key not in ("1", "2", "3"):
            return
        item = SHOP_CATALOG[int(event.key) - 1]
        try:
            bought = buy_item(self._profile, item.id)
        except ShopError as exc:
            self.query_one("#shop-message", Label).update(str(exc))
            return
        self._profile = bought
        self._app_ref.apply_profile(bought)
        self._app_ref.return_to_arena()


class SettingsScreen(Screen[None]):
    """Shell toggles: palette cycle plus sound/bold/shake switches."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; border: solid #952CF5; }\n"
        "#settings-title { color: #FF2A2A; text-style: bold; }\n"
        "#settings-gold { color: #FFD23F; text-style: bold; }\n"
        "#settings-rows { height: 4; }\n"
        "#settings-hint { color: #24AEEB; }\n"
    )

    def __init__(self, profile: Profile, app: TypeSurvivorsApp) -> None:
        """Snapshot the settings; toggles write back through the app."""
        super().__init__()
        self._profile: Profile = profile
        self._app_ref: TypeSurvivorsApp = app

    @override
    def compose(self) -> ComposeResult:
        """Title, wallet, current toggle values, and the key hint."""
        yield Label("RITUAL CIRCLE", id="settings-title")
        yield Label(f"gold {self._profile.gold}", id="settings-gold")
        yield Label(self._rows(), id="settings-rows")
        yield Label("P palette  S sound  B bold  K shake  Q back", id="settings-hint")

    def _rows(self) -> str:
        """Render the four toggle values as one multi-line label."""
        settings = self._profile.settings
        sound = "on" if settings.sound_on else "off"
        bold = "on" if settings.bold else "off"
        shake = "on" if settings.shake else "off"
        return (
            f"palette {settings.palette.value}\nsound {sound}\n"
            f"bold {bold}\nshake {shake}"
        )

    def _apply(self, profile: Profile) -> None:
        """Write toggles back and repaint the rows."""
        self._profile = profile
        self._app_ref.apply_profile(profile)
        self.query_one("#settings-rows", Label).update(self._rows())

    async def on_key(self, event: events.Key) -> None:
        """Route one toggle keypress to its settings update."""
        settings = self._profile.settings
        match event.key:
            case "p":
                self._apply(
                    update_settings(
                        self._profile,
                        palette=next_palette(settings.palette),
                    ),
                )
            case "s":
                self._apply(
                    update_settings(self._profile, sound_on=not settings.sound_on),
                )
            case "b":
                self._apply(
                    update_settings(self._profile, bold=not settings.bold),
                )
            case "k":
                self._apply(
                    update_settings(self._profile, shake=not settings.shake),
                )
            case "q":
                _ = self._app_ref.pop_screen()
            case _:
                return


class TypeSurvivorsApp(App[None]):
    """Application root: hub menu entry, arena pushes, shared styling."""

    def __init__(  # noqa: PLR0913 - app config is one flat tested surface
        self,
        initial_words: tuple[str, ...] | None = None,
        initial_boss: str | None = None,
        *,
        spawn_enabled: bool = True,
        weak_keys: tuple[str, ...] = (),
        seed: int | None = None,
        profile: Profile | None = None,
        profile_dir: Path | None = None,
        start_at_hub: bool = False,
        resume: bool = False,
    ) -> None:
        """Configure the opening deal; live runs generate their own words."""
        super().__init__()
        if initial_words is None:
            self._initial_words: tuple[str, ...] = _default_words()
        else:
            self._initial_words = initial_words
        self._initial_boss: str | None = initial_boss
        self._spawn_enabled: bool = spawn_enabled
        self._weak_keys: tuple[str, ...] = weak_keys
        self._seed: int | None = seed
        if profile is None:
            self._profile: Profile = Profile(
                settings=Settings(sound_on=default_enabled()),
            )
        else:
            self._profile = profile
        self._profile_dir: Path | None = profile_dir
        self._start_at_hub: bool = start_at_hub
        self._resume: bool = resume
        self._hub_intro_played: bool = False
        self._crash_message: str | None = None

    @property
    def crash_message(self) -> str | None:
        """Last panic banner (the hub shows it until the next clean launch)."""
        return self._crash_message

    def claim_hub_intro(self) -> bool:
        """Consume the one-shot hub decrypt intro (True on the first call)."""
        if self._hub_intro_played:
            return False
        self._hub_intro_played = True
        return True

    @property
    def profile(self) -> Profile:
        """Current player profile (shop/settings write back through this)."""
        return self._profile

    def apply_profile(self, profile: Profile) -> None:
        """Replace the profile after a shop or settings write."""
        self._profile = profile

    def start_run(self, *, practice: bool = False) -> None:
        """Push a fresh arena (practice pins HP via the no-death tick)."""
        _ = self.push_screen(self._build_arena(practice=practice))

    def report_screen(self) -> ReportScreen:
        """Build the death recap card for the live arena tallies."""
        arena = self._live_arena()
        state = arena.arena_state
        accuracy = tally_accuracy(arena.tally)
        trail = arena.wpm_trail
        card = render_report(
            RunSummary(
                wpm_samples=trail,
                accuracy=accuracy,
                kills=state.kills,
                wave=state.wave,
                score=int(state.score),
                duration_s=arena.clock,
            ),
            killer=arena.killer,
        )
        return ReportScreen(
            score=int(state.score),
            kills=state.kills,
            wave=state.wave,
            card=card,
            app=self,
            wpm=trail,
            net=net_wpm(arena.hits, Seconds(arena.clock)),
            accuracy=accuracy,
            consistency=consistency(trail).value,
            best_streak=arena.best_streak,
        )

    def open_shop(self) -> None:
        """Push the meta shop over the current screen."""
        _ = self.push_screen(ShopScreen(self._profile, self))

    def open_settings(self) -> None:
        """Push the shell toggles over the current screen."""
        _ = self.push_screen(SettingsScreen(self._profile, self))

    def resume_run(self) -> bool:
        """Push a checkpoint-restored arena; False when none is saved."""
        if self._profile_dir is None:
            return False
        try:
            checkpoint = load_checkpoint(self._profile_dir)
        except CheckpointError:
            return False
        _ = self.push_screen(self._build_arena(state=restore(checkpoint)))
        return True

    def return_to_arena(self) -> None:
        """Pop back to the arena, pushing a fresh one when hub is below."""
        while len(self.screen_stack) > 1 and not isinstance(self.screen, ArenaScreen):
            _ = self.pop_screen()
        if not isinstance(self.screen, ArenaScreen):
            self.start_run()

    def retry_run(self) -> None:
        """Drop the recap and its dead arena, then deal a fresh run."""
        while len(self.screen_stack) > 1 and isinstance(
            self.screen,
            (ReportScreen, ArenaScreen),
        ):
            _ = self.pop_screen()
        self.start_run()

    def suspend_to_hub(self) -> None:
        """Drop screens down to the hub, pushing one when none is below."""
        while len(self.screen_stack) > 1 and not isinstance(self.screen, HubScreen):
            _ = self.pop_screen()
        if not isinstance(self.screen, HubScreen):
            _ = self.push_screen(HubScreen(self))

    def crash_to_hub(self, message: str) -> None:
        """Panic landing: keep the message, show the hub with its resume hint."""
        self._crash_message = message
        self.suspend_to_hub()
        screen = self.screen
        if isinstance(screen, HubScreen) and screen.is_mounted:
            screen.show_crash(message)

    def _live_arena(self) -> ArenaScreen:
        """Return the arena screen, assuming one is on the stack."""
        screen = self.screen
        if not isinstance(screen, ArenaScreen):
            msg = "report card needs a live arena below it"
            raise TypeError(msg)
        return screen

    def _build_arena(
        self,
        *,
        state: ArenaState | None = None,
        practice: bool = False,
    ) -> ArenaScreen:
        """Build an arena with the app config, optionally checkpoint-restored."""
        screen = ArenaScreen(
            initial_words=self._initial_words,
            initial_boss=self._initial_boss,
            app=self,
            spawn_enabled=self._spawn_enabled,
            weak_keys=self._weak_keys,
            seed=self._seed,
            practice=practice,
            checkpoint_dir=self._profile_dir,
        )
        if state is not None:
            screen.set_restored(state)
        return screen

    def on_mount(self) -> None:
        """Push the hub menu, or the arena (checkpoint-restored on resume)."""
        if self._start_at_hub:
            _ = self.push_screen(HubScreen(self))
            return
        state: ArenaState | None = None
        if self._resume and self._profile_dir is not None:
            try:
                state = restore(load_checkpoint(self._profile_dir))
            except CheckpointError:
                state = None
        _ = self.push_screen(self._build_arena(state=state))
