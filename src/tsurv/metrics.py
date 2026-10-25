"""Honest keystroke taxonomy: correct/incorrect/extra/missed, WPM, consistency."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final, NewType, assert_never

from tsurv.combat import Advanced, Kill, NoTarget, TypoStun

if TYPE_CHECKING:
    from tsurv.combat import Keystroke

Seconds = NewType("Seconds", float)
"""Elapsed run time; non-positive spans report zero WPM, never crash."""

MIN_CONSISTENCY_SAMPLES: Final = 10
"""Kogasa needs this many per-second samples, else the value stays rough."""


class Stroke(StrEnum):
    """One classified keypress (Monkeytype model: extra/missed are honest)."""

    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"
    EXTRA = "EXTRA"
    MISSED = "MISSED"


@dataclass(frozen=True, slots=True)
class Tally:
    """Running stroke counters; `add` returns the next immutable tally."""

    correct: int = 0
    incorrect: int = 0
    extra: int = 0
    missed: int = 0

    def __post_init__(self) -> None:
        """Reject negative counters (a tally only ever grows)."""
        if min(self.correct, self.incorrect, self.extra, self.missed) < 0:
            msg = f"tally counters must be non-negative, got {self!r}"
            raise ValueError(msg)

    def add(self, stroke: Stroke) -> Tally:
        """Return the tally with one more stroke of this kind (exhaustive)."""
        match stroke:
            case Stroke.CORRECT:
                return replace(self, correct=self.correct + 1)
            case Stroke.INCORRECT:
                return replace(self, incorrect=self.incorrect + 1)
            case Stroke.EXTRA:
                return replace(self, extra=self.extra + 1)
            case Stroke.MISSED:
                return replace(self, missed=self.missed + 1)
            case _:
                assert_never(stroke)

    def add_missed(self, count: int) -> Tally:
        """Return the tally with `count` more missed chars (leak path)."""
        if count < 0:
            msg = f"missed count must be non-negative, got {count}"
            raise ValueError(msg)
        return replace(self, missed=self.missed + count)


def tally_of(outcome: Keystroke, locked: bool) -> Stroke:  # noqa: FBT001 - brief pins (outcome, locked)
    """Classify one combat outcome (NoTarget is extra, never a hit)."""
    match outcome:
        case Advanced() | Kill():
            return Stroke.CORRECT
        case TypoStun():
            return Stroke.INCORRECT if locked else Stroke.EXTRA
        case NoTarget():
            return Stroke.EXTRA
        case _:
            assert_never(outcome)


def accuracy(correct: int, incorrect: int, extra: int) -> float:
    """Share of presses that were correct; empty Denominators read 1.0."""
    if min(correct, incorrect, extra) < 0:
        msg = "accuracy counters must be non-negative"
        raise ValueError(msg)
    total = correct + incorrect + extra
    if total == 0:
        return 1.0
    return correct / total


def tally_accuracy(tally: Tally) -> float:
    """Accuracy straight from a tally (missed chars never dilute presses)."""
    return accuracy(tally.correct, tally.incorrect, tally.extra)


def raw_wpm(chars: int, seconds: Seconds) -> float:
    """All typed chars per minute (five chars to the word)."""
    if chars < 0:
        msg = f"char count must be non-negative, got {chars}"
        raise ValueError(msg)
    if seconds <= 0.0:
        return 0.0
    return (chars / 5.0) / (seconds / 60.0)


@dataclass(frozen=True, slots=True)
class TypedWord:
    """One finished word plus whether any of its chars needed a retry."""

    text: str
    errors: int = 0

    def __post_init__(self) -> None:
        """Reject negative error counts (errors only accumulate)."""
        if self.errors < 0:
            msg = f"error count must be non-negative, got {self.errors}"
            raise ValueError(msg)


def net_chars(words: tuple[TypedWord, ...]) -> int:
    """Chars from fully-clean words only (sloppy words contribute zero)."""
    return sum(len(word.text) for word in words if word.errors == 0)


def net_wpm(clean_chars: int, seconds: Seconds) -> float:
    """Clean-word chars per minute (fast-and-sloppy cannot pad this)."""
    return raw_wpm(clean_chars, seconds)


def leak_missed(word: str, typed: int) -> int:
    """Chars left untyped when a foe leaks (never negative on overtype)."""
    return max(len(word) - typed, 0)


@dataclass(frozen=True, slots=True)
class Consistency:
    """Kogasa score with its rough flag (<10 samples never reads confident)."""

    value: float | None
    rough: bool


def consistency(samples: tuple[float, ...]) -> Consistency:
    """Kogasa over per-second raw samples: 100*(1-tanh(cv+cv³/3+cv⁵/5))."""
    if len(samples) < MIN_CONSISTENCY_SAMPLES:
        return Consistency(value=None, rough=True)
    mean = statistics.fmean(samples)
    if mean <= 0.0:
        return Consistency(value=0.0, rough=False)
    cv = statistics.pstdev(samples) / mean
    kogasa = 100.0 * (1.0 - math.tanh(cv + cv**3 / 3.0 + cv**5 / 5.0))
    return Consistency(value=kogasa, rough=False)
