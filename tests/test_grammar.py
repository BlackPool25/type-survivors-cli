"""Tests for the generative boss-sentence grammar (templates + lexicon)."""

from __future__ import annotations

import random
from typing import Final

import pytest

from tsurv.grammar import (
    CORPUS_WORDS,
    MAX_SENTENCE_WORDS,
    MIN_SENTENCE_WORDS,
    GrammarError,
    generate_boss_sentence,
    pick_slot,
    templates_for_rank,
)

_SEED: Final = 20261025
_SAMPLES: Final = 200
_UNIQUE_RUN: Final = 50
_SLOT_OPTIONS: Final = ("swarm", "haze", "brood", "hive", "zap", "core", "maw", "ruin")


def _seeded(extra: int = 0) -> random.Random:
    """Fresh deterministic RNG for seeded generation checks (never crypto)."""
    return random.Random(_SEED + extra)  # noqa: S311 - deterministic test RNG


def test_rank_zero_rejected() -> None:
    """Boss ranks start at 1; zero and negatives raise GrammarError."""
    for rank in (0, -1):
        with pytest.raises(GrammarError, match="starts at 1"):
            _ = templates_for_rank(rank)


def test_templates_stay_within_word_bounds() -> None:
    """Every template yields 4-14 words since each slot is one word."""
    for rank in range(1, 7):
        for template in templates_for_rank(rank):
            count = len(template.split(" "))
            assert MIN_SENTENCE_WORDS <= count <= MAX_SENTENCE_WORDS


def test_determinism_under_seed() -> None:
    """The same seed and rank produce the same sentence twice."""
    first = generate_boss_sentence(2, set(), _seeded())
    second = generate_boss_sentence(2, set(), _seeded())
    assert first == second


def test_invariants_over_200_generations() -> None:
    """200 seeded sentences stay ASCII, 4-14 words, single-spaced."""
    rng = _seeded()
    used: set[str] = set()
    for index in range(_SAMPLES):
        sentence = generate_boss_sentence(index % 6 + 1, used, rng)
        words = sentence.split(" ")
        assert MIN_SENTENCE_WORDS <= len(words) <= MAX_SENTENCE_WORDS
        assert sentence.isascii()
        assert sentence == sentence.strip()
        assert "  " not in sentence


def test_complexity_grows_with_rank() -> None:
    """Late bosses speak longer sentences than the first boss on average."""
    early = [
        len(generate_boss_sentence(1, set(), _seeded(i)).split(" "))
        for i in range(_UNIQUE_RUN)
    ]
    late = [
        len(generate_boss_sentence(5, set(), _seeded(i)).split(" "))
        for i in range(_UNIQUE_RUN)
    ]
    assert sum(late) / len(late) > sum(early) / len(early)


def test_no_repeat_in_first_fifty() -> None:
    """The uniqueness guard yields 50 distinct sentences in one run."""
    rng = _seeded()
    used: set[str] = set()
    seen = [generate_boss_sentence(3, used, rng) for _ in range(_UNIQUE_RUN)]
    assert len(set(seen)) == _UNIQUE_RUN
    assert used == set(seen)


def test_weak_key_hook_biases_slot_picks() -> None:
    """Weak-letter slots surface more often with the hook, never exclusively."""
    rng = _seeded()
    plain = sum(1 for _ in range(_SAMPLES) if "z" in pick_slot(rng, _SLOT_OPTIONS))
    rng = _seeded()
    biased = 0
    saw_plain = False
    for _ in range(_SAMPLES):
        pick = pick_slot(rng, _SLOT_OPTIONS, ("z",))
        biased += 1 if "z" in pick else 0
        saw_plain = saw_plain or "z" not in pick
    assert biased > plain
    assert saw_plain


def test_corpus_slots_are_typeable_ascii() -> None:
    """Corpus slot words are ASCII single lowercase alpha tokens."""
    assert len(CORPUS_WORDS) > 0
    for word in CORPUS_WORDS:
        assert word.isascii()
        assert word.isalpha()
        assert word == word.lower()
