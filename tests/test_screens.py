"""Tests for shell screens: shop, settings, commands, checkpoint, practice."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Final

import pytest
from textual.widgets import Label

from tsurv.app import ArenaScreen, ReportScreen, TypeSurvivorsApp
from tsurv.arena import LEAK_DAMAGE, Score, advance, initial_arena, spawn_enemy
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
    """Practice leaks remove foes and name words, but HP never drops."""
    state = spawn_enemy(initial_arena(), _word("cat"), distance=0.5)
    after, leaked = practice_advance(state, 1.0)
    assert leaked == ("cat",)
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
    """Death → R recap → dismiss returns to the arena within 3 actions."""

    async def _scenario() -> None:
        app = TypeSurvivorsApp(initial_words=(), spawn_enabled=False)
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
            profile = buy_item(Profile(gold=_RICH), SHOP_CATALOG[0].id)
            assert starting_perks(profile) == (SHOP_CATALOG[0].id,)
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, ArenaScreen)

    asyncio.run(_scenario())
