"""Post-run report card: WPM sparkline, weakest keys, trend vs history."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from tsurv.profile import KeyStat, RunSummary

SPARK_LEVELS: Final = "▁▂▃▄▅▆▇"
"""Seven block levels for the WPM-over-time graph (PLAN.md §report card)."""

_MID_LEVEL: Final = "▄"
"""Flat series render: every sample sits on the middle level."""


def sparkline(samples: Sequence[float]) -> str:
    """Map a WPM series onto block levels, min-to-max (blank when empty)."""
    if not samples:
        return ""
    low = min(samples)
    high = max(samples)
    if high <= low:
        return _MID_LEVEL * len(samples)
    span = len(SPARK_LEVELS) - 1
    return "".join(
        SPARK_LEVELS[round((value - low) / (high - low) * span)] for value in samples
    )


def weakest_keys(
    per_key: Mapping[str, KeyStat],
    count: int = 3,
) -> tuple[str, ...]:
    """Weakest-first keys: lowest accuracy, then slowest, then alphabetical.

    Keys with zero presses never rank; coaching only targets typed keys.
    """
    ranked = sorted(
        (key for key, stat in per_key.items() if stat.presses > 0),
        key=lambda key: (
            per_key[key].accuracy,
            # Negated so slower averages sort first under the ascending sort.
            -(per_key[key].total_time / per_key[key].presses),
            key,
        ),
    )
    return tuple(ranked[: max(count, 0)])


def trend_delta(run: RunSummary, history: Sequence[RunSummary]) -> int:
    """Run score minus the mean history score (zero on a first run)."""
    if not history:
        return 0
    return run.score - round(sum(past.score for past in history) / len(history))


def render_report(
    run: RunSummary,
    per_key: Mapping[str, KeyStat] | None = None,
    history: Sequence[RunSummary] = (),
    killer: str | None = None,
) -> str:
    """Render the death recap card: tallies, graph, weakest row, trend."""
    stats: Mapping[str, KeyStat] = {} if per_key is None else per_key
    weak = weakest_keys(stats)
    weak_row = (
        "weakest: " + " ".join(f"{key} ({stats[key].accuracy:.0%})" for key in weak)
        if weak
        else "weakest: —"
    )
    graph = sparkline(run.wpm_samples) or "—"
    trend_row = (
        f"trend {trend_delta(run, history):+d} vs avg"
        if history
        else "trend — (first run)"
    )
    lines = [
        f"REPORT CARD — wave {run.wave} score {run.score}",
        f"wpm {graph}",
        f"accuracy {run.accuracy:.0%}  kills {run.kills}  time {run.duration_s:.0f}s",
        weak_row,
        trend_row,
        f"killer {killer}" if killer is not None else "killer —",
    ]
    return "\n".join(lines)
