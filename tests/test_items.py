"""Tests for the pure item + powerup economy (heals, slows, revives, NOVA)."""

from __future__ import annotations

import pytest

from tsurv.items import (
    BLOOD_VIAL_HEAL,
    FROST_VEIL_DURATION,
    NOVA_CHARGE_SECONDS,
    NOVA_MIN_ACCURACY,
    ActiveEffects,
    ItemError,
    ItemKind,
    TriggerResult,
    nova_ready,
    trigger,
)

_MAX_HP = 100.0
_MID_HP = 70.0
_LOW_HP = 40.0


def test_blood_vial_heals_thirty() -> None:
    """Blood Vial restores 30 HP and is consumed."""
    result = trigger(ItemKind.BLOOD_VIAL, 50.0, 100.0, 0, 10.0)
    assert result == TriggerResult(
        hp=50.0 + BLOOD_VIAL_HEAL,
        frost_until=0.0,
        shield_until=0.0,
        revives_used=0,
        consumed=True,
    )


def test_blood_vial_caps_at_max() -> None:
    """Overheal clamps to max HP instead of exceeding it."""
    result = trigger(ItemKind.BLOOD_VIAL, 90.0, 100.0, 0, 10.0)
    assert result.hp == _MAX_HP


def test_frost_veil_bonus_extends_slow() -> None:
    """Deep-chill ranks add seconds to the frost window (bonus defaults 0)."""
    base = trigger(ItemKind.FROST_VEIL, _MID_HP, _MAX_HP, 0, 10.0)
    assert base.frost_until == 10.0 + FROST_VEIL_DURATION
    boosted = trigger(ItemKind.FROST_VEIL, _MID_HP, _MAX_HP, 0, 10.0, veil_bonus=2.0)
    assert boosted.frost_until == 10.0 + FROST_VEIL_DURATION + 2.0


def test_frost_veil_sets_slow_window() -> None:
    """Frost Veil opens an absolute 5s slow window and is consumed."""
    result = trigger(ItemKind.FROST_VEIL, _MID_HP, _MAX_HP, 0, 10.0)
    assert result.frost_until == 10.0 + FROST_VEIL_DURATION
    assert result.hp == _MID_HP
    assert result.consumed is True


def test_second_wind_revives_once_at_half() -> None:
    """Lethal damage with a fresh Second Wind revives at 50% max HP."""
    result = trigger(ItemKind.SECOND_WIND, 0.0, 100.0, 0, 10.0)
    assert result == TriggerResult(
        hp=50.0,
        frost_until=0.0,
        shield_until=0.0,
        revives_used=1,
        consumed=True,
    )


def test_second_wind_spent_stays_dead() -> None:
    """A used Second Wind does not revive a second time."""
    result = trigger(ItemKind.SECOND_WIND, 0.0, 100.0, 1, 10.0)
    assert result == TriggerResult(
        hp=0.0,
        frost_until=0.0,
        shield_until=0.0,
        revives_used=1,
        consumed=False,
    )


def test_second_wind_ignores_healthy() -> None:
    """Second Wind only fires on lethal damage, never while alive."""
    result = trigger(ItemKind.SECOND_WIND, _LOW_HP, _MAX_HP, 0, 10.0)
    assert result.hp == _LOW_HP
    assert (result.revives_used, result.consumed) == (0, False)


def test_chain_spark_consumes_without_touching_vitals() -> None:
    """Chain Spark marks consumed; the arena resolves the 3-kill arc."""
    result = trigger(ItemKind.CHAIN_SPARK, _MID_HP, _MAX_HP, 0, 10.0)
    assert result == TriggerResult(
        hp=70.0,
        frost_until=0.0,
        shield_until=0.0,
        revives_used=0,
        consumed=True,
    )


def test_nova_locked_below_threshold() -> None:
    """NOVA stays locked below 95% accuracy or before 30 charged seconds."""
    assert nova_ready(NOVA_MIN_ACCURACY - 0.001, NOVA_CHARGE_SECONDS) is False
    assert nova_ready(1.0, NOVA_CHARGE_SECONDS - 0.1) is False
    assert nova_ready(0.5, 120.0) is False


def test_nova_ready_at_threshold() -> None:
    """NOVA fires at 95%+ accuracy after 30 charged seconds."""
    assert nova_ready(NOVA_MIN_ACCURACY, NOVA_CHARGE_SECONDS) is True
    assert nova_ready(1.0, NOVA_CHARGE_SECONDS + 30.0) is True


def test_effects_windows_are_absolute() -> None:
    """ActiveEffects carries absolute now-based timestamps, 0.0 = inactive."""
    assert ActiveEffects(frost_until=0.0, shield_until=0.0) == ActiveEffects(
        frost_until=0.0,
        shield_until=0.0,
    )


def test_trigger_rejects_bad_vitals() -> None:
    """Out-of-range vitals raise ItemError instead of warping state."""
    with pytest.raises(ItemError):
        _ = trigger(ItemKind.BLOOD_VIAL, 50.0, 0.0, 0, 10.0)
    with pytest.raises(ItemError):
        _ = trigger(ItemKind.BLOOD_VIAL, -1.0, 100.0, 0, 10.0)
    with pytest.raises(ItemError):
        _ = trigger(ItemKind.BLOOD_VIAL, 101.0, 100.0, 0, 10.0)
    with pytest.raises(ItemError):
        _ = trigger(ItemKind.BLOOD_VIAL, 50.0, 100.0, -1, 10.0)
    with pytest.raises(ItemError, match="now"):
        _ = trigger(ItemKind.BLOOD_VIAL, 50.0, 100.0, 0, -0.1)
