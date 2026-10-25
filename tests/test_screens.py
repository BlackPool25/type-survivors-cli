"""Tests for shell screens: shop, settings, commands, checkpoint, practice."""

from __future__ import annotations

import asyncio
import random
from dataclasses import replace
from typing import TYPE_CHECKING, Final

import pytest
from textual.widgets import Label

from tsurv.app import (
    BOSS_EVERY,
    ArenaScreen,
    HubScreen,
    ReportScreen,
    SettingsScreen,
    ShopScreen,
    TypeSurvivorsApp,
    boss_word_text,
)
from tsurv.arena import (
    LEAK_DAMAGE,
    EnemyKind,
    Score,
    advance,
    boss_cleared,
    handle_keystroke,
    initial_arena,
    spawn_enemy,
)
from tsurv.grammar import GrammarError, generate_boss_sentence
from tsurv.profile import Palette, Profile, Settings
from tsurv.screens import (
    CHECKPOINT_FILENAME,
    GOLD_PER_KILL,
    GOLD_PER_WAVE,
    HELP_TEXT,
    SHOP_CATALOG,
    CheckpointError,
    ShellCommand,
    ShopError,
    bank_gold,
    buy_item,
    corruption_for_rank,
    describe,
    load_checkpoint,
    next_palette,
    parse_command,
    practice_advance,
    restore,
    save_checkpoint,
    shop_lookup,
    snapshot,
    starting_perks,
    update_settings,
)
from tsurv.words import (
    TIER_WORDS,
    WEAK_KEY_BOOST,
    Corruption,
    Tier,
    Word,
    WordText,
    reweight_for_weak_keys,
)

if TYPE_CHECKING:
    from pathlib import Path

_RICH: Final = 250
"""Gold wallet that affords any single catalog item."""
_WAVE_SEVEN: Final = 7
"""Checkpoint wave used by the suspend/resume round-trip."""
_CATALOG_COUNT: Final = 3
"""Permanent starting perks in the meta shop."""
_SNAP_SCORE: Final = 500
"""Score frozen by the checkpoint snapshot test."""
_SNAP_KILLS: Final = 9
"""Kill tally frozen by the checkpoint snapshot test."""
_BARS_RANK_ONE: Final = 3
"""Boss bars at wave 5 (2 + rank 1)."""
_BARS_RANK_TWO: Final = 4
"""Boss bars at wave 10 (2 + rank 2)."""
_GENERATION_ATTEMPTS: Final = 2
"""Pinned retry count (kept local: the source name is module-private)."""


def _word(text: str) -> Word:
    """Build a T1 word for arena/practice scenarios."""
    return Word(text=WordText(text), tier=Tier.T1)


def test_shop_catalog_prices_from_source() -> None:
    """Three permanent starting perks with positive distinct prices."""
    assert len(SHOP_CATALOG) == _CATALOG_COUNT
    prices = [item.price for item in SHOP_CATALOG]
    assert all(price > 0 for price in prices)
    assert len(set(prices)) == len(prices)
    assert shop_lookup(SHOP_CATALOG[0].id) == SHOP_CATALOG[0]


def test_buy_item_deducts_and_unlocks() -> None:
    """Buying deducts the catalog price and records the perk id."""
    item = SHOP_CATALOG[0]
    profile = Profile(gold=item.price)
    after = buy_item(profile, item.id)
    assert after.gold == 0
    assert starting_perks(after) == (item.id,)


def test_buy_item_rejects_unknown_owned_and_broke() -> None:
    """Unknown ids, duplicates, and short wallets raise ShopError."""
    item = SHOP_CATALOG[0]
    with pytest.raises(ShopError):
        _ = buy_item(Profile(gold=_RICH), "no-such-perk")
    owned = buy_item(Profile(gold=_RICH), item.id)
    with pytest.raises(ShopError):
        _ = buy_item(owned, item.id)
    with pytest.raises(ShopError):
        _ = buy_item(Profile(gold=item.price - 1), item.id)


def test_bank_gold_uses_tuning_constants() -> None:
    """Kills and waves bank gold at the source-pinned rates."""
    profile = bank_gold(Profile(), kills=2, waves=1)
    assert profile.gold == 2 * GOLD_PER_KILL + GOLD_PER_WAVE
    with pytest.raises(ShopError):
        _ = bank_gold(Profile(), kills=-1, waves=0)


def test_update_settings_only_touches_given_fields() -> None:
    """Settings updates replace named fields, leaving the rest alone."""
    profile = Profile()
    after = update_settings(profile, palette=Palette.TRITAN, sound_on=False)
    assert after.settings == Settings(palette=Palette.TRITAN, sound_on=False)
    assert update_settings(profile).settings == profile.settings


def test_next_palette_cycles_all_modes() -> None:
    """The palette switch walks all four colorblind-safe modes in a loop."""
    assert next_palette(Palette.STANDARD) is Palette.PROTAN
    assert next_palette(Palette.PROTAN) is Palette.DEUTAN
    assert next_palette(Palette.DEUTAN) is Palette.TRITAN
    assert next_palette(Palette.TRITAN) is Palette.STANDARD


def test_parse_command_routes_shell_verbs() -> None:
    """Slash and bare verbs route; anything else is UNKNOWN, never an error."""
    assert parse_command("/help") is ShellCommand.HELP
    assert parse_command("help") is ShellCommand.HELP
    assert parse_command("/quit") is ShellCommand.QUIT
    assert parse_command("/shop") is ShellCommand.SHOP
    assert parse_command("/settings") is ShellCommand.SETTINGS
    assert parse_command("/practice") is ShellCommand.PRACTICE
    assert parse_command("/resume") is ShellCommand.RESUME
    assert parse_command("/start") is ShellCommand.START
    assert parse_command("/bogus") is ShellCommand.UNKNOWN
    assert describe(ShellCommand.HELP) != describe(ShellCommand.QUIT)
    assert "/quit" in HELP_TEXT
    assert "/help" in HELP_TEXT


def test_corruption_ladder_pins_rank_mapping() -> None:
    """Boss ranks climb clean, reversed, glitch, then rot13 forever."""
    assert corruption_for_rank(1) is Corruption.CLEAN
    assert corruption_for_rank(2) is Corruption.REVERSED
    assert corruption_for_rank(3) is Corruption.GLITCH
    assert corruption_for_rank(4) is Corruption.ROT13
    assert corruption_for_rank(99) is Corruption.ROT13


def test_checkpoint_round_trip_restores_wave(tmp_path: Path) -> None:
    """Suspend writes the file; resume restores the exact wave and tallies."""
    state = replace(
        initial_arena(),
        wave=_WAVE_SEVEN,
        score=Score(_SNAP_SCORE),
        kills=_SNAP_KILLS,
    )
    save_checkpoint(tmp_path, snapshot(state))
    assert (tmp_path / CHECKPOINT_FILENAME).is_file()
    restored = restore(load_checkpoint(tmp_path))
    assert restored.wave == _WAVE_SEVEN
    assert int(restored.score) == _SNAP_SCORE
    assert restored.kills == _SNAP_KILLS
    assert restored.enemies == ()


def test_checkpoint_rejects_missing_and_corrupt(tmp_path: Path) -> None:
    """No silent defaults: missing or garbage checkpoints raise."""
    with pytest.raises(CheckpointError):
        _ = load_checkpoint(tmp_path)
    _ = (tmp_path / CHECKPOINT_FILENAME).write_text("{nope", encoding="utf-8")
    with pytest.raises(CheckpointError):
        _ = load_checkpoint(tmp_path)


def test_practice_mode_is_no_death() -> None:
    """Practice leaks remove foes and report ids, but HP never drops."""
    state = spawn_enemy(initial_arena(), _word("cat"), distance=0.5)
    foe_id = state.enemies[0].id
    after, leaked = practice_advance(state, 1.0)
    assert leaked == (foe_id,)
    assert after.hp == state.hp
    for _ in range(10):
        state = spawn_enemy(state, _word("cat"), distance=0.5)
        state, _ = practice_advance(state, 1.0)
    assert state.hp == initial_arena().hp


def test_real_advance_still_costs_hp() -> None:
    """The no-death pin is practice-only: real leaks cost LEAK_DAMAGE."""
    state = spawn_enemy(initial_arena(), _word("cat"), distance=0.5)
    after, _ = advance(state, 1.0)
    assert after.hp == 100.0 - LEAK_DAMAGE


def test_weak_key_words_weighted_more_never_exclusive() -> None:
    """Reweighting favors weak-key words while keeping the rest eligible."""
    assert WEAK_KEY_BOOST > 1
    candidates = (
        WordText("cat"),
        WordText("haze"),
        WordText("dog"),
        WordText("quiz"),
    )
    assert reweight_for_weak_keys(candidates, ()) == candidates
    biased = reweight_for_weak_keys(candidates, ("z",))
    assert biased.count(WordText("haze")) == WEAK_KEY_BOOST
    assert WordText("cat") in biased
    assert len(biased) == WEAK_KEY_BOOST * 2 + 2


def test_pilot_death_recap_shop_restart() -> None:
    """Death → R recap → S shop → buy key restarts on the arena in 3."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile=Profile(gold=_RICH),
        )
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            for _ in range(10):
                screen.spawn_test_enemy("zz", distance=0.05)
                screen.tick(5.0)
            await pilot.pause()
            assert screen.query_one("#death", Label).display is True
            await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, ReportScreen)
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, ShopScreen)
            await pilot.press("1")
            await pilot.pause()
            assert isinstance(app.screen, ArenaScreen)
            assert SHOP_CATALOG[0].id in app.profile.shop
            assert app.profile.gold == _RICH - SHOP_CATALOG[0].price

    asyncio.run(_scenario())


def test_boss_wave_spawns_single_multibar_foe() -> None:
    """Wave 5 deals exactly one BOSS foe holding all 3 bars."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=True, seed=1)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.set_restored(replace(initial_arena(), wave=BOSS_EVERY))
            for _ in range(20):
                screen.tick(0.5)
                if screen.arena_state.enemies:
                    break
            foes = screen.arena_state.enemies
            assert len(foes) == 1
            assert foes[0].kind is EnemyKind.BOSS
            assert foes[0].hp_words == _BARS_RANK_ONE
            assert len(str(foes[0].word.text).split(" ")) == _BARS_RANK_ONE

    asyncio.run(_scenario())


def test_multibar_burn_keeps_foe_alive_until_last_bar() -> None:
    """Each completed boss word burns one bar; only the last one kills."""
    text = "the swarm rises"
    state = spawn_enemy(
        initial_arena(boss_wave=True),
        Word(text=WordText(text), tier=Tier.T3),
        kind=EnemyKind.BOSS,
        hp_words=3,
        distance=8.0,
    )
    now = 0.0
    for bar in range(_BARS_RANK_ONE - 1):
        for char in text:
            now += 1.0
            state, _ = handle_keystroke(state, char, now)
        assert len(state.enemies) == 1
        assert state.enemies[0].hp_words == _BARS_RANK_ONE - 1 - bar
        assert state.kills == 0
        assert boss_cleared(state) is False
    for char in text:
        now += 1.0
        state, _ = handle_keystroke(state, char, now)
    assert state.enemies == ()
    assert state.kills == 1
    assert boss_cleared(state) is True


def _always_boom(*args: object, **kwargs: object) -> str:
    """Simulate an exhausted grammar space for the fallback path."""
    _ = (args, kwargs)
    msg = "grammar space exhausted"
    raise GrammarError(msg)


def test_boss_word_text_retries_grammar_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One GrammarError retries; the second attempt still deals bars."""
    real = generate_boss_sentence
    calls = 0

    def _flaky(
        rank: int,
        used: set[str],
        rng: random.Random,
        weak_keys: tuple[str, ...] = (),
    ) -> str:
        """Fail the first generation, then delegate to the real grammar."""
        nonlocal calls
        calls += 1
        if calls == 1:
            msg = "first attempt exhausted"
            raise GrammarError(msg)
        return real(rank, used, rng, weak_keys)

    monkeypatch.setattr("tsurv.app.generate_boss_sentence", _flaky)
    text, bars = boss_word_text(1, set(), random.Random(1), ())  # noqa: S311 - deterministic test RNG
    assert bars == _BARS_RANK_ONE
    assert len(text.split(" ")) == bars
    assert calls == _GENERATION_ATTEMPTS


def test_boss_word_text_falls_back_to_t3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two GrammarErrors fall back to the T3 list, still one foe's bars."""
    monkeypatch.setattr("tsurv.app.generate_boss_sentence", _always_boom)
    text, bars = boss_word_text(2, set(), random.Random(1), ())  # noqa: S311 - deterministic test RNG
    assert bars == _BARS_RANK_TWO
    chunks = text.split(" ")
    assert len(chunks) == bars
    pool = {str(word) for word in TIER_WORDS[Tier.T3]}
    assert all(chunk in pool for chunk in chunks)


def test_pilot_hub_shop_buy_returns_to_arena() -> None:
    """Hub → H shop → buy key purchases and restarts on the arena."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile=Profile(gold=_RICH),
            start_at_hub=True,
        )
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HubScreen)
            await pilot.press("h")
            await pilot.pause()
            assert isinstance(app.screen, ShopScreen)
            await pilot.press("1")
            await pilot.pause()
            assert isinstance(app.screen, ArenaScreen)
            assert SHOP_CATALOG[0].id in app.profile.shop
            assert app.profile.gold == _RICH - SHOP_CATALOG[0].price

    asyncio.run(_scenario())


def test_pilot_hub_settings_toggle_and_back() -> None:
    """Hub → E settings → P cycles the palette → Q returns to the hub."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            start_at_hub=True,
        )
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HubScreen)
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            await pilot.press("p")
            await pilot.pause()
            assert app.profile.settings.palette is Palette.PROTAN
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, HubScreen)

    asyncio.run(_scenario())


def test_pilot_hub_starts_runs() -> None:
    """Hub S starts a live run; P starts the no-death practice run."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            start_at_hub=True,
        )
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HubScreen)
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, ArenaScreen)

    async def _practice() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            start_at_hub=True,
        )
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.pause()
            assert isinstance(app.screen, ArenaScreen)

    asyncio.run(_scenario())
    asyncio.run(_practice())


def test_hub_shop_settings_reuse_blood_neon_void_palette() -> None:
    """Menu screens reuse the hub.tcss Blood Neon Void hexes by value."""
    for css in (HubScreen.CSS, ShopScreen.CSS, SettingsScreen.CSS):
        for hex_value in ("#0B0B12", "#CACACA", "#FFD23F"):
            assert hex_value in css
    assert "#FF2A2A" in HubScreen.CSS
    assert "#24AEEB" in HubScreen.CSS


def test_pilot_suspend_saves_and_resume_restores_wave(tmp_path: Path) -> None:
    """P then S suspends the wave; a resume launch restores its tallies."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile_dir=tmp_path,
        )
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, ArenaScreen)
            screen.set_restored(
                replace(
                    initial_arena(),
                    wave=_WAVE_SEVEN,
                    score=Score(_SNAP_SCORE),
                    kills=_SNAP_KILLS,
                ),
            )
            await pilot.press("P")
            assert screen.paused is True
            await pilot.press("S")
            await pilot.pause()
            assert (tmp_path / CHECKPOINT_FILENAME).is_file()

        resumed = TypeSurvivorsApp(
            initial_words=(),
            spawn_enabled=False,
            profile_dir=tmp_path,
            resume=True,
        )
        async with resumed.run_test() as pilot:
            await pilot.pause()
            screen = resumed.screen
            assert isinstance(screen, ArenaScreen)
            assert screen.arena_state.wave == _WAVE_SEVEN
            assert int(screen.arena_state.score) == _SNAP_SCORE
            assert screen.arena_state.kills == _SNAP_KILLS

    asyncio.run(_scenario())
