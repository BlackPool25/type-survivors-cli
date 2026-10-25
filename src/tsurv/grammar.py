"""Generative boss-sentence grammar: Tracery-style templates + corpus lexicon.

Replaces the fixed T3-chunk placeholder: each boss wave speaks a fresh
sentence whose word count grows with boss rank. Slots draw from invasion
vocabulary plus curated corpus words; every sentence is ASCII-only, 4-14
words, and unique within a run via the caller-held `used` set.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from tsurv.words import TIER_WORDS, Tier

if TYPE_CHECKING:
    import random
    from collections.abc import Sequence

MIN_SENTENCE_WORDS: Final = 4
"""Shortest boss sentence: early bosses speak in short declaratives."""

MAX_SENTENCE_WORDS: Final = 14
"""Longest boss sentence: typed word-by-word, never a wall of text."""

MAX_ATTEMPTS: Final = 500
"""Uniqueness retries before admitting the well ran dry."""

WEAK_SLOT_BIAS: Final = 0.5
"""Chance a slot resolves from the weak-key subset when one exists."""

_MEDIUM_MAX_RANK: Final = 3
"""Highest boss rank speaking medium-length sentences."""


class GrammarError(ValueError):
    """Raised for invalid boss ranks or an exhausted sentence space."""


_NOUNS: Final = (
    "swarm",
    "void",
    "brood",
    "hive",
    "horde",
    "legion",
    "abyss",
    "fang",
    "claw",
    "night",
    "storm",
    "ash",
    "ruin",
    "maw",
    "haze",
    "shade",
    "thorn",
    "crypt",
    "plague",
    "wound",
)

_VERBS: Final = (
    "rises",
    "hungers",
    "stirs",
    "crawls",
    "burns",
    "howls",
    "wakes",
    "feeds",
    "breaks",
    "falls",
    "drifts",
    "seethes",
    "coils",
    "snaps",
    "wails",
    "rots",
)

_ADJECTIVES: Final = (
    "hollow",
    "endless",
    "hungry",
    "dark",
    "broken",
    "silent",
    "restless",
    "frozen",
    "savage",
    "pallid",
    "grim",
    "stark",
)

_PLACES: Final = (
    "below",
    "above",
    "within",
    "beyond",
    "behind",
    "beneath",
    "beside",
    "among",
)

CORPUS_WORDS: Final[tuple[str, ...]] = tuple(
    str(word)
    for word in (*TIER_WORDS[Tier.T1], *TIER_WORDS[Tier.T2])
    if str(word).islower() and str(word).isalpha()
)
"""Corpus slot filler: lowercase single-token words from the T1/T2 lists."""

_SLOTS: Final[dict[str, tuple[str, ...]]] = {
    "noun": _NOUNS,
    "verb": _VERBS,
    "adj": _ADJECTIVES,
    "place": _PLACES,
    "wild": CORPUS_WORDS,
}

_SLOT_PATTERN: Final = re.compile(r"\{(noun|verb|adj|place|wild)\}")

_SHORT_TEMPLATES: Final = (
    "the {noun} {verb} below",
    "the {adj} {noun} {verb}",
    "the {noun} {verb} the {noun}",
    "{noun} {verb} the {adj} {noun}",
    "we {verb} the {adj} {noun}",
    "hold the {noun} {verb} {place}",
)

_MEDIUM_TEMPLATES: Final = (
    "the {adj} {noun} {verb} while the {noun} {verb}",
    "{noun} {verb} {place} and {noun} {verb} {place}",
    "the {noun} {verb} the {wild} while {noun} {verb}",
    "beneath the {adj} {noun} the {noun} {verb} {place}",
    "we {verb} the {noun} but the {noun} {verb} {place}",
)

_LONG_TEMPLATES: Final = (
    "the {adj} {noun} {verb} {place} while the {adj} {noun} {verb} the {wild}",
    "{noun} {verb} {place} and the {noun} {verb} while {noun} {verb} {place}",
    "we {verb} the {adj} {noun} {place} but the {adj} {noun} still {verb}",
)


def templates_for_rank(rank: int) -> tuple[str, ...]:
    """Pick the template pool for a boss rank (short early, long late)."""
    if rank < 1:
        msg = f"boss rank starts at 1, got {rank}"
        raise GrammarError(msg)
    if rank <= 1:
        return _SHORT_TEMPLATES
    if rank <= _MEDIUM_MAX_RANK:
        return _MEDIUM_TEMPLATES
    return _LONG_TEMPLATES


def pick_slot(
    rng: random.Random,
    options: Sequence[str],
    weak_keys: Sequence[str] = (),
) -> str:
    """Resolve one slot, leaning toward weak-key words when hooked up."""
    if weak_keys:
        weak = [
            option
            for option in options
            if any(key.lower() in option.lower() for key in weak_keys if key)
        ]
        # The hook path spends one rng.random() before the choice, so the
        # hook-absent path below stays a single rng.choice: the pinned order.
        if weak and rng.random() < WEAK_SLOT_BIAS:
            return rng.choice(weak)
    return rng.choice(options)


def generate_boss_sentence(
    rank: int,
    used: set[str],
    rng: random.Random,
    weak_keys: Sequence[str] = (),
) -> str:
    """Generate a fresh boss sentence, tracking it in `used` for uniqueness."""
    templates = templates_for_rank(rank)
    for _ in range(MAX_ATTEMPTS):
        template = rng.choice(templates)
        sentence = _SLOT_PATTERN.sub(
            lambda match: pick_slot(rng, _SLOTS[match.group(1)], weak_keys),
            template,
        )
        words = sentence.split(" ")
        if not MIN_SENTENCE_WORDS <= len(words) <= MAX_SENTENCE_WORDS:
            continue
        if sentence in used:
            continue
        used.add(sentence)
        return sentence
    msg = f"boss sentence space exhausted at rank {rank}"
    raise GrammarError(msg)
