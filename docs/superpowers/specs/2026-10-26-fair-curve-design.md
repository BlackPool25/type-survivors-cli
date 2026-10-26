# Design: sprite alpha, fair curve, hub-grade menus, CLI-themed README — 2026-10-26

## Intent and why

Players report three feel-breakers: foe sprites render as opaque tiles
that swallow the MC; wave 1 can be brutal while one good burst makes the
game spike; submenus look nothing like the hub. The README sells all of
it with off-theme art and bad screenshots. Fix the feel, then sell it.

## Goals / non-goals / anti-goals

- Goals: transparent foe sprites; wave 1 completable by a hunt-and-peck
  rookie; a visible linear ramp across waves with adaptation leashed to
  ±20%; every screen speaks hub; README matches the CLI theme with true
  screenshots incl. the recap graph.
- Non-goals: new enemies/art, new tracks, rebalancing shop prices, GIFs.
- Anti-goals: a curve that punishes skill (adaptation must never be the
  reason a good player dies); menus that flash or distract mid-run.

## Constraints

- No new deps. Full suite green. Manual headless screenshot review.
- Build on the parallel agent's committed menu CSS (titles/panels), don't
  revert it.

## Approaches

- Sprites: alpha passthrough (picked — only sane fix) vs per-frame
  background matching (rejected: fragile, costly).
- Difficulty: line-plus-leash (picked) vs tighter clamp on instant pace
  (rejected: keeps the jerk).
- Menus/README: hub voice everywhere + CLI-palette README (picked, only
  sane path).

## Decided

- Rescue dips below the line allowed; adaptation band ±20% around the
  wave line; rating moves slowly (many kills per nudge); every screen
  restyled (hub/shop/settings/pause/recap/help).
- Scaling: explicit per-wave baseline table — gap, word-length rails,
  speeds all linear in wave with a hard late-game floor so it scales
  from gentle to brutal without cliffs. Wave 1: short words only, slowest
  gap, grunts only.

## Left to the builder

Exact per-wave table numbers; screenshot capture choreography; README
badge/palette hexes; whether PyPI goes 0.1.1 or 0.2.0.
