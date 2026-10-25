"""Tests for the pure word-selection engine (tiers, constraints, swear filter)."""

from pathlib import Path
from typing import Final, TypedDict

import pytest
from pydantic import TypeAdapter

from tsurv.words import (
    TIER_WORDS,
    Tier,
    Word,
    WordSelectionError,
    chunk_boss_sentence,
    pick_word,
)

_T1_MIN_LEN = 3
_T1_MAX_LEN = 5
_T2_MIN_LEN = 5
_T2_MAX_LEN = 8
_BOSS_MIN_LEN = 9
_HISTORY_WINDOW = 30
_SAMPLES = 50


class _WordFile(TypedDict):
    words: list[str]


_WORD_FILE_ADAPTER: Final = TypeAdapter(_WordFile)


def _file_words(name: str) -> set[str]:
    """Read the raw word set from a local word-list JSON file."""
    text = (Path(__file__).resolve().parent.parent / "words" / name).read_text(
        encoding="utf-8",
    )
    return set(_WORD_FILE_ADAPTER.validate_json(text)["words"])


def _pick_many(tier: Tier, count: int = _SAMPLES) -> list[str]:
    """Pick words with empty history/screen for band sampling."""
    return [pick_word(tier, (), ()).text for _ in range(count)]


def test_tier_members_are_pinned() -> None:
    """The Tier enum has exactly the four tiers the engine handles."""
    assert set(Tier) == {Tier.T1, Tier.T2, Tier.CODE, Tier.BOSS}


def test_t1_words_use_short_band() -> None:
    """T1 picks come from the 3-5 character band."""
    for text in _pick_many(Tier.T1):
        assert _T1_MIN_LEN <= len(text) <= _T1_MAX_LEN


def test_t2_words_use_mid_band() -> None:
    """T2 picks come from the 5-8 character band."""
    for text in _pick_many(Tier.T2):
        assert _T2_MIN_LEN <= len(text) <= _T2_MAX_LEN


def test_boss_words_use_long_band() -> None:
    """BOSS picks are 9+ characters from the 10k list."""
    for text in _pick_many(Tier.BOSS):
        assert len(text) >= _BOSS_MIN_LEN


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
    for tier in (Tier.T1, Tier.T2, Tier.BOSS):
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
