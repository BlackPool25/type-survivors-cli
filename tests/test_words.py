"""Tests for the pure word-selection engine (tiers, constraints, swear filter)."""

from __future__ import annotations

import importlib
import random
from pathlib import Path
from typing import Final, TypedDict

import pytest
from pydantic import TypeAdapter

from tsurv import words
from tsurv.words import (
    _WORDS_DIR,
    MAX_TARGET_LEN,
    MIN_TARGET_LEN,
    OPENING_MAX_LEN,
    OVERDUE_COST,
    TIER_WORDS,
    WEAK_KEY_COST,
    Tier,
    Word,
    WordSelectionError,
    WordText,
    chunk_boss_sentence,
    deal_score,
    deal_word,
    max_len_for_wave,
    pick_word,
    target_length,
    weak_hits,
    word_difficulty,
)

_T1_MIN_LEN = 3
_T1_MAX_LEN = 5
_T2_MIN_LEN = 5
_T2_MAX_LEN = 8
_T3_MIN_LEN = 9
_HISTORY_WINDOW = 30
_SAMPLES = 50


class _WordFile(TypedDict):
    words: list[str]


_WORD_FILE_ADAPTER: Final = TypeAdapter(_WordFile)


def _file_words(name: str) -> set[str]:
    """Read the raw word set from a packaged word-list JSON file."""
    text = (_WORDS_DIR / name).read_text(encoding="utf-8")
    return set(_WORD_FILE_ADAPTER.validate_json(text)["words"])


def _pick_many(tier: Tier, count: int = _SAMPLES) -> list[str]:
    """Pick words with empty history/screen for band sampling."""
    return [pick_word(tier, (), ()).text for _ in range(count)]


def test_tier_members_are_pinned() -> None:
    """The Tier enum has exactly the five tiers the engine handles."""
    assert set(Tier) == {Tier.T1, Tier.T2, Tier.T3, Tier.CODE, Tier.BOSS}


def test_t1_words_use_short_band() -> None:
    """T1 picks come from the 3-5 character band."""
    for text in _pick_many(Tier.T1):
        assert _T1_MIN_LEN <= len(text) <= _T1_MAX_LEN


def test_t2_words_use_mid_band() -> None:
    """T2 picks come from the 5-8 character band."""
    for text in _pick_many(Tier.T2):
        assert _T2_MIN_LEN <= len(text) <= _T2_MAX_LEN


def test_t3_words_use_long_band() -> None:
    """T3 picks are 9+ characters from the 10k list."""
    for text in _pick_many(Tier.T3):
        assert len(text) >= _T3_MIN_LEN


def test_boss_tier_has_no_pickable_pool() -> None:
    """BOSS words come only from chunk_boss_sentence over authored pools."""
    with pytest.raises(WordSelectionError, match="boss words come only"):
        _ = pick_word(Tier.BOSS, (), ())


def test_code_words_come_from_code_lists() -> None:
    """CODE picks are drawn from the code word files."""
    code = _file_words("code_python.json") | _file_words("code_javascript.json")
    for text in _pick_many(Tier.CODE):
        assert text in code


def test_picked_word_is_clean_by_default() -> None:
    """pick_word returns CLEAN corruption; the ladder applies it later."""
    assert pick_word(Tier.T1, (), ()).corruption == "CLEAN"


def test_no_repeat_within_last_thirty() -> None:
    """A pick never repeats a word from the trailing 30 history entries."""
    history: list[str] = []
    for _ in range(2 * _HISTORY_WINDOW):
        word: Word = pick_word(Tier.T1, history, ())
        assert word.text not in history[-_HISTORY_WINDOW:]
        history.append(word.text)


def test_word_never_already_on_screen() -> None:
    """A pick is never a word already visible on screen."""
    on_screen = ("about", "search", "other")
    for _ in range(_SAMPLES):
        assert pick_word(Tier.T2, (), on_screen).text not in on_screen


def test_max_two_shared_initials() -> None:
    """A pick avoids an initial already used twice on screen."""
    on_screen = ("snake", "storm", "about")
    for _ in range(_SAMPLES):
        assert not pick_word(Tier.T1, (), on_screen).text.startswith("s")


def test_swear_list_word_never_returned() -> None:
    """Known profanities present in the raw lists are never picked."""
    seen: set[str] = set()
    for tier in (Tier.T1, Tier.T2, Tier.T3):
        seen.update(_pick_many(tier, _SAMPLES))
    assert "damn" not in seen
    assert "hell" not in seen


def test_exhausted_pool_raises() -> None:
    """Covering the whole pool with on-screen words raises a clear error."""
    with pytest.raises(WordSelectionError, match="no T1 word"):
        _ = pick_word(Tier.T1, (), TIER_WORDS[Tier.T1])


def test_chunk_splits_sentence_into_words() -> None:
    """A boss sentence chunks word-by-word for per-bar battles."""
    assert chunk_boss_sentence("Type to survive the swarm") == [
        "Type",
        "to",
        "survive",
        "the",
        "swarm",
    ]


def test_chunk_keeps_punctuation_attached() -> None:
    """Punctuation stays on its word; nothing is lost or split off."""
    assert chunk_boss_sentence("Destroy the core, now!") == [
        "Destroy",
        "the",
        "core,",
        "now!",
    ]


def test_chunk_every_chunk_typeable_ascii() -> None:
    """Every chunk is non-empty plain ASCII with no whitespace."""
    chunks = chunk_boss_sentence("Hold the line!  Push forward.")
    assert chunks == ["Hold", "the", "line!", "Push", "forward."]
    for chunk in chunks:
        assert chunk
        assert chunk.isascii()
        assert not any(c.isspace() for c in chunk)


def test_chunk_empty_sentence_returns_empty() -> None:
    """Blank input chunks to nothing rather than raising."""
    assert chunk_boss_sentence("") == []
    assert chunk_boss_sentence("   ") == []


def test_word_older_than_thirty_is_eligible_again() -> None:
    """A word that fell out of the 30-entry window can be picked again."""
    pool = TIER_WORDS[Tier.T1]
    target = pool[0]
    rest = [word for word in pool if word != target]
    history = [target, *rest[:_HISTORY_WINDOW]]
    assert pick_word(Tier.T1, history, tuple(rest)).text == target


def test_initials_filter_relaxes_when_it_empties_pool() -> None:
    """When every remaining word shares a blocked initial, one is picked."""
    pool = TIER_WORDS[Tier.T1]
    on_screen = ("snake", "storm", *[word for word in pool if not word.startswith("s")])
    for _ in range(_SAMPLES):
        assert pick_word(Tier.T1, (), on_screen).text.startswith("s")


def test_exhausted_code_pool_raises() -> None:
    """Covering the whole CODE pool with on-screen words raises."""
    with pytest.raises(WordSelectionError, match="no CODE word"):
        _ = pick_word(Tier.CODE, (), TIER_WORDS[Tier.CODE])


def test_code_pool_is_deduplicated() -> None:
    """Tokens shared by both code files (e.g. assert) appear exactly once."""
    pool = TIER_WORDS[Tier.CODE]
    assert len(pool) == len(set(pool))
    assert sum(1 for word in pool if word == WordText("assert")) == 1


def test_chunk_non_ascii_raises() -> None:
    """Non-typeable chunks (em-dash, curly quotes, accents) are rejected."""
    with pytest.raises(WordSelectionError, match="typeable ASCII"):
        _ = chunk_boss_sentence("wait \u2014 what")
    with pytest.raises(WordSelectionError, match="typeable ASCII"):
        _ = chunk_boss_sentence("\u201chello\u201d")
    with pytest.raises(WordSelectionError, match="typeable ASCII"):
        _ = chunk_boss_sentence("caf\u00e9")


def test_broken_word_file_error_names_tier_and_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing or malformed word files raise naming the tier and filename."""
    real_validate = _WORD_FILE_ADAPTER.validate_json

    def _no_disk(*args: object, **kwargs: object) -> str:
        """Simulate an unreadable word file."""
        _ = (args, kwargs)
        msg = "disk gone"
        raise OSError(msg)

    def _bad_json(*args: object, **kwargs: object) -> _WordFile:
        """Simulate a malformed word file via the real validator."""
        _ = (args, kwargs)
        return real_validate("not json")

    def _bad_bytes(*args: object, **kwargs: object) -> str:
        """Simulate a non-UTF-8 word file (UnicodeDecodeError is a ValueError)."""
        _ = (args, kwargs)
        encoding = "utf-8"
        raise UnicodeDecodeError(encoding, b"\xff", 0, 1, "invalid start byte")

    def _expect_load_error(label: str) -> None:
        """Reload with broken I/O; the error must name the tier and file."""
        try:
            _ = importlib.reload(words)
        except words.WordSelectionError as exc:
            error = str(exc)
        else:
            pytest.fail("broken word file should raise")
        finally:
            monkeypatch.undo()
            _ = importlib.reload(words)
        assert label in error
        assert "english_1k.json" in error

    monkeypatch.setattr(Path, "read_text", _no_disk)
    _expect_load_error("T1")
    monkeypatch.setattr(Path, "read_text", _bad_bytes)
    _expect_load_error("T1")
    monkeypatch.setattr(TypeAdapter, "validate_json", _bad_json)
    _expect_load_error("T1")


_SEEDED_KEY: Final = "q"
"""Rare T1 letter for the seeded bias check (5 of 687 words)."""

_SEEDED_DRAWS: Final = 2000
"""Draw count pinning the weak-key bias distribution (verified 44 vs 9)."""

_SEED: Final = 7
"""Fixed RNG seed making the bias distribution deterministic."""

_MID_TARGET: Final = 8.0
"""Ability target for a 40 WPM typist (a fifth of pace)."""


def _seeded_draws(*, weak_keys: tuple[str, ...]) -> list[WordText]:
    """Draw words from a freshly seeded RNG (deterministic per seed)."""
    rng = random.Random(_SEED)  # noqa: S311 - deterministic test RNG
    return [
        pick_word(Tier.T1, (), (), weak_keys=weak_keys, rng=rng).text
        for _ in range(_SEEDED_DRAWS)
    ]


def test_pick_word_seeded_rng_is_deterministic() -> None:
    """The same seed and hook deal the identical word sequence twice."""
    assert _seeded_draws(weak_keys=(_SEEDED_KEY,)) == _seeded_draws(
        weak_keys=(_SEEDED_KEY,),
    )


def test_pick_word_seeded_rng_biases_weak_keys() -> None:
    """Seeded draws favor weak-key words while keeping the rest eligible."""
    hooked = _seeded_draws(weak_keys=(_SEEDED_KEY,))
    plain = _seeded_draws(weak_keys=())
    hooked_hits = sum(1 for word in hooked if weak_hits(str(word), (_SEEDED_KEY,)))
    plain_hits = sum(1 for word in plain if weak_hits(str(word), (_SEEDED_KEY,)))
    assert hooked_hits > plain_hits
    assert any(not weak_hits(str(word), (_SEEDED_KEY,)) for word in hooked)


def test_word_difficulty_counts_length_then_weak_keys() -> None:
    """Length is the base; weak and overdue hits add fixed costs."""
    assert word_difficulty("cat", (), ()) == len("cat")
    assert word_difficulty("zebra", ("z",), ()) == len("zebra") + WEAK_KEY_COST
    assert (
        word_difficulty("zebra", ("z",), ("z",))
        == len("zebra") + WEAK_KEY_COST + OVERDUE_COST
    )
    assert word_difficulty("zebra", ("q",), ()) == len("zebra")


def test_target_length_tracks_ability_with_caps() -> None:
    """Slow typists get short words; fast ones hit the pool ceiling."""
    assert target_length(15.0) == MIN_TARGET_LEN
    assert target_length(40.0) == _MID_TARGET
    assert target_length(200.0) == MAX_TARGET_LEN


def test_deal_score_trains_weak_when_calm_spares_when_strained() -> None:
    """Equal-length words split on weak hits by the strain signal."""
    calm_weak = deal_score("cat", 3.0, ("c",), (), 0.0)
    calm_clean = deal_score("bat", 3.0, ("c",), (), 0.0)
    assert calm_weak < calm_clean
    hot_weak = deal_score("cat", 3.0, ("c",), (), 1.0)
    hot_clean = deal_score("bat", 3.0, ("c",), (), 1.0)
    assert hot_weak > hot_clean


def test_deal_word_stays_near_ability() -> None:
    """Dealt words land within one char of the ability target."""
    slow = deal_word(
        Tier.T1,
        (),
        (),
        ability_wpm=15.0,
        rng=random.Random(_SEED),  # noqa: S311
    )
    assert abs(len(slow.text) - MIN_TARGET_LEN) <= 1
    mid = deal_word(
        Tier.T2,
        (),
        (),
        ability_wpm=40.0,
        rng=random.Random(_SEED),  # noqa: S311
    )
    assert abs(len(mid.text) - _MID_TARGET) <= 1


def test_deal_word_honors_opening_cap() -> None:
    """Wave-1 rails cap every dealt word at four characters."""
    for _ in range(20):
        word = deal_word(
            Tier.T1,
            (),
            (),
            ability_wpm=15.0,
            max_len=OPENING_MAX_LEN,
            rng=random.Random(),  # noqa: S311 - unseeded single draw
        )
        assert len(word.text) <= OPENING_MAX_LEN


def test_max_len_for_wave_rails_wave_one() -> None:
    """Wave 1 caps words at four letters; later waves run free."""
    assert max_len_for_wave(1) == OPENING_MAX_LEN
    assert max_len_for_wave(0) == OPENING_MAX_LEN
    assert max_len_for_wave(2) is None
