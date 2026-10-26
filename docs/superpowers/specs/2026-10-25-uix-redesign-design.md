# UI/UX Redesign — Full-Screen Battlefield

Date: 2026-10-25. Status: awaiting user approval. Build freeze holds until approved.

## Intent and why

The typing game underneath works (words, adaptive difficulty, bosses, streaks,
coaching — all green). Its face does not: playtest screenshots show a "hole"
for a player character, enemies clumped at spawn, an uncentered menu, acres of
empty space on wide terminals, and a startup crash. This redesign replaces all
presentation — title, hub, arena, HUD, effects — while touching zero game math.

## Goals

- Minecraft-feel title: designed pixel logo, splash tagline, alpha-dashboard
  hub (logo header, key-plus-icon buttons, live stats footer).
- True 2D arena: MC sprite centered, simultaneous radial spawns from far out
  that visibly travel inward, speed/count scaling with level.
- Kill juice: blood splash (yellow→red→black fade), disintegration particles;
  boss entrance (banner, shake, large portal, bar pips).
- Full RPG HUD: red HP bar, streak meter, score/accuracy, wave progress bar,
  waves-until-boss countdown, level number (level = boss gate: 5 waves + boss).
- Cells-first: must look great with zero graphics protocol (test terminal has
  none); kitty true-pixel is enhancement only, auto-detected.
- Crash fixed (needs user traceback — open input, see below).

## Non-goals / anti-goals

- No XP/perk/level-up systems; level = boss gate cleared. No game-math changes
  (words, difficulty, economy, mercy, spaced repetition untouched).
- Failure = pretty but unreadable: word chips must never render under
  particles; color never the sole signal (mono-safe glyphs).
- No new runtime deps beyond rich-pixels + terminaltexteffects (both pure
  Python, Textual-compatible). No chafa (external binary).

## Constraints

- Textual app, uv-only, basedpyright all, ruff ALL, full gate green, TDD,
  frozen+slots, real-wildcard assert_never, no Any/cast/type-ignore.
- Layouts must hold at 80×24, 120×30, and ultrawide (previous failure: only
  narrow sizes were piloted). <80 keeps a non-empty guard.

## Approaches

- A. Full-screen battlefield (PICKED): arena owns the screen, docked HUD
  rails. Max feel; readability fought for via clean chip plates.
- B. Panel roguelike (rejected): smaller map, side panels, message log.
  Legible but not the game feel requested.
- C. Hybrid (rejected): compact canvas + labeled panels; neither cinematic
  nor crisp enough to beat A at the stated goal.

## Decided parts (user-locked)

1. Logo: rich-pixels runtime render from pre-sized art (designed once).
2. Menu motion: terminaltexteffects (decrypt boot, slides on transitions).
3. Hub: alpha-dashboard structure — a true restructured home screen; shop,
   settings, report hang off it.
4. Arena: approach A; simultaneous spawns, REAL travel time from far out
   (difficulty retuned around it — the math freeze is lifted for spawn travel
   only; words/economy/mercy/repetition untouched).
5. Juice: splash + disintegration + boss entrance as specified above.
6. HUD: HP bar, streak, score/acc, wave progress, boss countdown, level.
7. Spectacle pauses the clock: input frozen during boss entrances and
   transitions (fairness rule).
8. Wave tracking already exists (arena.wave, BOSS_EVERY=5) — HUD binds to it.
9. Acceptance: user's Ghostty at full width; hold = no overflow, no dead
   acres, centered composition.
10. World-space spawns: enemies spawn at world positions independent of the
    viewport; the camera maps world→screen (small screens see less field, not
    a smaller world). Speed/distance owned by the difficulty engine, retuned
    for real travel time.
11. Markers, simplified: circle under each foe, color = difficulty tier;
    ring around circle = elite; red crown = boss. No pips/text plates.
12. Metrics redo (mechanism): per-keystroke taxonomy correct / incorrect /
    extra / missed (Monkeytype model). Correct = right char on locked foe.
    Incorrect = wrong char while locked (still stuns). Extra = keypress
    matching nothing (fixes the NoTarget-as-hit inflation). Missed = chars
    left untyped when a foe leaks. Accuracy = correct/(correct+incorrect+
    extra). Net WPM counts only fully-correct words (word-level, Monkeytype
    rule — fast-and-sloppy can't outscore fast-and-clean); raw WPM counts
    everything; the raw−net gap is the sloppiness signal. Consistency =
    kogasa over per-second raw samples (TypeCrt formula), <10 samples flagged
    rough. keybr confidence + spaced repetition keep feeding word selection;
    NOVA's 95% gate moves to net accuracy.
13. Rewards (skill-gated score, locked): kill score = base chars ×
    accuracy-band modifier (TypeClash-style: ≥95% ×1.0, ≥90% ×0.8, ≥85%
    ×0.6, ≥80% ×0.4, <80% ×0 — sloppy waves earn nothing extra) × streak
    multiplier (existing x4/x8/x16 ladder) × consistency gate (consistency
    <60 halves streak gains). Mashing pays base only; clean flow multiplies.

## Left to the builder

- Exact canvas mapping (polar→cells), chip plate style, particle budget
  (count/lifetime at 60fps), spawn simultaneity curve per level.
- Logo art itself (design asset, not code) + splash line copy.
- Crash root-cause once traceback arrives; renderer diagnostics line stays.

## Open input needed

- Startup crash traceback (user to paste).
- Logo art + splash copy approval (mockup before build).
