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
from tsurv.items import ItemKind
from tsurv.profile import Palette, Profile, atomic_write_text
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
    """One meta-shop line: one-time caches or capped escalating ranks."""

    id: str
    name: str
    price: int
    blurb: str
    max_rank: int = 1
    price_step: int = 0


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
    ShopItem(
        id="vitality",
        name="Vitality Mesh",
        price=100,
        blurb="+10 max hull per rank",
        max_rank=5,
        price_step=100,
    ),
    ShopItem(
        id="focus",
        name="Focus Lattice",
        price=150,
        blurb="shorter typo stuns per rank",
        max_rank=4,
        price_step=150,
    ),
    ShopItem(
        id="deep-chill",
        name="Deep Chill",
        price=120,
        blurb="+1s frost veil per rank",
        max_rank=3,
        price_step=140,
    ),
    ShopItem(
        id="greed",
        name="Greed Sigil",
        price=200,
        blurb="+1 gold per kill per rank",
        max_rank=3,
        price_step=200,
    ),
)

CACHE_ITEMS: Final[tuple[str, ...]] = ("blood-vial", "frost-veil", "second-wind")
"""One-time shop lines that grant a held starting item each run."""

CACHE_TO_KIND: Final[dict[str, ItemKind]] = {
    "blood-vial": ItemKind.BLOOD_VIAL,
    "frost-veil": ItemKind.FROST_VEIL,
    "second-wind": ItemKind.SECOND_WIND,
}
"""Cache line id to the held item it grants at run start."""

VITALITY_HP_PER_RANK: Final = 10
"""Max hull gained per vitality rank (100 -> 150 at cap)."""

FOCUS_STUN_RELIEF_PER_RANK: Final = 0.05
"""Typo-stun seconds shaved per focus rank (0.6s -> 0.4s at cap)."""

DEEP_CHILL_SECONDS_PER_RANK: Final = 1.0
"""Frost-veil seconds gained per deep-chill rank (+3s at cap)."""

GREED_GOLD_PER_RANK: Final = 1
"""Extra gold per kill per greed rank (5 -> 8 at cap)."""


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


def shop_rank(profile: Profile, item_id: str) -> int:
    """Owned rank of one shop line (0 when never bought)."""
    return profile.shop.get(item_id, 0)


def price_for(item: ShopItem, owned_rank: int) -> int:
    """Next-rank price: base plus one step per rank already owned."""
    if owned_rank < 0:
        msg = f"owned rank must be >= 0, got {owned_rank}"
        raise ShopError(msg)
    return item.price + item.price_step * owned_rank


def buy_item(profile: Profile, item_id: str) -> Profile:
    """Spend run gold on the next rank (capped, wallet must cover)."""
    item = shop_lookup(item_id)
    rank = shop_rank(profile, item_id)
    if rank >= item.max_rank:
        msg = f"shop item maxed out: {item_id!r}"
        raise ShopError(msg)
    price = price_for(item, rank)
    if profile.gold < price:
        msg = f"cannot afford {item_id!r}: costs {price}, wallet has {profile.gold}"
        raise ShopError(msg)
    return profile.model_copy(
        update={
            "gold": profile.gold - price,
            "shop": {**profile.shop, item.id: rank + 1},
        },
    )


def refund_all(profile: Profile) -> tuple[Profile, int]:
    """Full refund (VS-style): clear every rank, pay back exact spend."""
    total = 0
    for item in SHOP_CATALOG:
        rank = shop_rank(profile, item.id)
        total += sum(price_for(item, owned) for owned in range(rank))
    cleared = profile.model_copy(update={"gold": profile.gold + total, "shop": {}})
    return cleared, total


def bank_gold(
    profile: Profile,
    kills: int,
    waves: int,
    *,
    gold_per_kill: int = GOLD_PER_KILL,
) -> Profile:
    """Bank run earnings at the per-kill rate (greed raises it)."""
    if kills < 0 or waves < 0:
        msg = f"cannot bank negative earnings: kills={kills} waves={waves}"
        raise ShopError(msg)
    return profile.model_copy(
        update={"gold": profile.gold + kills * gold_per_kill + waves * GOLD_PER_WAVE},
    )


def starting_perks(profile: Profile) -> tuple[str, ...]:
    """Owned cache ids in catalog order: every run starts holding each."""
    return tuple(
        item.id
        for item in SHOP_CATALOG
        if item.id in CACHE_ITEMS and item.id in profile.shop
    )


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
    """Durably write the suspend file so a crash never corrupts it."""
    directory.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_text(
            directory / CHECKPOINT_FILENAME,
            checkpoint.model_dump_json(),
        )
    except OSError as exc:
        msg = f"cannot save checkpoint to {directory / CHECKPOINT_FILENAME}: {exc}"
        raise CheckpointError(msg) from exc


def clear_checkpoint(directory: Path) -> None:
    """Unlink the suspend file at run end; missing is a no-op (idempotent)."""
    try:
        _ = (directory / CHECKPOINT_FILENAME).unlink(missing_ok=True)
    except OSError as exc:
        msg = f"cannot clear checkpoint in {directory}: {exc}"
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
