"""Textual arena: playable endless loop, two screens, pause flag, 60fps tick."""

from __future__ import annotations

import math
import os
import random
import time
from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar, Final, assert_never, override

from par_textual_image import TerminalImage
from PIL import Image
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Label, ProgressBar

from tsurv.arena import (
    ArenaEnemy,
    ArenaState,
    EnemyKind,
    advance,
    apply_pickup,
    boss_cleared,
    chain_lightning,
    clear_lock,
    corrupted_display,
    handle_keystroke,
    initial_arena,
    mercy_spawn_factor,
    mercy_tier,
    roll_drop,
    seconds_to_impact,
    set_boss_wave,
    spawn_enemy,
)
from tsurv.combat import EnemyId, Kill, TypoStun, rolling_wpm, spawn_interval
from tsurv.grammar import GrammarError, generate_boss_sentence
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
from tsurv.profile import Profile, RunSummary, weak_keys_for_spawn
from tsurv.report import render_report
from tsurv.screens import (
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
from tsurv.visuals import (
    BOB_FPS,
    COMPACT_WIDTH,
    HUB_ENTRIES,
    agitated,
    agitated_mark,
    ambient_line,
    boss_portal_mark,
    core_sprite_file,
    foe_hit_showing,
    foe_mark,
    foe_plate_text,
    foe_sprite_file,
    fx_line,
    hub_banner_text,
    hub_greeting,
    hub_list_text,
    juice_overlay,
    portal_mark,
    radial_indent,
    shop_row_text,
    sprite_path,
    tier_pips,
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
    from pathlib import Path

    from textual import events

GUARD_WIDTH: Final = 80
"""Windows narrower than this show the guard screen instead of the arena."""

_sprite_cache: dict[str, Image.Image] = {}
"""Loaded sprite art, cached so TerminalImage never holds file handles open."""


def sprite_image(filename: str) -> Image.Image | None:
    """Load sprite bytes once, cached; None when the asset file is missing."""
    if filename not in _sprite_cache:
        path = sprite_path(filename)
        if not path.is_file():
            return None
        with Image.open(path) as handle:
            pic = handle.convert("RGBA")
            _ = pic.load()
        _sprite_cache[filename] = pic
    return _sprite_cache[filename]


MAX_BOSS_BARS: Final = 6
"""Stacked ProgressBar pool; boss HP above this clamps the display."""


MAX_FOES: Final = 8
"""On-screen enemy cap, bounding layout and difficulty."""

REF_WPM: Final = 40.0
"""Reference WPM for adaptive spawn pacing."""

WAVE_SECONDS: Final = 30.0
"""Timed waves: survive the clock for a checkpoint and breather."""

BOSS_EVERY: Final = 5
"""Boss wave cadence (boss waves end on kill, not on the clock)."""

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


def true_pixel_available() -> bool:
    """Capability probe gating true-pixel TerminalImage rendering."""
    return os.environ.get("TSURV_TRUEPIXEL") == "1"


def is_narrow(width: int) -> bool:
    """Guard predicate: windows under 80 cols cannot host the arena."""
    return width < GUARD_WIDTH


def sprite_text(kind: EnemyKind, frame: int = 0) -> str:
    """Half-block fallback sprite: glyph per kind, never color-only identity.

    True-pixel TerminalImage renders only behind true_pixel_available();
    this deterministic string is the first display path everywhere else.
    """
    match kind:
        case EnemyKind.GRUNT:
            glyph = "▛█▜"
        case EnemyKind.MITE:
            glyph = "▄█▄"
        case EnemyKind.HEX:
            glyph = "█▄█"
        case EnemyKind.ELITE:
            glyph = "▀█▀"
        case EnemyKind.BOSS:
            glyph = "██████"
        case _:
            assert_never(kind)
    bob = "" if frame % 2 == 0 else " "
    return f"{glyph}{bob}"


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

    _HALF_FOES: ClassVar[int] = 4
    """Half the foe slots hang below the core: the ring reads above and below."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#topbar { width: 1fr; height: 3; border: solid #952CF5; color: #CACACA; }\n"
        "#arena { height: 1fr; border: solid #952CF5; }\n"
        "#foes { height: 1fr; }\n"
        "#foes-above { height: 1fr; }\n"
        "#foes-below { height: 1fr; }\n"
        ".foe-row { height: 3; }\n"
        ".foe-row TerminalImage { width: 10; height: 3; }\n"
        ".foe-word { width: 1fr; height: 3; content-align: left middle; }\n"
        "#core-row { height: 4; align: center middle; }\n"
        "#core-row TerminalImage { width: 12; height: 4; }\n"
        "#bossbanner { width: 1fr; height: 2; color: #FF2A2A; "
        "text-style: bold; text-align: center; }\n"
        f"#bossbars {{ height: {MAX_BOSS_BARS}; }}\n"
        "#fx { width: 1fr; height: 1; color: #FFD23F; }\n"
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
        self._presses: int = 0
        self._hits: int = 0
        self._killer: str | None = None
        self._foes_render: Text = Text("")
        self._boss_bars: list[ProgressBar] = [
            ProgressBar(total=1, show_bar=True, show_percentage=False)
            for _ in range(MAX_BOSS_BARS)
        ]
        self._last_wave: int = state.wave
        self._boss_banner_until: float = 0.0
        self._advance_until: float = 0.0
        self._drift_until: float = 0.0

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
        """Plain-text foe listing (display renderings, one per line)."""
        return self._foes_render.plain

    @property
    def foes_span_count(self) -> int:
        """Style span count on the foe text (zero exactly when mono)."""
        return len(self._foes_render.spans)

    @property
    def stun_visible(self) -> bool:
        """Whether the typo gun-jam flag is currently shown."""
        return self.query_one("#stun", Label).display

    @property
    def hits(self) -> int:
        """Correct keypresses this run (feeds the recap accuracy)."""
        return self._hits

    @property
    def presses(self) -> int:
        """Total keypresses this run (feeds the recap accuracy)."""
        return self._presses

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
        """Header, foe sprite+word rows, core, boss bars, fx, typing, flags."""
        yield Label("", id="topbar")
        yield Label("", id="bossbanner")
        with Vertical(id="arena"):
            with Vertical(id="foes"):
                with Vertical(id="foes-above"):
                    for index in range(self._HALF_FOES):
                        with Horizontal(id=f"foe-row-{index}", classes="foe-row"):
                            yield TerminalImage(id=f"foe-sprite-{index}")
                            yield Label("", id=f"foe-word-{index}", classes="foe-word")
                with Horizontal(id="core-row"):
                    yield TerminalImage(id="core-sprite")
                with Vertical(id="foes-below"):
                    for index in range(self._HALF_FOES, MAX_FOES):
                        with Horizontal(id=f"foe-row-{index}", classes="foe-row"):
                            yield TerminalImage(id=f"foe-sprite-{index}")
                            yield Label("", id=f"foe-word-{index}", classes="foe-word")
            with Vertical(id="bossbars"):
                yield from self._boss_bars
        yield Label("", id="fx")
        yield Label("", id="typing")
        yield Label("", id="stun")
        yield Label("widen to 80+ columns to play", id="guard")
        yield Label("", id="death")

    def on_mount(self) -> None:
        """First paint, mosaic fallback, viewport guard, then the 60fps tick."""
        if not true_pixel_available():
            for widget in self.query(TerminalImage):
                widget.force_protocol("halfblock")
        self._refresh()
        self.check_viewport()
        _ = self.set_interval(1 / 60, self._tick)

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
        """Advance movement, leaks, waves, and spawns (pause/death gate it)."""
        if self.paused or self._arena.hp <= 0.0:
            return
        self._juice = step_juice(self._juice, dt)
        if self._juice.frozen_at(time.monotonic()):
            self._refresh()
            return
        now = time.monotonic()
        dt *= time_scale(self._juice, now)
        self._run_clock += dt
        if self._practice:
            self._arena, leaked = practice_advance(self._arena, dt)
        else:
            self._arena, leaked = advance(self._arena, dt)
        if leaked:
            self._killer = leaked[0]
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
        elif self._wave_clock >= WAVE_SECONDS:
            self._arena = replace(self._arena, wave=self._arena.wave + 1)
            self._wave_clock = 0.0
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
                distance=8.0,
            )
            self._arena = self._place_last(self._arena)
            now = time.monotonic()
            self._boss_banner_until = now + self._BOSS_BANNER_S
            self._juice = replace(self._juice, trauma=1.0)
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
        self._arena = spawn_enemy(self._arena, word, kind=kind)
        self._arena = self._place_last(self._arena)

    async def on_key(self, event: events.Key) -> None:
        """Type-to-target: printable chars feed the arena, P pauses."""
        ch = event.character
        if event.key == "escape":
            self._arena = clear_lock(self._arena)
            self._refresh()
            return
        if ch is None or self._handle_command_key(ch):
            return
        if is_narrow(self.size.width):
            return
        now = time.monotonic()
        self._presses += 1
        before = self._arena
        state, outcome = handle_keystroke(before, ch, now)
        self._arena = state
        if isinstance(outcome, Kill):
            self._hits += 1
            self._kill_times.append(now)
            self._resolve_drop(before, outcome.target)
            self._juice_hit(before, outcome, now)
        elif not isinstance(outcome, TypoStun):
            self._hits += 1
        self._refresh()

    def _handle_command_key(self, ch: str) -> bool:
        """Pause, suspend, and death-recap keys; True when fully handled."""
        if ch == "P" and (self.paused or not self._expects_upper_p()):
            self.paused = not self.paused
            self._refresh()
            return True
        if self.paused:
            if ch == "S":
                self._suspend()
            return True
        if len(ch) != 1 or not ch.isprintable():
            return True
        if self._arena.hp <= 0.0:
            if ch == "r" and self._app_ref is not None:
                _ = self._app_ref.push_screen(self._app_ref.report_screen())
            return True
        return False

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
        if is_bar_break(foe.kind, foe.hp_words):
            self._juice = trigger_bar_break(self._juice, now, self._rng)
        else:
            self._juice = trigger_kill(self._juice, outcome.streak, now)

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
            self._arena, _ = chain_lightning(self._arena, foe.id)

    def _refresh(self) -> None:
        """Repaint header, sprites, foes, fx ribbon, boss bars, flags."""
        state = self._arena
        now = time.monotonic()
        overlay = juice_overlay(self._juice, now)
        frame_tick = int(self._run_clock * BOB_FPS)
        compact = self.size.width < COMPACT_WIDTH
        hit = foe_hit_showing(self._juice, now)
        wpm = rolling_wpm(self._kill_times, now)
        accuracy = self._hits / self._presses if self._presses else 1.0
        vitals = f"HP {state.hp:.0f}  WPM {wpm:.0f}  x{state.streak}"
        if low_hp(state.hp, state.max_hp):
            vitals += " LOW"
        if overlay.slow:
            vitals += " SLO-MO"
        progress = f"wave {state.wave}  score {int(state.score)}  acc {accuracy:.0%}"
        self.query_one("#topbar", Label).update(Text(f"{vitals}  {progress}"))
        if state.wave != self._last_wave:
            self._last_wave = state.wave
            self._advance_until = now + self._ADVANCE_S
            self._drift_until = now + self._ADVANCE_DRIFT_S
        banner = self.query_one("#bossbanner", Label)
        banner.update(Text(self.boss_banner_text))
        banner.display = self.boss_banner_text != ""
        self._foes_render = self._foes_text(
            frame_tick,
            now,
            self._drift_scroll(now),
            compact=compact,
            shake=overlay.shake,
        )
        self._refresh_foe_rows(
            frame_tick,
            now,
            self._drift_scroll(now),
            compact=compact,
            shake=overlay.shake,
            hit=hit,
        )
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

    def _foe_line(  # noqa: PLR0913 - one foe row needs its full render context
        self,
        foe: ArenaEnemy,
        frame_tick: int = 0,
        now: float = 0.0,
        scroll: int = 0,
        *,
        compact: bool = False,
        shake: int = 0,
    ) -> Text:
        """One foe row: ring indent, sprite, plate (pips + word + mark).

        Portal foes show the spawn glyph while scaling in; agitated foes
        (inside ``AGITATED_DISTANCE``) bob double-time with a warning mark
        and a red plate. The typed-lock highlight survives on the word.
        """
        text = Text()
        raw = str(foe.word.text)
        agit = agitated(foe.distance)
        rate = 2 if agit else 1
        glyph = sprite_text(foe.kind, frame_tick * rate)
        width = max(self.size.width, 1)
        plate = foe_plate_text(
            raw,
            kind=foe.kind,
            tier=foe.word.tier,
            corruption=foe.word.corruption,
            hp_words=foe.hp_words,
        )
        indent = radial_indent(
            angle=foe.angle,
            distance=foe.distance,
            width=width,
            plate_len=len(glyph) + 1 + len(plate),
            compact=compact,
            scroll=scroll,
        )
        spawned = self._spawned_at.get(foe.id, 0.0)
        prefix = f"{' ' * shake}{indent}"
        if now - spawned < self._PORTAL_S:
            ring = boss_portal_mark() if foe.kind is EnemyKind.BOSS else portal_mark()
            prefix += f"{ring}{self._telegraph_warn(foe)} "
        else:
            prefix += f"{glyph}{' ' if frame_tick % 2 else ''}"
            if agit:
                prefix += agitated_mark()
            prefix += self._telegraph_warn(foe)
            prefix += " "
        state = self._arena
        locked = foe.id == state.current and 0 < state.typed <= len(raw)
        if self.mono or not locked:
            # Mono strips color only: pips and marks still read via glyphs.
            globe = corrupted_display(foe.word)
            replated = foe_plate_text(
                globe,
                kind=foe.kind,
                tier=foe.word.tier,
                corruption=foe.word.corruption,
                hp_words=foe.hp_words,
            )
            if agit and not self.mono:
                _ = text.append(prefix)
                _ = text.append(replated, style="bold #FF2A2A")
            else:
                _ = text.append(prefix + replated)
            return text
        head = "●" * (
            foe.hp_words if foe.kind is EnemyKind.BOSS else tier_pips(foe.word.tier)
        )
        _ = text.append(f"{prefix}{head} " if head else prefix)
        _ = text.append(raw[: state.typed], style=HP_GREEN)
        _ = text.append(
            raw[state.typed : state.typed + 1],
            style=f"underline {GOLD_NEXT}",
        )
        _ = text.append(raw[state.typed + 1 :])
        _ = text.append(f" {foe_mark(foe.kind, foe.word.corruption)}")
        return text

    def _foes_text(
        self,
        frame_tick: int = 0,
        now: float = 0.0,
        scroll: int = 0,
        *,
        compact: bool = False,
        shake: int = 0,
    ) -> Text:
        """Aggregate foe lines (plain-text path; live rows paint each line)."""
        text = Text()
        for index, foe in enumerate(self._arena.enemies):
            if index:
                _ = text.append("\n")
            _ = text.append_text(
                self._foe_line(
                    foe,
                    frame_tick,
                    now,
                    scroll,
                    compact=compact,
                    shake=shake,
                ),
            )
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

    def _refresh_foe_rows(  # noqa: PLR0913 - row rebind needs the render context
        self,
        frame_tick: int,
        now: float,
        scroll: int,
        *,
        compact: bool,
        shake: int,
        hit: bool,
    ) -> None:
        """Bind one sprite+word row per foe; hidden rows release kitty ids.

        Setting ``image = None`` runs the renderer's cleanup, so pooled
        slots never hold stale true-pixel textures while hidden.
        """
        foes = self._arena.enemies
        self._set_sprite_image(
            self.query_one("#core-sprite", TerminalImage),
            core_sprite_file(
                hit=low_hp(self._arena.hp, self._arena.max_hp),
                tick=frame_tick,
            ),
        )
        live = {foe.id for foe in foes}
        self._spawned_at = {
            key: born for key, born in self._spawned_at.items() if key in live
        }
        for index in range(MAX_FOES):
            row = self.query_one(f"#foe-row-{index}", Horizontal)
            sprite = self.query_one(f"#foe-sprite-{index}", TerminalImage)
            if index >= len(foes):
                if row.display:
                    row.display = False
                    sprite.display = False
                    if sprite.image is not None:
                        sprite.image = None
                continue
            row.display = True
            self._set_sprite_image(
                sprite,
                foe_sprite_file(foes[index].kind, hit=hit, tick=frame_tick),
            )
            self.query_one(f"#foe-word-{index}", Label).update(
                self._foe_line(
                    foes[index],
                    frame_tick,
                    now,
                    scroll,
                    compact=compact,
                    shake=shake,
                ),
            )

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


class ReportScreen(Screen[None]):
    """Post-run recap card: tallies plus S for shop, Q back to the arena."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#report-card { height: 6; }\n"
        "#report-hint { height: 1; color: #952CF5; }\n"
    )

    def __init__(
        self,
        score: int,
        kills: int,
        wave: int,
        *,
        card: str = "",
        app: TypeSurvivorsApp | None = None,
    ) -> None:
        """Snapshot the run tallies; the app link powers S/Q navigation."""
        super().__init__()
        self._score: int = score
        self._kills: int = kills
        self._wave: int = wave
        self._card: str = card
        self._app_ref: TypeSurvivorsApp | None = app

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

    @override
    def compose(self) -> ComposeResult:
        """Tallies, the recap card, and the S/Q hint."""
        yield Label(self.score_line, id="report-score")
        yield Label(self.kills_line, id="report-kills")
        yield Label(self.wave_line, id="report-wave")
        yield Label(self._card, id="report-card")
        yield Label("S shop  Q back to arena", id="report-hint")

    async def on_key(self, event: events.Key) -> None:
        """S detours to the shop; Q restarts back on the arena."""
        if self._app_ref is None:
            return
        if event.key == "s":
            self._app_ref.open_shop()
        elif event.key == "q":
            self._app_ref.return_to_arena()


class HubScreen(Screen[None]):
    """Blood Neon Void menu: banner, selectable list, wallet, key hints."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#hub-hint { dock: bottom; width: 1fr; height: 1; color: #24AEEB; "
        "text-align: center; }\n"
        "#hub-center { height: 1fr; }\n"
        "#hub-column { width: 1fr; height: auto; align: center middle; }\n"
        "#hub-banner { width: 1fr; height: 3; color: #FF2A2A; "
        "text-style: bold; text-align: center; }\n"
        "#subtitle { width: 1fr; height: 1; color: #B57CFF; text-align: center; }\n"
        "#hub-header { width: 80%; height: 4; border: solid #952CF5; }\n"
        "#gold { width: 1fr; height: 1; color: #FFD23F; text-style: bold; "
        "text-align: center; }\n"
        "#hub-greeting { width: 1fr; height: 1; color: #CACACA; text-align: center; }\n"
        "#hub-panel { width: 80%; height: 9; border: solid #952CF5; }\n"
        "#hub-list { width: 1fr; height: 6; }\n"
        "#hub-message { width: 1fr; height: 1; color: #FFD23F; }\n"
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
            yield Label(hub_banner_text(mono=not colors_enabled()), id="hub-banner")
            yield Label("type fast or be eaten by the void", id="subtitle")
            with Vertical(id="hub-header"):
                yield Label(f"gold {self._app_ref.profile.gold}", id="gold")
                yield Label(
                    hub_greeting(
                        gold=self._app_ref.profile.gold,
                        runs=len(self._app_ref.profile.runs),
                    ),
                    id="hub-greeting",
                )
            with Vertical(id="hub-panel"):
                yield Label("", id="hub-list")
                yield Label("", id="hub-message")

    def on_mount(self) -> None:
        """Paint the selectable list once the widgets exist."""
        self._refresh_hub()

    def _refresh_hub(self) -> None:
        """Repaint the highlighted menu row."""
        self.query_one("#hub-list", Label).update(
            hub_list_text(HUB_ENTRIES, self._selected, mono=not colors_enabled()),
        )

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
        self._profile: Profile = profile if profile is not None else Profile()
        self._profile_dir: Path | None = profile_dir
        self._start_at_hub: bool = start_at_hub
        self._resume: bool = resume

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
        accuracy = arena.hits / arena.presses if arena.presses else 1.0
        card = render_report(
            RunSummary(
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
