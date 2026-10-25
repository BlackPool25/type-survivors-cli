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
    set_boss_wave,
    spawn_enemy,
)
from tsurv.combat import EnemyId, Kill, TypoStun, rolling_wpm, spawn_interval
from tsurv.words import Tier, Word, WordText, pick_word

if TYPE_CHECKING:
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
        case _ as other:
            if other is EnemyKind.BOSS:
                glyph = "██████"
            else:
                assert_never(other)
    bob = "" if frame % 2 == 0 else " "
    return f"{glyph}{bob}"


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

    def __init__(
        self,
        initial_words: tuple[str, ...] = ("cat",),
        initial_boss: str | None = None,
        app: App[None] | None = None,
        *,
        spawn_enabled: bool = True,
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
        self._app_ref: App[None] | None = app
        self._spawn_enabled: bool = spawn_enabled
        self.paused: bool = False
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
        state, leaked = advance(self._arena, dt)
        self._arena = state
        if leaked:
            self._killer = leaked[0]
            self._refresh()
            return
        now = time.monotonic()
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
        """Spawn one foe: boss bars on boss waves, tier words otherwise."""
        shown = [str(foe.word.text) for foe in self._arena.enemies]
        if self._arena.wave % BOSS_EVERY == 0 and not self._arena.boss_wave:
            self._arena = set_boss_wave(self._arena, flag=True)
            chunk = pick_word(Tier.T3, (), shown)
            # shortcut: boss bars reuse T1-T3 chunks until authored pools land.
            self._arena = spawn_enemy(
                self._arena,
                chunk,
                kind=EnemyKind.BOSS,
                hp_words=2 + self._arena.wave // BOSS_EVERY,
                distance=8.0,
            )
            return
        tier = Tier.T1 if self._arena.wave <= 1 else Tier.T2
        word = pick_word(tier, (), shown)
        kind = EnemyKind.GRUNT if len(shown) % 3 else EnemyKind.MITE
        self._arena = spawn_enemy(self._arena, word, kind=kind)

    async def on_key(self, event: events.Key) -> None:
        """Type-to-target: printable chars feed the arena, P pauses."""
        ch = event.character
        if event.key == "escape":
            self._arena = clear_lock(self._arena)
            self._refresh()
            return
        if ch is None:
            return
        if ch == "P" and (self.paused or not self._expects_upper_p()):
            self.paused = not self.paused
            self._refresh()
            return
        if self.paused or len(ch) != 1 or not ch.isprintable():
            return
        if self._arena.hp <= 0.0:
            if ch == "r" and self._app_ref is not None:
                _ = self._app_ref.push_screen(
                    ReportScreen(
                        score=int(self._arena.score),
                        kills=self._arena.kills,
                        wave=self._arena.wave,
                    ),
                )
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
        elif not isinstance(outcome, TypoStun):
            self._hits += 1
        self._refresh()

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

    def _foes_text(self) -> Text:
        """Foe lines: half-block sprite glyph plus word (typed prefix lit)."""
        state = self._arena
        text = Text()
        for index, foe in enumerate(state.enemies):
            if index:
                _ = text.append("\n")
            prefix = f"{sprite_text(foe.kind)} "
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
                shown = raw if self.mono else corrupted_display(foe.word)
                _ = text.append(prefix + shown)
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
    """Post-run report card: the second and only other screen."""

    def __init__(self, score: int, kills: int, wave: int) -> None:
        """Snapshot the run tallies for the report card."""
        super().__init__()
        self._score: int = score
        self._kills: int = kills
        self._wave: int = wave

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
        """Tallies plus a hint back to the arena."""
        yield Label(self.score_line, id="report-score")
        yield Label(self.kills_line, id="report-kills")
        yield Label(self.wave_line, id="report-wave")
        yield Label("press Q to return", id="report-hint")

    def on_key(self, _event: events.Key) -> None:
        """Any key returns to the arena screen."""
        _ = self.dismiss(None)


class TypeSurvivorsApp(App[None]):
    """Application root: pushes the arena and owns shared styling."""

    def __init__(
        self,
        initial_words: tuple[str, ...] | None = None,
        initial_boss: str | None = None,
        *,
        spawn_enabled: bool = True,
    ) -> None:
        """Configure the opening deal; live runs generate their own words."""
        super().__init__()
        if initial_words is None:
            self._initial_words: tuple[str, ...] = _default_words()
        else:
            self._initial_words = initial_words
        self._initial_boss: str | None = initial_boss
        self._spawn_enabled: bool = spawn_enabled

    def on_mount(self) -> None:
        """Push the one and only arena screen."""
        _ = self.push_screen(
            ArenaScreen(
                initial_words=self._initial_words,
                initial_boss=self._initial_boss,
                app=self,
                spawn_enabled=self._spawn_enabled,
            ),
        )
