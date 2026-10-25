"""Shell layer: hub commands, meta shop, settings, checkpoints, practice.

Pure logic only: the arena screen owns pixels, this module owns the hub
verbs (/help, /quit, shop, settings, suspend/resume), the run-gold economy,
the no-death practice tick, and the boss corruption ladder.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, assert_never

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tsurv.arena import ArenaState, Score, advance, initial_arena
from tsurv.profile import Palette, Profile
from tsurv.words import Corruption

if TYPE_CHECKING:
    from pathlib import Path

    from tsurv.combat import EnemyId

GOLD_PER_KILL: Final = 5
"""Run gold banked per kill toward the meta shop."""

GOLD_PER_WAVE: Final = 25
"""Run gold banked per survived wave toward the meta shop."""

CHECKPOINT_FILENAME: Final = "checkpoint.json"
"""Suspend file inside the player data dir (one per profile)."""

_REVERSED_RANK: Final = 2
"""Boss rank speaking with reversed words."""

_GLITCH_RANK: Final = 3
"""Boss rank speaking with glitch-block words."""


@dataclass(frozen=True, slots=True)
class ShopItem:
    """One permanent starting perk: run gold buys it once, forever."""

    id: str
    name: str
    price: int
    blurb: str


SHOP_CATALOG: Final[tuple[ShopItem, ...]] = (
    ShopItem(
        id="blood-vial",
        name="Blood Vial Cache",
        price=100,
        blurb="begin every run holding a heal",
    ),
    ShopItem(
        id="frost-veil",
        name="Frost Veil Cache",
        price=150,
        blurb="begin every run holding a slow",
    ),
    ShopItem(
        id="second-wind",
        name="Second Wind Cache",
        price=200,
        blurb="begin every run holding a revive",
    ),
)


class ShopError(ValueError):
    """Raised for unknown, duplicate, or unaffordable shop purchases."""


class CheckpointError(ValueError):
    """Raised when a suspend checkpoint is missing or corrupt."""


class ShellCommand(StrEnum):
    """Hub verbs: slash commands plus their bare-word forms."""

    HELP = "HELP"
    QUIT = "QUIT"
    START = "START"
    PRACTICE = "PRACTICE"
    SHOP = "SHOP"
    SETTINGS = "SETTINGS"
    RESUME = "RESUME"
    UNKNOWN = "UNKNOWN"


_COMMAND_WORDS: Final[dict[str, ShellCommand]] = {
    "help": ShellCommand.HELP,
    "quit": ShellCommand.QUIT,
    "start": ShellCommand.START,
    "practice": ShellCommand.PRACTICE,
    "shop": ShellCommand.SHOP,
    "settings": ShellCommand.SETTINGS,
    "resume": ShellCommand.RESUME,
}

HELP_TEXT: Final = """commands: /start /practice /resume /shop /settings /help /quit
keys: type to kill, P pause, S suspend, R recap after death, Q arena"""


def parse_command(text: str) -> ShellCommand:
    """Route a hub line to its verb; anything else is UNKNOWN, never an error."""
    return _COMMAND_WORDS.get(
        text.strip().lower().removeprefix("/"),
        ShellCommand.UNKNOWN,
    )


def describe(command: ShellCommand) -> str:
    """One help line per hub verb (exhaustive over ShellCommand)."""
    match command:
        case ShellCommand.HELP:
            line = "/help — list hub commands and keys"
        case ShellCommand.QUIT:
            line = "/quit — bank earned gold and leave the run"
        case ShellCommand.START:
            line = "/start — begin a fresh endless run"
        case ShellCommand.PRACTICE:
            line = "/practice — no-death drill targeting your weakest keys"
        case ShellCommand.SHOP:
            line = "/shop — spend run gold on permanent starting perks"
        case ShellCommand.SETTINGS:
            line = "/settings — palette, sound, bold, shake"
        case ShellCommand.RESUME:
            line = "/resume — restore the suspended checkpoint wave"
        case ShellCommand.UNKNOWN:
            line = "unknown command — try /help"
        case _:
            assert_never(command)
    return line


def shop_lookup(item_id: str) -> ShopItem:
    """Fetch a catalog item by id, raising ShopError when unknown."""
    for item in SHOP_CATALOG:
        if item.id == item_id:
            return item
    msg = f"unknown shop item: {item_id!r}"
    raise ShopError(msg)


def buy_item(profile: Profile, item_id: str) -> Profile:
    """Spend run gold on a permanent perk (once each, wallet must cover)."""
    item = shop_lookup(item_id)
    if item.id in profile.shop:
        msg = f"shop item already owned: {item_id!r}"
        raise ShopError(msg)
    if profile.gold < item.price:
        msg = (
            f"cannot afford {item_id!r}: costs {item.price}, wallet has {profile.gold}"
        )
        raise ShopError(msg)
    return profile.model_copy(
        update={"gold": profile.gold - item.price, "shop": (*profile.shop, item.id)},
    )


def bank_gold(profile: Profile, kills: int, waves: int) -> Profile:
    """Bank run earnings at the pinned per-kill and per-wave rates."""
    if kills < 0 or waves < 0:
        msg = f"cannot bank negative earnings: kills={kills} waves={waves}"
        raise ShopError(msg)
    return profile.model_copy(
        update={"gold": profile.gold + kills * GOLD_PER_KILL + waves * GOLD_PER_WAVE},
    )


def starting_perks(profile: Profile) -> tuple[str, ...]:
    """Owned perk ids: every run starts holding each of these."""
    return profile.shop


def update_settings(
    profile: Profile,
    *,
    palette: Palette | None = None,
    sound_on: bool | None = None,
    bold: bool | None = None,
    shake: bool | None = None,
) -> Profile:
    """Replace only the named shell toggles, leaving the rest alone."""
    current = profile.settings
    return profile.model_copy(
        update={
            "settings": replace(
                current,
                palette=current.palette if palette is None else palette,
                sound_on=current.sound_on if sound_on is None else sound_on,
                bold=current.bold if bold is None else bold,
                shake=current.shake if shake is None else shake,
            ),
        },
    )


def next_palette(palette: Palette) -> Palette:
    """Cycle the colorblind-safe palette one step (exhaustive over Palette)."""
    match palette:
        case Palette.STANDARD:
            return Palette.PROTAN
        case Palette.PROTAN:
            return Palette.DEUTAN
        case Palette.DEUTAN:
            return Palette.TRITAN
        case Palette.TRITAN:
            return Palette.STANDARD
        case _:
            assert_never(palette)


def corruption_for_rank(rank: int) -> Corruption:
    """Boss corruption ladder: clean, reversed, glitch, then rot13 forever."""
    if rank <= 1:
        return Corruption.CLEAN
    if rank == _REVERSED_RANK:
        return Corruption.REVERSED
    if rank == _GLITCH_RANK:
        return Corruption.GLITCH
    return Corruption.ROT13


class Checkpoint(BaseModel):
    """Suspend boundary: the wave-start snapshot resume restores exactly."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    wave: int = Field(ge=1)
    score: int = Field(ge=0)
    kills: int = Field(ge=0)
    hp: float = Field(ge=0.0)
    streak: int = Field(ge=0)
    boss_wave: bool = False


def snapshot(state: ArenaState) -> Checkpoint:
    """Freeze the resumable tallies of a live arena (foes re-deal on resume)."""
    return Checkpoint(
        wave=state.wave,
        score=int(state.score),
        kills=state.kills,
        hp=state.hp,
        streak=state.streak,
        boss_wave=state.boss_wave,
    )


def restore(checkpoint: Checkpoint) -> ArenaState:
    """Rebuild an empty arena at the checkpoint wave with its tallies."""
    base = initial_arena(
        hp=checkpoint.hp,
        streak=checkpoint.streak,
        boss_wave=checkpoint.boss_wave,
    )
    return replace(
        base,
        wave=checkpoint.wave,
        score=Score(checkpoint.score),
        kills=checkpoint.kills,
    )


def save_checkpoint(directory: Path, checkpoint: Checkpoint) -> None:
    """Atomically write the suspend file so a crash never corrupts it."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CHECKPOINT_FILENAME
    tmp = path.with_name(f"{CHECKPOINT_FILENAME}.tmp")
    try:
        _ = tmp.write_text(checkpoint.model_dump_json(), encoding="utf-8")
        _ = tmp.replace(path)
    except OSError as exc:
        msg = f"cannot save checkpoint to {path}: {exc}"
        raise CheckpointError(msg) from exc


def load_checkpoint(directory: Path) -> Checkpoint:
    """Read the suspended wave; missing or corrupt files raise, never default."""
    path = directory / CHECKPOINT_FILENAME
    if not path.exists():
        msg = f"no checkpoint in {directory}"
        raise CheckpointError(msg)
    try:
        return Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        msg = f"cannot load checkpoint from {path}: {exc}"
        raise CheckpointError(msg) from exc


def practice_advance(
    state: ArenaState,
    dt: float,
) -> tuple[ArenaState, tuple[EnemyId, ...]]:
    """No-death drill tick: foes converge and leak, but HP never drops."""
    after, leaked = advance(state, dt)
    return replace(after, hp=max(after.hp, state.hp)), leaked
