"""Honest keystroke taxonomy: correct/incorrect/extra/missed + WPM + kogasa."""

from __future__ import annotations

from typing import Final

import pytest

from tsurv.combat import (
    Advanced,
    EnemyId,
    EnemyState,
    Kill,
    NoTarget,
    TypoStun,
    apply_keystroke,
)
from tsurv.metrics import (
    Seconds,
    Stroke,
    Tally,
    TypedWord,
    accuracy,
    consistency,
    leak_missed,
    net_chars,
    net_wpm,
    raw_wpm,
    tally_of,
)
from tsurv.words import Tier, Word, WordText

_MASH_PRESSES: Final = 20
_CAT_TYPED: Final = 1
_CAT_MISSED: Final = 3
_HELLO_CHARS: Final = 5
_MINUTE: Final = 60.0
_STEADY_WPM: Final = 60.0


def _enemies() -> tuple[EnemyState, ...]:
    """One grunt holding 'cat' (taxonomy tests drive real combat)."""
    return (
        EnemyState(
            id=EnemyId(0),
            word=Word(text=WordText("cat"), tier=Tier.T1),
            hp_words=1,
            distance=5.0,
        ),
    )


def test_notarget_mash_scores_zero() -> None:
    """Unmatched presses tally extra, never correct; accuracy reads 0.0."""
    tally = Tally()
    for _ in range(_MASH_PRESSES):
        outcome = apply_keystroke("z", _enemies(), None, 0, 0, 10.0, 0.0)
        assert isinstance(outcome, NoTarget)
        tally = tally.add(tally_of(outcome, locked=False))
    assert tally.correct == 0
    assert tally.extra == _MASH_PRESSES
    assert accuracy(tally.correct, tally.incorrect, tally.extra) == 0.0


def test_typo_while_locked_is_incorrect() -> None:
    """A wrong char on the locked foe stuns: incorrect, never extra."""
    outcome = apply_keystroke("x", _enemies(), EnemyId(0), 1, 0, 10.0, 0.0)
    assert isinstance(outcome, TypoStun)
    assert tally_of(outcome, locked=True) == Stroke.INCORRECT


def test_correct_keystroke_scores_correct() -> None:
    """Advance and Kill outcomes both tally as correct strokes."""
    assert (
        tally_of(Advanced(target=EnemyId(0), typed=1, streak=0), locked=True)
        is Stroke.CORRECT
    )
    assert (
        tally_of(Kill(target=EnemyId(0), streak=1, shield_until=0.0), locked=True)
        is Stroke.CORRECT
    )


def test_leak_records_missed() -> None:
    """A foe leaking with 3 untyped chars records 3 missed."""
    assert leak_missed("cat", 0) == _CAT_MISSED
    assert leak_missed("cat", _CAT_TYPED) == _CAT_MISSED - _CAT_TYPED
    tally = Tally().add_missed(leak_missed("cat", 0))
    assert tally.missed == _CAT_MISSED


def test_net_counts_only_clean_words() -> None:
    """A sloppy word ('helol', one error) contributes zero net chars."""
    sloppy = (TypedWord(text="helol", errors=1),)
    assert net_chars(sloppy) == 0
    assert net_chars((TypedWord(text="hello", errors=0),)) == _HELLO_CHARS
    assert net_wpm(net_chars(sloppy), Seconds(_MINUTE)) == 0.0
    assert raw_wpm(_HELLO_CHARS, Seconds(_MINUTE)) == pytest.approx(1.0)


def test_consistency_rough_under_10_samples() -> None:
    """Under 10 samples the value is None and flagged rough."""
    result = consistency((_STEADY_WPM,) * 9)
    assert result.rough is True
    assert result.value is None
    steady = consistency((_STEADY_WPM,) * 12)
    assert steady.rough is False
    assert steady.value == pytest.approx(100.0)
