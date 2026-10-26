# UI/UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all presentation (title, hub, arena, HUD, markers, effects) and the metrics/rewards core of Type Survivors with the approved full-screen-battlefield redesign, without changing words, difficulty brain inputs, economy, mercy, or spaced repetition.

**Architecture:** World-space sim (arena owns positions in world units; camera maps to viewport) with a canvas render layer; metrics taxonomy module feeding a skill-gated scorer; alpha-dashboard hub and docked HUD rails as Textual screens.

**Tech Stack:** Python, Textual 8.x, rich-pixels (logo runtime), terminaltexteffects (menu motion), Pillow (logo bake + cell art), pytest `-n auto`, basedpyright all, ruff ALL.

**Spec:** `docs/superpowers/specs/2026-10-25-uix-redesign-design.md` (13 locked decisions) plus `type-survivors-cli/PLAN.md` (game math, unchanged).

## Global Constraints

- uv only; no new runtime deps beyond rich-pixels + terminaltexteffects (both pure Python).
- basedpyright `all` clean, `ruff check` + `ruff format --check` clean, full gate green before every commit.
- Frozen dataclasses + slots, NewType, real-wildcard `assert_never` on every match, no Any/cast/type:ignore/pyright:ignore.
- TDD: failing test first, real tests (pilots for UI), frequent commits `feat:`/`fix:`.
- Mono-safe: color never the sole signal. Layouts hold at 80×24, 120×30, wide Ghostty; <80 guard non-empty.
- Game-math freeze: words, WPM scaling inputs, economy rates, mercy, spaced repetition untouched (spawn travel retune excepted — Task 3).

## Review Focus

- Ultrawide Ghostty (~200+ cols): composition stays centered, no dead acres, nothing overflows (Task 7 test).
- Key mashing with no locked foe scores zero extra-hits and feeds `extra` (Task 1 test).
- Boss banner pause freezes spawn/impact timers; no foe advances or leaks mid-spectacle (Task 8 test).
- A foe leaking with half its word untyped records every untyped char as `missed` (Task 1 test).
- Consistency on <10 per-second samples is flagged rough, never shown as a confident number (Task 1 test).

---

## File structure

- `src/tsurv/metrics.py` (NEW): keystroke taxonomy, net/raw WPM, kogasa consistency. Single responsibility: honest numbers.
- `src/tsurv/combat.py` (MOD): consume taxonomy; `NoTarget` no longer a hit.
- `src/tsurv/arena.py` (MOD): world-space positions, simultaneous spawns, travel-time speeds, skill-gated scorer hooks.
- `src/tsurv/stage.py` (MOD): canvas mapping world→cells, circle markers (tier color / elite ring / boss crown).
- `src/tsurv/app.py` (MOD): HUD rails, pause-for-spectacle clock, hub/home screens, diagnostics.
- `src/tsurv/logo.py` + `assets/logo.png` (NEW): pre-sized art + rich-pixels runtime render + deterministic bake script.
- `tests/test_metrics.py`, `tests/test_arena_world.py`, `tests/test_markers.py`, `tests/test_hud.py` (NEW); pilots in existing visual tests.

### Task 1: Metrics taxonomy core

**Files:**
- Create: `src/tsurv/metrics.py`
- Modify: `src/tsurv/combat.py` (NoTarget-as-hit fix), `src/tsurv/app.py:625-648` (feed taxonomy)
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Keystroke` outcomes from `combat.handle_keystroke`.
- Produces: `tally(outcome, locked: bool) -> Stroke` where `Stroke ∈ {CORRECT, INCORRECT, EXTRA, MISSED}`; `accuracy(c,i,e) = c/(c+i+e)`; `net_wpm(correct_word_chars, seconds)`, `raw_wpm(all_chars, seconds)` (÷5 chars/word); `consistency(samples) -> float` via `kogasa(x) = 100*(1-tanh(x+x**3/3+x**5/5))`, `None`/rough flag when <10 samples.

- [ ] **Step 1: Write failing tests** — `test_notarget_mash_scores_zero` (20 unmatched presses → 0 correct, 20 extra, accuracy 0.0); `test_leak_records_missed` (foe leaks with 3 untyped chars → 3 missed); `test_net_counts_only_clean_words` (`helol` → 0 net chars); `test_consistency_rough_under_10_samples`.
- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_metrics.py -q`. Expected: FAIL, module missing.
- [ ] **Step 3: Implement `metrics.py`** — frozen `Tally` dataclass (c/i/e/m counters), the four functions above with exact formulas.
- [ ] **Step 4: Fix `combat.py`/`app.py`** — `NoTarget` maps to EXTRA, never a hit; leak path emits MISSED per untyped char.
- [ ] **Step 5: Run full file + suite** — `pytest tests/test_metrics.py -q`, then full suite `-n auto`. Expected: PASS.
- [ ] **Step 6: Commit** — `git add src/tsurv/metrics.py src/tsurv/combat.py src/tsurv/app.py tests/test_metrics.py && git commit -m "feat: honest keystroke taxonomy and net/raw metrics"`.

### Task 2: Skill-gated rewards

**Files:**
- Modify: `src/tsurv/arena.py` (scorer), `src/tsurv/app.py` (HUD score source)
- Test: `tests/test_rewards.py` (new) — or extend test_metrics; use new file.

**Interfaces:**
- Consumes: `Tally`, `consistency`, streak multiplier from Task 1/juice.
- Produces: `score_kill(chars, acc, streak_mult, consist) = chars*10 * band(acc) * streak_mult * gate(consist)` with bands ≥.95→1.0, ≥.90→0.8, ≥.85→0.6, ≥.80→0.4, else 0.0; `gate(c) = 0.5 if c<60 else 1.0`.

- [ ] **Step 1: Write failing tests** — `test_sloppy_wave_earns_zero_bonus` (acc .79 → band 0.0); `test_bands_step_down` (all five boundaries); `test_low_consistency_halves_streak`.
- [ ] **Step 2: Run to verify fail** — `pytest tests/test_rewards.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement scorer in `arena.py`** — exact bands and gate above; NOVA 95% gate reads net accuracy.
- [ ] **Step 4: Run tests + suite** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: skill-gated scoring with consistency gate"`.

### Task 3: World-space spawns with real travel time

**Files:**
- Modify: `src/tsurv/arena.py` (positions, multi-spawn, speeds), `src/tsurv/stage.py` (camera map)
- Test: `tests/test_arena_world.py`

**Interfaces:**
- Consumes: difficulty scalar from `spawn_interval` (unchanged inputs).
- Produces: foes spawn on a world ring radius R(level) simultaneously (count = 1 + level//2, cap 8); `impact_time = distance/speed` with real travel; camera `world_to_cell` centers MC at any viewport.

- [ ] **Step 1: Write failing tests** — `test_simultaneous_spawn_count` (level 3 → 2 foes same tick, distinct angles ≥0.25 apart); `test_spawn_radius_viewport_independent` (same world pos at 80×24 and 120×30); `test_far_spawn_lives_longer` (impact time grows with radius).
- [ ] **Step 2: Run to verify fail** — Expected: FAIL.
- [ ] **Step 3: Implement world ring + multi-spawn** — additive fields only on frozen `ArenaEnemy`; travel retune is the sole allowed math change.
- [ ] **Step 4: Run tests + suite** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: world-space simultaneous radial spawns"`.

### Task 4: Circle markers

**Files:**
- Modify: `src/tsurv/stage.py` (markers), `src/tsurv/visuals.py` (glyphs)
- Test: `tests/test_markers.py`

**Interfaces:**
- Produces: `marker(kind, tier, elite, boss) -> (glyph, color)`: circle glyph tinted by tier color; elite adds ring glyph; boss adds red crown glyph above. Mono-safe (shape differs even uncolored).

- [ ] **Step 1: Write failing tests** — `test_elite_has_ring_grunt_does_not`; `test_boss_has_crown`; `test_tier_colors_distinct`; `test_mono_shapes_differ` (NO_COLOR: glyphs still distinct).
- [ ] **Step 2: Run to verify fail** — Expected: FAIL.
- [ ] **Step 3: Implement markers** — replace pip plates; keep word chips adjacent.
- [ ] **Step 4: Run tests + suite** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: circle tier markers with elite ring and boss crown"`.

### Task 5: RPG HUD rails

**Files:**
- Modify: `src/tsurv/app.py` (dock top/bottom/side rails)
- Test: pilots in `tests/test_hud.py`

**Interfaces:**
- Produces: top rail (red HP bar `hp/max`, streak ×N, score, net ACC%, consistency); bottom rail (wave progress bar n/5, `BOSS IN n`, `LV k`); side/below wave banner. All bound to `arena.wave`, `BOSS_EVERY=5`, metrics from Task 1.

- [ ] **Step 1: Write failing pilots** — `test_hud_rails_at_80x24_and_120x30` (all six elements present, bars proportional); `test_boss_countdown_ticks` (wave 3 → "BOSS IN 2").
- [ ] **Step 2: Run to verify fail** — Expected: FAIL.
- [ ] **Step 3: Implement rails** — Textual docked widgets; bars as block glyphs, mono-safe labels.
- [ ] **Step 4: Run pilots + suite** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: RPG HUD rails with wave progress and boss countdown"`.

### Task 6: Logo, title motion, alpha hub

**Files:**
- Create: `assets/logo.png` (pre-sized art), `src/tsurv/logo.py` (bake + rich-pixels render)
- Modify: `src/tsurv/app.py` (hub → home screen)
- Test: `tests/test_logo.py` (bake determinism: same PNG → same cells twice) + hub pilots.

**Interfaces:**
- Produces: `render_logo(cells_w) -> str` (rich-pixels, pre-sized art, deterministic); hub = header logo + decrypt-in via TTE + key-icon buttons (S/P/R/H/E/Q) + footer (`best WPM / gold / LV`); shop/settings/report hang off hub.

- [ ] **Step 1: Write failing tests** — `test_bake_deterministic`; `test_hub_has_all_sections_at_80x24` (logo, 6 buttons, stats footer, vertically centered).
- [ ] **Step 2: Run to verify fail** — Expected: FAIL.
- [ ] **Step 3: Author logo PNG + implement `logo.py` + hub restructure** — pixel art with outline/glow (design asset, builder's eye); TTE decrypt on boot only (non-blocking; hub input live immediately).
- [ ] **Step 4: Run tests + suite** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: baked logo, TTE title motion, alpha-dashboard hub"`.

### Task 7: Kill juice, boss entrance, spectacle pause

**Files:**
- Modify: `src/tsurv/juice.py` (particles), `src/tsurv/app.py` (pause clock, banner)
- Test: `tests/test_juice.py` additions + pilots.

**Interfaces:**
- Produces: `burst(pos, palette=[yellow,red,black])` particle events on kill; disintegration = shrink+fade over 300ms; boss entrance = banner 2.5s + shake + large portal + bar pips; `spectacle_freeze` pauses spawn/impact timers (sim time, not wall).

- [ ] **Step 1: Write failing tests** — `test_kill_spawns_blood_burst` (palette order yellow→red→black); `test_boss_banner_freezes_timers` (sim clock unchanged across banner duration).
- [ ] **Step 2: Run to verify fail** — Expected: FAIL.
- [ ] **Step 3: Implement juice + freeze** — overlay only; typing stays live except banner/transition windows where clock stops.
- [ ] **Step 4: Run tests + suite** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: kill particles, boss entrance, spectacle pause"`.

### Task 8: Acceptance + crash safes + pause menu

**Files:** pilots + `src/tsurv/app.py` (top-level guard, pause overlay).
- [ ] **Step 1: Write wide-viewport pilots** — 200×50 Ghostty: centered composition, no overflow, MC centered, rails docked (field fills ≥70% width).
- [ ] **Step 2: Run to verify fail** — Expected: FAIL on current layout.
- [ ] **Step 3: Fix layout for wide** — responsive rail/collapse rules.
- [ ] **Step 4: Crash safes (no traceback — harden instead)** — top-level exception guard that autosuspends the run, restores the terminal, and shows the error on the hub with "resume where you left off"; panic path covered by a test that raises inside tick and asserts checkpoint written + clean screen stack.
- [ ] **Step 5: Pause menu** — P opens an overlay (Resume / How to Play / Settings / Suspend & Hub / Quit); sim clock frozen while open; pilot asserts overlay options + frozen timers + resume restores.
- [ ] **Step 6: Full gate + commit** — `git commit -m "feat: wide-viewport acceptance, crash safes, pause menu"`.

## Self-review

1. **Spec coverage:** 13 decisions → Tasks 1 (metrics), 2 (rewards), 3 (world spawns/travel), 4 (markers), 5 (HUD), 6 (logo/hub), 7 (juice/pause), 8 (acceptance/crash). Simultaneous spawning (T3), speed adaptivity (T3 travel + unchanged WPM scaling), splash copy (T6 builder asset — code-adjacent, accepted). Covered.
2. **Step scan:** each test step names assertions; each code step names file + signature + exact values. Fixed the vague "responsive rules" by pinning ≥70% fill in T8.
3. **Type consistency:** `Tally`/`Stroke` defined T1, consumed T2; `world_to_cell` produced T3, used by markers/HUD pilots; bands/gate defined once in T2.
4. **Review Focus:** five items each pinned to an owning task test above.
5. **Proportion:** plan states decisions and pins tests; bodies left to implementers.
