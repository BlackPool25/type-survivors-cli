"""Tests for arena state: kills, stun, shields, drops, boss waves, display."""

from __future__ import annotations

from typing import Final

from tsurv.arena import (
    LEAK_DAMAGE,
    EnemyKind,
    Score,
    advance,
    apply_pickup,
    boss_cleared,
    chain_lightning,
    clear_lock,
    corrupted_display,
    handle_keystroke,
    initial_arena,
    merge_window,
    roll_drop,
    spawn_enemy,
)
from tsurv.combat import (
    SHIELD_DURATION,
    SHIELD_STREAK_EVERY,
    STUN_DURATION,
    Keystroke,
    Kill,
    NoTarget,
    TypoStun,
)
from tsurv.items import BLOOD_VIAL_HEAL, FROST_VEIL_DURATION, ItemKind
from tsurv.reward import KILL_POINTS_PER_CHAR
from tsurv.words import Corruption, Tier, Word, WordText

_NOW = 100.0
_STEP = 1.0
_LONG_WINDOW = 50.0
_BELOW_RATE = 0.05
_ABOVE_RATE = 0.50
_CHAIN_ARCS: Final = 2


def _word(text: str, corruption: Corruption = Corruption.CLEAN) -> Word:
    """Build a T1 word with the given corruption stage."""
    return Word(text=WordText(text), tier=Tier.T1, corruption=corruption)


def test_typing_full_word_kills_and_scores() -> None:
    """Feeding a grunt's chars kills it, bumps kills/streak, raises score."""
    state = spawn_enemy(initial_arena(), _word("cat"))
    outcome: Keystroke = NoTarget()
    for index, char in enumerate("cat"):
        state, outcome = handle_keystroke(state, char, _NOW + float(index))
    assert isinstance(outcome, Kill)
    assert state.enemies == ()
    assert state.kills == 1
    assert state.streak == 1
    assert state.score > Score(0)


def test_wrong_char_after_lock_stuns() -> None:
    """A wrong char on a live lock jams the gun for 0.6s, streak reset."""
    state = spawn_enemy(initial_arena(), _word("cat"))
    state, _ = handle_keystroke(state, "c", _NOW)
    state, outcome = handle_keystroke(state, "x", _NOW + 1.0)
    assert isinstance(outcome, TypoStun)
    assert state.stunned_until == _NOW + _STEP + STUN_DURATION
    assert state.streak == 0


def test_keys_inside_stun_window_are_swallowed() -> None:
    """Keystrokes before stun_until keep the same window, no progress."""
    state = spawn_enemy(initial_arena(), _word("cat"))
    state, _ = handle_keystroke(state, "c", _NOW)
    state, _ = handle_keystroke(state, "x", _NOW + _STEP)
    stunned = state.stunned_until
    state, outcome = handle_keystroke(state, "a", _NOW + _STEP + 0.2)
    assert isinstance(outcome, TypoStun)
    assert state.stunned_until == stunned


def test_streak_eight_kill_produces_shield() -> None:
    """The arena is the shield_until producer: streak-x8 sets now+1.0."""
    state = initial_arena(streak=SHIELD_STREAK_EVERY - 1)
    state = spawn_enemy(state, _word("cat"))
    outcome = NoTarget()
    for index, char in enumerate("cat"):
        state, outcome = handle_keystroke(state, char, _NOW + float(index))
    assert isinstance(outcome, Kill)
    assert state.shield_until == _NOW + 2 * _STEP + SHIELD_DURATION


def test_shield_merge_never_clobbers_live_window() -> None:
    """A fresh streak shield max()-merges over a longer live shield."""
    state = initial_arena(
        streak=SHIELD_STREAK_EVERY - 1,
        shield_until=_NOW + _LONG_WINDOW,
    )
    state = spawn_enemy(state, _word("cat"))
    outcome = NoTarget()
    for index, char in enumerate("cat"):
        state, outcome = handle_keystroke(state, char, _NOW + float(index))
    assert isinstance(outcome, Kill)
    assert state.shield_until == _NOW + _LONG_WINDOW


def test_merge_window_takes_max() -> None:
    """Effect windows merge with max(): pickups never clear live effects."""
    assert merge_window(_LONG_WINDOW, FROST_VEIL_DURATION) == _LONG_WINDOW
    assert merge_window(0.0, FROST_VEIL_DURATION) == FROST_VEIL_DURATION
    assert merge_window(_STEP * 10.0, _STEP * 10.0) == _STEP * 10.0


def test_frost_pickup_merges_over_live_slow() -> None:
    """Frost Veil max()-merges: a live window survives a weaker pickup."""
    state = initial_arena(frost_until=_NOW + _LONG_WINDOW)
    after = apply_pickup(state, ItemKind.FROST_VEIL, _NOW)
    assert after.frost_until == _NOW + _LONG_WINDOW
    fresh = apply_pickup(initial_arena(), ItemKind.FROST_VEIL, _NOW)
    assert fresh.frost_until == _NOW + FROST_VEIL_DURATION


def test_blood_vial_heals_without_touching_windows() -> None:
    """Blood Vial heals 30 capped at max, leaving shield/frost at zero."""
    state = initial_arena(hp=40.0)
    after = apply_pickup(state, ItemKind.BLOOD_VIAL, _NOW)
    assert after.hp == 40.0 + BLOOD_VIAL_HEAL
    assert after.frost_until == 0.0
    assert after.shield_until == 0.0


def test_boss_drop_is_always_frost() -> None:
    """Every boss kill drops a Frost Veil, regardless of the roll."""
    assert roll_drop(EnemyKind.BOSS, _ABOVE_RATE) is ItemKind.FROST_VEIL
    assert roll_drop(EnemyKind.BOSS, 0.0) is ItemKind.FROST_VEIL


def test_elite_drop_is_chain_at_ten_percent() -> None:
    """Elites drop Chain Spark only below the 10% roll threshold."""
    assert roll_drop(EnemyKind.ELITE, _BELOW_RATE) is ItemKind.CHAIN_SPARK
    assert roll_drop(EnemyKind.ELITE, _ABOVE_RATE) is None
    assert roll_drop(EnemyKind.GRUNT, 0.0) is None


def test_nova_never_drops() -> None:
    """NOVA charges via nova_ready only; no roll combination yields it."""
    for kind in EnemyKind:
        for roll in (0.0, _BELOW_RATE, _ABOVE_RATE):
            drop = roll_drop(kind, roll)
            assert drop in (None, ItemKind.FROST_VEIL, ItemKind.CHAIN_SPARK)


def test_boss_wave_ends_on_kill() -> None:
    """A two-bar boss survives the first word, dies on the second."""
    state = initial_arena(boss_wave=True)
    state = spawn_enemy(
        state,
        _word("alpha"),
        kind=EnemyKind.BOSS,
        hp_words=2,
        distance=8.0,
    )
    assert boss_cleared(state) is False
    outcome = NoTarget()
    for index, char in enumerate("alpha"):
        state, outcome = handle_keystroke(state, char, _NOW + float(index))
    assert not isinstance(outcome, TypoStun)
    assert len(state.enemies) == 1
    assert state.enemies[0].hp_words == 1
    assert state.kills == 0
    assert boss_cleared(state) is False
    for index, char in enumerate("alpha"):
        state, _ = handle_keystroke(state, char, _NOW + 10.0 + float(index))
    assert state.enemies == ()
    assert state.kills == 1
    assert boss_cleared(state) is True


def test_boss_cleared_false_off_boss_waves() -> None:
    """Empty non-boss waves never report a boss clear."""
    assert boss_cleared(initial_arena()) is False


def test_corrupted_display_covers_ladder() -> None:
    """All four corruption stages render deterministically."""
    assert corrupted_display(_word("cat", Corruption.CLEAN)) == "cat"
    assert corrupted_display(_word("cat", Corruption.REVERSED)) == "tac"
    assert corrupted_display(_word("cat", Corruption.ROT13)) == "png"
    glitched = corrupted_display(_word("cat", Corruption.GLITCH))
    assert glitched != "cat"
    assert glitched == corrupted_display(_word("cat", Corruption.GLITCH))


def test_corrupted_rendering_is_display_only() -> None:
    """Lock/target/advance use raw words even when the render is reversed."""
    state = spawn_enemy(state=initial_arena(), word=_word("cat", Corruption.REVERSED))
    outcome = NoTarget()
    for index, char in enumerate("cat"):
        state, outcome = handle_keystroke(state, char, _NOW + float(index))
    assert isinstance(outcome, Kill)
    assert state.enemies == ()


def test_advance_moves_leaks_and_reports_ids() -> None:
    """Tick movement converges enemies; leaks cost HP and report foe ids."""
    state = spawn_enemy(initial_arena(), _word("cat"), distance=0.5)
    foe_id = state.enemies[0].id
    state, leaked = advance(state, 1.0)
    assert leaked == (foe_id,)
    assert state.enemies == ()
    assert state.hp == 100.0 - LEAK_DAMAGE
    assert state.current is None


def test_clear_lock_releases_target() -> None:
    """Esc drops the lock and typed progress, leaving foes untouched."""
    state = spawn_enemy(initial_arena(), _word("cat"))
    state, _ = handle_keystroke(state, "c", _NOW)
    assert state.current is not None
    cleared = clear_lock(state)
    assert cleared.current is None
    assert cleared.typed == 0
    assert len(cleared.enemies) == 1


def test_chain_lightning_arcs_to_nearest_others() -> None:
    """Chain Spark kills the two nearest foes past the typed one."""
    state = initial_arena()
    state = spawn_enemy(state, _word("aaa"), distance=7.0)
    state = spawn_enemy(state, _word("bbb"), distance=3.0)
    state = spawn_enemy(state, _word("ccc"), distance=5.0)
    typed_id = state.enemies[0].id
    after, zapped = chain_lightning(state, typed_id)
    assert zapped == _CHAIN_ARCS
    assert [str(foe.word.text) for foe in after.enemies] == ["aaa"]
    assert after.kills == _CHAIN_ARCS
    assert int(after.score) == (3 + 3) * KILL_POINTS_PER_CHAR


def test_chain_lightning_caps_at_two_arcs() -> None:
    """A fourth foe survives the arc cap."""
    state = initial_arena()
    for text in ("aaa", "bbb", "ccc", "ddd"):
        state = spawn_enemy(state, _word(text))
    after, zapped = chain_lightning(state, state.enemies[0].id)
    assert zapped == _CHAIN_ARCS
    assert len(after.enemies) == _CHAIN_ARCS
