"""Tests for the post-run report card (sparkline, weakest keys, trend)."""

from __future__ import annotations

from typing import Final

from tsurv.profile import KeyStat, RunSummary
from tsurv.report import (
    SPARK_LEVELS,
    render_report,
    sparkline,
    trend_delta,
    weakest_keys,
)

_WPM: tuple[float, ...] = (10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0)
"""Fixed WPM series spanning the full sparkline range."""

_RUN_SCORE: Final = 1800
"""Score of the fixture run (history averages 1500, so the delta is +300)."""

_EXPECTED_DELTA: Final = 300
"""Pinned trend delta: fixture score minus history mean."""


def _per_key() -> dict[str, KeyStat]:
    """Provide three pressed keys with a strict weakest-first order."""
    return {
        "a": KeyStat(presses=10, correct=9, total_time=1.0),
        "q": KeyStat(presses=4, correct=1, total_time=1.2),
        "z": KeyStat(presses=2, correct=0, total_time=0.9),
    }


def _run() -> RunSummary:
    """Build a finished run over the fixed WPM series."""
    return RunSummary(
        wpm_samples=_WPM,
        accuracy=0.9,
        kills=12,
        wave=5,
        score=_RUN_SCORE,
        duration_s=120.0,
    )


def _history() -> tuple[RunSummary, ...]:
    """Provide two past runs averaging score 1500, so the delta is pinned."""
    base = _run()
    first = RunSummary(
        wpm_samples=(),
        accuracy=0.8,
        kills=8,
        wave=3,
        score=1000,
        duration_s=90.0,
    )
    second = RunSummary(
        wpm_samples=(),
        accuracy=0.85,
        kills=10,
        wave=4,
        score=2000,
        duration_s=100.0,
    )
    assert base.score == _RUN_SCORE
    return (first, second)


def test_sparkline_uses_all_seven_levels() -> None:
    """The fixed series maps one-to-one onto the seven block levels."""
    assert SPARK_LEVELS == "▁▂▃▄▅▆▇"
    assert sparkline(_WPM) == "▁▂▃▄▅▆▇"


def test_sparkline_empty_and_constant_series() -> None:
    """Empty samples render blank; a flat series renders the middle level."""
    assert sparkline(()) == ""
    assert sparkline((40.0, 40.0, 40.0)) == "▄▄▄"


def test_weakest_keys_order() -> None:
    """Weakest-first order is z (0%), q (25%), a (90%)."""
    assert weakest_keys(_per_key()) == ("z", "q", "a")


def test_weakest_keys_tiebreak_prefers_slower_key() -> None:
    """Equal accuracy sorts slower average time first, then alphabetically."""
    stats = {
        "n": KeyStat(presses=2, correct=1, total_time=0.2),
        "m": KeyStat(presses=2, correct=1, total_time=1.0),
    }
    assert weakest_keys(stats) == ("m", "n")


def test_weakest_keys_ignores_unpressed() -> None:
    """Keys with zero presses never appear, even with default accuracy."""
    stats = {**_per_key(), "e": KeyStat()}
    assert "e" not in weakest_keys(stats)


def test_trend_delta_vs_average() -> None:
    """Delta is run score minus the history mean; empty history is zero."""
    assert trend_delta(_run(), _history()) == _EXPECTED_DELTA
    assert trend_delta(_run(), ()) == 0


def test_render_report_pins_rows() -> None:
    """The card carries the sparkline, weakest row in order, and +300 trend."""
    text = render_report(_run(), _per_key(), _history(), killer="grunt")
    assert "▁▂▃▄▅▆▇" in text
    assert f"wave {_run().wave}" in text
    assert f"score {_run().score}" in text
    assert text.index("z (0%)") < text.index("q (25%)") < text.index("a (90%)")
    assert "+300" in text
    assert "grunt" in text


def test_render_report_without_history_or_keys() -> None:
    """Single-arg render still works: blank graph marker, no weakest row."""
    text = render_report(_run())
    assert "score 1800" in text
    assert "—" in text
