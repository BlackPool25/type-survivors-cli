"""Textual arena: playable endless loop, two screens, pause flag, 60fps tick."""

from __future__ import annotations

import os
import random
import time
from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar, Final, assert_never, override

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
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
from tsurv.profile import Profile, RunSummary
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
    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#arena { height: 12; }\n"
        "#foes { height: 6; }\n"
        f"#bossbars {{ height: {MAX_BOSS_BARS}; }}\n"
        "#topbar { height: 1; color: #CACACA; }\n"
        "#typing { height: 1; color: #CACACA; }\n"
        "#stun { height: 1; color: #FFD23F; }\n"
        "#guard { height: 3; color: #FF2A2A; }\n"
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
        state = initial_arena(hp=_START_HP)
        for text in initial_words:
            state = spawn_enemy(
                state,
                Word(text=WordText(text), tier=Tier.T1),
                distance=5.0,
            )
        if initial_boss is not None:
            state = set_boss_wave(state, flag=True)
            state = spawn_enemy(
                state,
                Word(text=WordText(initial_boss), tier=Tier.T3),
                kind=EnemyKind.BOSS,
                hp_words=2,
                distance=8.0,
            )
        self._arena: ArenaState = state
        self._app_ref: TypeSurvivorsApp | None = app
        self._spawn_enabled: bool = spawn_enabled
        self._weak_keys: tuple[str, ...] = weak_keys
        self._rng: random.Random = random.Random(seed)  # noqa: S311 - gameplay RNG
        self._boss_sentences: set[str] = set()
        self.paused: bool = False
        self._practice: bool = practice
        self._checkpoint_dir: Path | None = checkpoint_dir
        self._run_clock: float = 0.0
        self.mono: bool = not colors_enabled()
        self._clock: float = 0.0
        self._wave_clock: float = 0.0
        self._kill_times: list[float] = []
        self._juice: JuiceState = JuiceState()
        self._presses: int = 0
        self._hits: int = 0
        self._killer: str | None = None
        self._foes_render: Text = Text("")
        self._boss_bars: list[ProgressBar] = [
            ProgressBar(total=1, show_bar=True, show_percentage=False)
            for _ in range(MAX_BOSS_BARS)
        ]

    @property
    def arena_state(self) -> ArenaState:
        """Current pure arena state (tests read score/foes through this)."""
        return self._arena

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
        """Header, fixed-height arena, typing line, flags, guard, death."""
        yield Label("", id="topbar")
        with Vertical(id="arena"):
            yield Label("", id="foes")
            with Vertical(id="bossbars"):
                yield from self._boss_bars
        yield Label("", id="typing")
        yield Label("", id="stun")
        yield Label("", id="guard")
        yield Label("", id="death")

    def on_mount(self) -> None:
        """First paint, viewport guard, then the 60fps tick."""
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
        self._refresh()

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
            return
        tier = Tier.T1 if self._arena.wave <= 1 else Tier.T2
        word = pick_word(tier, (), shown, weak_keys=self._weak_keys)
        kind = EnemyKind.GRUNT if len(shown) % 3 else EnemyKind.MITE
        self._arena = spawn_enemy(self._arena, word, kind=kind)

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
        """Repaint header, foes, boss bars, typing line, and flags."""
        state = self._arena
        now = time.monotonic()
        wpm = rolling_wpm(self._kill_times, now)
        accuracy = self._hits / self._presses if self._presses else 1.0
        vitals = f"HP {state.hp:.0f}  WPM {wpm:.0f}  x{state.streak}"
        if low_hp(state.hp, state.max_hp):
            vitals += " LOW"
        progress = f"wave {state.wave}  score {int(state.score)}  acc {accuracy:.0%}"
        self.query_one("#topbar", Label).update(Text(f"{vitals}  {progress}"))
        self._foes_render = self._foes_text()
        self.query_one("#foes", Label).update(self._foes_render)
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

    def _telegraph_warn(self, foe: ArenaEnemy) -> str:
        """Return the leak-warning marker for foes inside their 200ms window."""
        if telegraph_showing(seconds_to_impact(foe.kind, foe.distance), foe.kind):
            return "!"
        return ""

    def _foes_text(self) -> Text:
        """Foe lines: half-block sprite glyph plus word (typed prefix lit)."""
        state = self._arena
        text = Text()
        for index, foe in enumerate(state.enemies):
            if index:
                _ = text.append("\n")
            prefix = f"{sprite_text(foe.kind)}{self._telegraph_warn(foe)} "
            raw = str(foe.word.text)
            if (
                not self.mono
                and foe.id == state.current
                and 0 < state.typed <= len(raw)
            ):
                _ = text.append(prefix)
                _ = text.append(raw[: state.typed], style=HP_GREEN)
                _ = text.append(
                    raw[state.typed : state.typed + 1],
                    style=f"underline {GOLD_NEXT}",
                )
                _ = text.append(raw[state.typed + 1 :])
            else:
                # Mono strips color only: corruption still reads via glyphs.
                _ = text.append(prefix + corrupted_display(foe.word))
        return text

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
    """Blood Neon Void menu: start, practice, resume, shop, settings."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#title { color: #FF2A2A; text-style: bold; }\n"
        "#subtitle { color: #952CF5; }\n"
        "#gold { color: #FFD23F; text-style: bold; }\n"
        "#hub-message { height: 1; color: #FFD23F; }\n"
        "#hub-hint { color: #24AEEB; }\n"
    )

    def __init__(self, app: TypeSurvivorsApp) -> None:
        """Hold the app link; every menu key delegates to one app method."""
        super().__init__()
        self._app_ref: TypeSurvivorsApp = app

    @override
    def compose(self) -> ComposeResult:
        """Title, wallet, menu verbs, and the key hint."""
        yield Label("TYPE SURVIVORS", id="title")
        yield Label("type fast or be eaten by the void", id="subtitle")
        yield Label(f"gold {self._app_ref.profile.gold}", id="gold")
        yield Label("", id="hub-message")
        yield Label(
            "S start  P practice  R resume  H shop  E settings  Q quit",
            id="hub-hint",
        )

    async def on_key(self, event: events.Key) -> None:
        """Route one menu keypress to its app navigation method."""
        match event.key:
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


class ShopScreen(Screen[None]):
    """Meta shop: number keys buy permanent perks, then return to arena."""

    CSS: ClassVar[str] = (
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#shop-gold { color: #FFD23F; text-style: bold; }\n"
        "#shop-message { height: 1; color: #FF2A2A; }\n"
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
        """Wallet, one numbered row per catalog perk, and the key hint."""
        yield Label(f"gold {self._profile.gold}", id="shop-gold")
        for index, item in enumerate(SHOP_CATALOG, start=1):
            owned = "OWNED" if item.id in self._profile.shop else f"{item.price}g"
            yield Label(f"{index} {item.name} — {owned}", id=f"shop-item-{index}")
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
        "Screen { background: #0B0B12; color: #CACACA; }\n"
        "#settings-gold { color: #FFD23F; text-style: bold; }\n"
        "#settings-rows { height: 5; }\n"
        "#settings-hint { color: #24AEEB; }\n"
    )

    def __init__(self, profile: Profile, app: TypeSurvivorsApp) -> None:
        """Snapshot the settings; toggles write back through the app."""
        super().__init__()
        self._profile: Profile = profile
        self._app_ref: TypeSurvivorsApp = app

    @override
    def compose(self) -> ComposeResult:
        """Render the current toggle values plus the key hint."""
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
