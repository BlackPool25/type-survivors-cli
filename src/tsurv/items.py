"""Pure item economy: heals, slows, revives, NOVA charge (no Textual imports)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, assert_never

BLOOD_VIAL_HEAL: Final = 30.0
"""HP restored by one Blood Vial, clamped to max."""

FROST_VEIL_DURATION: Final = 5.0
"""Slow window in seconds opened by one Frost Veil."""

SECOND_WIND_FRACTION: Final = 0.5
"""Max-HP fraction restored by the one Second Wind revive."""

NOVA_MIN_ACCURACY: Final = 0.95
"""Smoothed accuracy needed before NOVA can fire."""

NOVA_CHARGE_SECONDS: Final = 30.0
"""Charged seconds at or above accuracy needed before NOVA can fire."""


class ItemKind(StrEnum):
    """Typed-to-grab item pool (NOVA charges separately, it never drops)."""

    BLOOD_VIAL = "BLOOD_VIAL"
    SECOND_WIND = "SECOND_WIND"
    FROST_VEIL = "FROST_VEIL"
    CHAIN_SPARK = "CHAIN_SPARK"


class ItemError(ValueError):
    """Raised when item trigger inputs are out of range."""


@dataclass(frozen=True, slots=True)
class ActiveEffects:
    """Live effect windows as absolute now-based timestamps (0.0 = inactive)."""

    frost_until: float
    shield_until: float


@dataclass(frozen=True, slots=True)
class TriggerResult:
    """One item use resolved: new vitals plus absolute effect windows.

    Windows the item does not touch come back 0.0 (leave them alone);
    merge nonzero windows with max() so a use never clears a live effect.
    """

    hp: float
    frost_until: float
    shield_until: float
    revives_used: int
    consumed: bool


def _check_vitals(hp: float, max_hp: float, revives_used: int, now: float) -> None:
    """Reject out-of-range vitals (hp 0.0 is lethal, not invalid)."""
    if max_hp <= 0.0:
        msg = f"max_hp must be positive, got {max_hp}"
        raise ItemError(msg)
    if not 0.0 <= hp <= max_hp:
        msg = f"hp {hp} outside 0..max_hp {max_hp}"
        raise ItemError(msg)
    if revives_used < 0:
        msg = f"revives_used must be >= 0, got {revives_used}"
        raise ItemError(msg)
    if now < 0.0:
        msg = f"now must be >= 0.0, got {now}"
        raise ItemError(msg)


def trigger(  # noqa: PLR0913 - six explicit params per ruling
    item: ItemKind,
    hp: float,
    max_hp: float,
    revives_used: int,
    now: float,
    *,
    veil_bonus: float = 0.0,
) -> TriggerResult:
    """Resolve one typed item grab against narrow vitals (exhaustive over ItemKind).

    Blood Vial heals 30 capped at max; Frost Veil opens a 5s slow window
    plus deep-chill bonus seconds; Second Wind revives lethal damage once
    at half max; Chain Spark only marks consumed (the arena resolves the
    3-kill arc in Task 5).
    """
    _check_vitals(hp, max_hp, revives_used, now)
    match item:
        case ItemKind.BLOOD_VIAL:
            return TriggerResult(
                hp=min(hp + BLOOD_VIAL_HEAL, max_hp),
                frost_until=0.0,
                shield_until=0.0,
                revives_used=revives_used,
                consumed=True,
            )
        case ItemKind.SECOND_WIND:
            if hp <= 0.0 and revives_used == 0:
                return TriggerResult(
                    hp=max_hp * SECOND_WIND_FRACTION,
                    frost_until=0.0,
                    shield_until=0.0,
                    revives_used=1,
                    consumed=True,
                )
            return TriggerResult(
                hp=hp,
                frost_until=0.0,
                shield_until=0.0,
                revives_used=revives_used,
                consumed=False,
            )
        case ItemKind.FROST_VEIL:
            return TriggerResult(
                hp=hp,
                frost_until=now + FROST_VEIL_DURATION + veil_bonus,
                shield_until=0.0,
                revives_used=revives_used,
                consumed=True,
            )
        case ItemKind.CHAIN_SPARK:
            return TriggerResult(
                hp=hp,
                frost_until=0.0,
                shield_until=0.0,
                revives_used=revives_used,
                consumed=True,
            )
        case _:
            assert_never(item)


def nova_ready(net_accuracy: float, good_seconds: float) -> bool:
    """NOVA fires once net (tally) accuracy holds 95%+ for 30 charged seconds."""
    return net_accuracy >= NOVA_MIN_ACCURACY and good_seconds >= NOVA_CHARGE_SECONDS


def nova_charge(good_seconds: float, net_accuracy: float, dt: float) -> float:
    """Bank sim seconds toward NOVA; sloppy time simply does not charge."""
    if net_accuracy >= NOVA_MIN_ACCURACY:
        return good_seconds + dt
    return good_seconds
