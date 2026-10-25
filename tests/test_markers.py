"""Circle tier markers: ringed elites, crowned bosses, mono-safe shapes."""

from __future__ import annotations

from tsurv.arena import EnemyKind
from tsurv.stage import crown_origin
from tsurv.visuals import marker
from tsurv.words import Tier


def test_elite_has_ring_grunt_does_not() -> None:
    """The elite flag adds a ring glyph; plain grunts wear none."""
    elite = marker(EnemyKind.GRUNT, Tier.T2, elite=True, boss=False, mono=False)
    grunt = marker(EnemyKind.GRUNT, Tier.T2, elite=False, boss=False, mono=False)
    assert elite.ring != ""
    assert grunt.ring == ""
    backstop = marker(EnemyKind.ELITE, Tier.T2, elite=False, boss=False, mono=False)
    assert backstop.ring != ""


def test_boss_has_crown() -> None:
    """The boss flag (or boss kind) adds a red crown worn above the art."""
    boss = marker(EnemyKind.BOSS, Tier.BOSS, elite=False, boss=True, mono=False)
    assert boss.crown != ""
    assert boss.crown_color == "#FF2A2A"
    backstop = marker(EnemyKind.BOSS, Tier.BOSS, elite=False, boss=False, mono=False)
    assert backstop.crown != ""
    plain = marker(EnemyKind.GRUNT, Tier.T1, elite=False, boss=False, mono=False)
    assert plain.crown == ""
    assert plain.crown_color is None
    art = ("#####", "#####")
    assert crown_origin(10, 5, art) == (10, 4)


def test_tier_colors_distinct() -> None:
    """Every tier tints its circle a different color."""
    colors = {
        marker(EnemyKind.GRUNT, tier, elite=False, boss=False, mono=False).color
        for tier in Tier
    }
    assert len(colors) == len(list(Tier))
    assert None not in colors


def test_mono_shapes_differ() -> None:
    """NO_COLOR strips the tint but the circle phases stay distinct."""
    markers = [
        marker(EnemyKind.GRUNT, tier, elite=False, boss=False, mono=True)
        for tier in Tier
    ]
    assert len({item.glyph for item in markers}) == len(list(Tier))
    assert all(item.color is None for item in markers)
