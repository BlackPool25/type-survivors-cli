"""Pure word-selection engine: tier pools, spawn constraints, boss chunking."""

from __future__ import annotations

import secrets
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Final, NewType, TypedDict, assert_never

from pydantic import TypeAdapter

if TYPE_CHECKING:
    import random
    from collections.abc import Mapping, Sequence

_WORDS_DIR: Final = Path(str(resources.files("tsurv") / "words"))

WEAK_KEY_BOOST: Final = 3
"""Reweight factor for weak-key words: listed this often, never exclusively."""

REVIEW_BOOST: Final = 2
"""Extra multiplier for overdue-review weak keys (stacks with WEAK_KEY_BOOST)."""

_T1_MIN_LEN: Final = 3
_T1_MAX_LEN: Final = 5
_T2_MIN_LEN: Final = 5
_T2_MAX_LEN: Final = 8
_T3_MIN_LEN: Final = 9
_HISTORY_WINDOW: Final = 30
_MAX_SHARED_INITIALS: Final = 2

WordText = NewType("WordText", str)
"""A word safe to spawn: deduplicated, swear-filtered, non-empty."""

_SWEARS: Final = frozenset(
    {
        "anal",
        "asshole",
        "bastard",
        "bitch",
        "boob",
        "boobs",
        "cock",
        "cunt",
        "damn",
        "dick",
        "fuck",
        "hell",
        "nigger",
        "piss",
        "porn",
        "pussy",
        "sex",
        "sexy",
        "shit",
        "slut",
        "tit",
        "tits",
        "twat",
        "wank",
        "whore",
    },
)


class Tier(StrEnum):
    """Word difficulty tier: short, mid, long, code-biome, boss phrases."""

    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    CODE = "CODE"
    BOSS = "BOSS"


class Corruption(StrEnum):
    """Boss-bar corruption ladder stage for a word's display."""

    CLEAN = "CLEAN"
    REVERSED = "REVERSED"
    GLITCH = "GLITCH"
    ROT13 = "ROT13"


@dataclass(frozen=True, slots=True)
class Word:
    """A spawned word with its tier and corruption stage."""

    text: WordText
    tier: Tier
    corruption: Corruption = Corruption.CLEAN


class WordSelectionError(ValueError):
    """Raised when spawn constraints eliminate every candidate word."""


class _WordFile(TypedDict):
    words: list[str]


_WORD_FILE_ADAPTER: Final = TypeAdapter(_WordFile)


def _load_words(tier: Tier, filename: str) -> tuple[WordText, ...]:
    """Load a local word-list JSON file, deduplicated, order preserved."""
    try:
        text = (_WORDS_DIR / filename).read_text(encoding="utf-8")
        words = _WORD_FILE_ADAPTER.validate_json(text)["words"]
    except (OSError, ValueError) as exc:
        # ValueError covers ValidationError and non-UTF-8 bytes alike.
        msg = f"cannot load {tier.value} words from {filename}: {exc}"
        raise WordSelectionError(msg) from exc
    unique: list[WordText] = []
    seen: set[str] = set()
    for item in words:
        if item and item not in seen:
            seen.add(item)
            unique.append(WordText(item))
    return tuple(unique)


def _clean(pool: tuple[WordText, ...]) -> tuple[WordText, ...]:
    """Drop swear-list entries (case-insensitive) from a pool."""
    return tuple(word for word in pool if word.lower() not in _SWEARS)


def _dedupe(pool: tuple[WordText, ...]) -> tuple[WordText, ...]:
    """Drop repeats across files, order preserved."""
    return tuple(dict.fromkeys(pool))


_T1_POOL: Final = tuple(
    word
    for word in _clean(_load_words(Tier.T1, "english_1k.json"))
    if _T1_MIN_LEN <= len(word) <= _T1_MAX_LEN
)
_T2_POOL: Final = tuple(
    word
    for word in _clean(_load_words(Tier.T2, "english_5k.json"))
    if _T2_MIN_LEN <= len(word) <= _T2_MAX_LEN
)
_T3_POOL: Final = tuple(
    word
    for word in _clean(_load_words(Tier.T3, "english_10k.json"))
    if len(word) >= _T3_MIN_LEN
)
_CODE_POOL: Final = _dedupe(
    _clean(
        _load_words(Tier.CODE, "code_python.json")
        + _load_words(Tier.CODE, "code_javascript.json"),
    ),
)

# BOSS has no pool: boss words come only from chunk_boss_sentence pools.
TIER_WORDS: Final[Mapping[Tier, tuple[WordText, ...]]] = {
    Tier.T1: _T1_POOL,
    Tier.T2: _T2_POOL,
    Tier.T3: _T3_POOL,
    Tier.CODE: _CODE_POOL,
}


def _pool_for(tier: Tier) -> tuple[WordText, ...]:
    """Return the word pool for a tier (exhaustive over Tier)."""
    match tier:
        case Tier.T1:
            return _T1_POOL
        case Tier.T2:
            return _T2_POOL
        case Tier.T3:
            return _T3_POOL
        case Tier.CODE:
            return _CODE_POOL
        case Tier.BOSS:
            msg = "boss words come only from chunk_boss_sentence pools"
            raise WordSelectionError(msg)
        case _:
            assert_never(tier)


def chunk_boss_sentence(sentence: str) -> list[str]:
    """Split one boss sentence into word-by-word chunks, punctuation kept."""
    chunks = sentence.split()
    for chunk in chunks:
        if not chunk.isascii():
            msg = f"boss chunk is not typeable ASCII: {chunk!r}"
            raise WordSelectionError(msg)
    return chunks


def weak_hits(word: str, weak_keys: Sequence[str]) -> bool:
    """Report whether a word contains any of the player's weak-key letters."""
    lowered = word.lower()
    return any(key.lower() in lowered for key in weak_keys if key)


def reweight_for_weak_keys(
    candidates: Sequence[WordText],
    weak_keys: Sequence[str],
) -> tuple[WordText, ...]:
    """Bias a candidate pool toward weak-key words without ever excluding.

    Weak-key words appear WEAK_KEY_BOOST times as often; every other
    candidate stays eligible exactly once, so practice targets weak keys
    while normal spawns can still surface anything.
    """
    return reweight_for_review(candidates, weak_keys)


def reweight_for_review(
    candidates: Sequence[WordText],
    weak_keys: Sequence[str],
    overdue: Sequence[str] = (),
) -> tuple[WordText, ...]:
    """Bias toward weak keys, overdue-review keys most, never excluding anyone.

    Weak-key words appear WEAK_KEY_BOOST times as often; the overdue subset
    appears WEAK_KEY_BOOST * REVIEW_BOOST times. Every other candidate stays
    eligible exactly once.
    """
    if not weak_keys:
        return tuple(candidates)
    weak = tuple(word for word in candidates if weak_hits(str(word), weak_keys))
    if not weak or len(weak) == len(candidates):
        return tuple(candidates)
    rest = tuple(word for word in candidates if not weak_hits(str(word), weak_keys))
    if not overdue:
        return (*weak * WEAK_KEY_BOOST, *rest)
    hot = tuple(word for word in weak if weak_hits(str(word), overdue))
    if not hot or len(hot) == len(weak):
        return (*weak * WEAK_KEY_BOOST, *rest)
    cold = tuple(word for word in weak if not weak_hits(str(word), overdue))
    return (*hot * (WEAK_KEY_BOOST * REVIEW_BOOST), *cold * WEAK_KEY_BOOST, *rest)


def pick_word(  # noqa: PLR0913 - spawn needs tier/history/screen/weak/overdue/rng
    tier: Tier,
    history: Sequence[str],
    on_screen: Sequence[str],
    *,
    weak_keys: Sequence[str] = (),
    overdue_keys: Sequence[str] = (),
    rng: random.Random | None = None,
) -> Word:
    """Pick a random word for a tier honoring spawn constraints.

    Excludes words already on screen, words in the trailing 30 history
    entries, and initials already used twice on screen (the initials
    filter relaxes when it alone would empty the pool). Pass `rng` for a
    seeded, deterministic draw; without it the crypto source deals.
    """
    pool = _pool_for(tier)
    recent = set(history[-_HISTORY_WINDOW:])
    visible = set(on_screen)
    eligible = [word for word in pool if word not in visible and word not in recent]
    counts = Counter(word[0].lower() for word in on_screen if word)
    preferred = [
        word
        for word in eligible
        if counts.get(word[0].lower(), 0) < _MAX_SHARED_INITIALS
    ]
    candidates = preferred or eligible
    if not candidates:
        msg = f"no {tier.value} word satisfies spawn constraints"
        raise WordSelectionError(msg)
    weighted = reweight_for_review(tuple(candidates), weak_keys, overdue_keys)
    if rng is not None:
        return Word(text=rng.choice(weighted), tier=tier)
    return Word(text=secrets.choice(weighted), tier=tier)
