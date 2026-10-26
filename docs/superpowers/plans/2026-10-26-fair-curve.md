# Fair curve + hub-grade menus + CLI README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transparent sprites, a linear wave ramp with ±20%-leashed adaptation, hub-grade styling on every screen, CLI-themed README with true screenshots, released as 0.1.1.

**Architecture:** Root-cause fixes in place (alpha passthrough, not re-skinning; baseline table, not clamp tuning). Menus restyle CSS/compose only — no nav/behavior changes, stable widget ids. Screenshots via headless autopilot; release on a clean branch excluding planning docs.

**Tech Stack:** Python 3.13, Textual, Pillow, pytest + xdist, hatchling, twine, gh.

**Spec:** `docs/superpowers/specs/2026-10-26-fair-curve-design.md`

## Global Constraints

- No new deps.
- Full suite green after every task (`pytest -n auto`).
- Ruff clean (`ruff check`, `ruff format`).
- Widget ids queried by tests (`#shop-gold`, `#shop-item-N`, `#shop-message`, `#settings-rows`, `#report-spark`, `#hub-list`, etc.) stay stable.
- Don't revert the parallel agent's committed menu CSS (border titles, `#7B2CBF` panels).
- Release commit excludes `docs/superpowers/`, `.omo/`, `dist/`.

## Review Focus

- Sixel backend flattens alpha to black: a black foe-box over a lighter panel would resurrect the bug on Windows Terminal — verify against the true stage background in the review pass.
- Wave-1 rookie with 15 WPM must finish wave 1 alive most runs — sim or pilot-test it, don't eyeball.
- Headless screenshots render blank if animations/timers don't settle — every capture asserts on SVG `<text>` content before saving.
- README image paths must be repo-relative (`docs/screenshots/*.svg`) so they render on both GitHub and PyPI long description.
- PyPI 0.1.1 upload must come from a rebuilt wheel off the release commit, verified by a fresh-venv `pip install type-survivors-cli==0.1.1`.

---

### Task 1: Alpha-passthrough sprites

**Files:**
- Modify: `src/tsurv/app.py:200-225` (`sprite_image`, `_ARENA_VOID`)
- Test: `tests/test_visuals.py` (or wherever `sprite_image` is pinned)

**Interfaces:**
- Consumes: `sprite_path(filename)` (unchanged).
- Produces: `sprite_image(filename) -> Image.Image | None` returning RGBA with alpha intact (still cached, still 2x nearest-scaled).

- [ ] **Step 1: Write the failing test**

```python
def test_sprite_image_keeps_transparency() -> None:
    pic = sprite_image("core_0.png")
    assert pic is not None and pic.mode == "RGBA"
    assert pic.getchannel("A").getextrema()[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_visuals.py::test_sprite_image_keeps_transparency -v`
Expected: FAIL (flattened image has alpha min 255)

- [ ] **Step 3: Implement alpha passthrough in `sprite_image`**

Drop the `_ARENA_VOID` composite; keep cache + `ImageOps.scale(2)`. Delete `_ARENA_VOID` if it has no other readers (grep first).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_visuals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tsurv/app.py tests/test_visuals.py
git commit -m "fix: transparent sprites stop painting over the MC"
```

### Task 2: Linear wave baseline with leashed adaptation

**Files:**
- Modify: `src/tsurv/combat.py:240-246` (add, don't change `spawn_interval`)
- Modify: `src/tsurv/app.py:995-1016` (tick gap wiring), `src/tsurv/app.py` kill path (pace EMA)
- Test: `tests/test_combat.py`, `tests/test_screens.py` (pilot gap assertion)

**Interfaces:**
- Consumes: `service_wpm(samples)`, `REF_WPM`, existing `spawn_interval` (kept as the raw ratio source).
- Produces:
  - `wave_baseline_gap(wave: int) -> float` — linear ramp `min(max(3.4 - 0.12 * wave, 1.2), 3.4)`, so wave 1 ≈ 3.28s, wave 10 ≈ 2.2s, wave 18+ = 1.2s floor.
  - `adapt_multiplier(ref_wpm: float, pace_wpm: float) -> float` — `spawn_interval(ref, pace) / BASE_SPAWN_INTERVAL` clamped to `[0.8, 1.2]`.
  - `ArenaScreen._pace_ema: float | None` — per-kill EMA (`0.85 * old + 0.15 * service_wpm`), seeded from the run-opening ability.

- [ ] **Step 1: Write the failing tests**

```python
def test_wave_baseline_ramps_linearly() -> None:
    gaps = [wave_baseline_gap(w) for w in (1, 5, 10, 18, 30)]
    assert gaps == sorted(gaps, reverse=True)
    assert gaps[0] > 3.0 and gaps[-1] == gaps[-2] == 1.2

def test_adapt_multiplier_leashed() -> None:
    assert adapt_multiplier(40.0, 200.0) == 0.8
    assert adapt_multiplier(40.0, 1.0) == 1.2
    assert adapt_multiplier(40.0, 40.0) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_combat.py -k "baseline or adapt_multiplier" -v`
Expected: FAIL with "not defined"

- [ ] **Step 3: Implement `wave_baseline_gap` + `adapt_multiplier` in `src/tsurv/combat.py`**

Pure functions next to `spawn_interval`. Import nothing new.

- [ ] **Step 4: Rewire tick: `gap = wave_baseline_gap(wave) * adapt_multiplier(ref, ema) * mercy * director`**

Update the EMA on every Kill in the kill path. Rescue paths (mercy 1.5x, Relax 1.3x) intentionally stay outside the ±20% band — document that in the tick comment.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -n auto -q`
Expected: PASS (update any test pinning the old raw-pace gap)

- [ ] **Step 6: Commit**

```bash
git add src/tsurv/combat.py src/tsurv/app.py tests/
git commit -m "feat: linear wave baseline with leashed skill adaptation"
```

### Task 3: Wave-1 rails and proper scaling audit

**Files:**
- Modify: `src/tsurv/words.py` (add `max_len_for_wave`), `src/tsurv/app.py:1105` (`_spawn_foe` rails)
- Modify: `src/tsurv/arena.py` (`kind_for_wave` if wave-1 leaks non-grunts)
- Test: `tests/test_words.py`, `tests/test_arena.py`

**Interfaces:**
- Produces: `max_len_for_wave(wave: int) -> int` = `min(OPENING_MAX_LEN + wave - 1, 12)` (wave 1 → 4, wave 5 → 8, wave 9+ → 12).

- [ ] **Step 1: Write the failing tests**

```python
def test_max_len_ramps_with_wave() -> None:
    assert max_len_for_wave(1) == 4
    assert max_len_for_wave(5) == 8
    assert max_len_for_wave(30) == 12

def test_wave_one_spawns_grunts_only() -> None:
    assert set(kind_for_wave(1)) == {EnemyKind.GRUNT}  # adjust to actual signature
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_words.py tests/test_arena.py -k "max_len or wave_one" -v`
Expected: FAIL

- [ ] **Step 3: Implement `max_len_for_wave`; wire `_spawn_foe` to use it instead of the wave-1-only `OPENING_MAX_LEN` gate**

Also verify `kind_for_wave(1)` is grunts-only and wave-2+ introduces mites gradually; fix the table if not.

- [ ] **Step 4: Pilot-test a rookie wave 1: spawn-enabled run at ~15 WPM completes wave 1 alive** (drive via `spawn_test_enemy` + slow presses, or assert `wave_baseline_gap(1) * 1.2` slowest-case spawn pressure < leak pressure for short words — pick the cheaper deterministic assertion)

- [ ] **Step 5: Run full suite, commit**

```bash
git add src/tsurv/words.py src/tsurv/app.py src/tsurv/arena.py tests/
git commit -m "feat: wave-1 rails and linear word-length scaling"
```

### Task 4: Shop screen hub-grade restyle

**Files:**
- Modify: `src/tsurv/app.py:2197-2276` (`ShopScreen.CSS` + `compose`)
- Test: `tests/test_screens.py` (existing pilot shop tests must pass unchanged; add one asserting the new panel ids/titles exist)

**Interfaces:**
- Consumes: `SHOP_CATALOG`, `shop_rank`, `price_for`, `shop_row_text` (unchanged).
- Produces: same widget ids (`#shop-title`, `#shop-gold`, `#shop-item-N`, `#shop-message`, `#shop-hint`), wrapped in `#shop-header` + `#shop-panel` Verticals with hub-style border titles and `#12101F` panel background.

- [ ] **Step 1: Write the failing test**

```python
async def test_pilot_shop_has_hub_grade_panels() -> None:
    # mount shop via pilot; assert #shop-panel and #shop-header exist
    # and #shop-gold still shows the wallet
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Restyle CSS + compose (panels, border titles with glyphs, icon prefixes on rows); no behavior/key changes**
- [ ] **Step 4: Run shop tests to verify they pass**
- [ ] **Step 5: Commit** (`feat: hub-grade void market panels`)

### Task 5: Settings screen hub-grade restyle

**Files:**
- Modify: `src/tsurv/app.py:2279-2332` (`SettingsScreen.CSS` + `compose` + `_rows`)
- Test: `tests/test_screens.py` (existing settings tests unchanged; add panel-presence test)

Same 5 steps as Task 4: keep ids `#settings-title`, `#settings-gold`, `#settings-rows`, `#settings-hint`; wrap in header/panel Verticals; render rows with icon prefixes (`◈ palette …`); commit `feat: hub-grade ritual circle panels`.

### Task 6: Recap, pause, and help hub-grade restyle

**Files:**
- Modify: `src/tsurv/app.py:1863-1977` (`ReportScreen`), pause overlay label + its CSS, `HOW_TO` help text path
- Test: `tests/test_screens.py` (recap/pilot tests unchanged; add panel-presence test for report)

Same 5 steps: keep ids (`#report-score/kills/wave/card/spark/stats/retry/hint`); panel the tallies + graph with border titles; pause overlay becomes a bordered panel with the five entries and icons; help text keeps content, gains the panel voice; commit `feat: hub-grade recap, pause, and help`.

### Task 7: True screenshots (all screens incl. recap graph)

**Files:**
- Create (throwaway, NOT committed): `/tmp/ship/capture.py`
- Create (committed): `docs/screenshots/hub.svg`, `arena.svg`, `shop.svg`, `report.svg`

**Interfaces:**
- Consumes: `TypeSurvivorsApp`, `ArenaScreen.spawn_test_enemy`, `ReportScreen(score, kills, wave, card, wpm, ...)` with a canned WPM trail.

- [ ] **Step 1: Write the capture script**

Headless `run_async(size=(120, 36))` per screen; hub waits out the decrypt worker; arena spawns 3 foes at distance, types a partial word, screenshots mid-action with the MC visible; shop presses `h` from hub; report mounts `ReportScreen` directly with a 60-sample WPM trail. Each capture asserts its SVG contains expected `<text>` (e.g. `VOID`, `GOLD`, `WPM`) before writing.

- [ ] **Step 2: Run it, inspect the SVGs** (grep `<text>` nodes; confirm MC art present in arena, graph present in report)
- [ ] **Step 3: Copy the four SVGs into `docs/screenshots/`** (script itself stays in /tmp, never committed)

### Task 8: CLI-themed README + docs refresh

**Files:**
- Modify: `README.md`, `PLAN.md`

- [ ] **Step 1: Rewrite the README in the CLI voice**

Void-black `#0B0B12` label colors, purple `#7B2CBF` accents, gold `#FFD23F` highlights; game-glyph dividers (`╰~-~-~ ※ ⛧`); no red-venom banner — capsule header re-tinted to a void-purple gradient with gold title text (or dropped if it fights the palette); screenshot table gains the recap graph; install grimoire unchanged in structure (per-OS pipx/uvx/pip verified working in the 0.1.0 release).

- [ ] **Step 2: Refresh `PLAN.md` to match the shipped game**

Controls, screens, difficulty engine, shop, persistence — everything a new contributor needs, in the same CLI voice; delete anything the code no longer does.

- [ ] **Step 3: Verify every image path is repo-relative and every badge URL resolves** (`docs/screenshots/*.svg` exist; shields/pypi links correct)
- [ ] **Step 4: Commit** (`docs: CLI-themed README, refreshed PLAN`)

### Task 9: Release 0.1.1 to GitHub + PyPI

**Files:**
- Modify: `pyproject.toml` (`version = "0.1.1"`)

- [ ] **Step 1: Bump version, rebuild, verify**

Run: `rm -rf dist && uv build && uv run --with twine twine check dist/*`
Expected: both PASS

- [ ] **Step 2: Fresh-venv end-user check**

Run: `pip install dist/*.whl` in a clean venv; `type-survivors --help` boots.
- [ ] **Step 3: Commit to the release branch excluding planning docs**

```bash
git checkout release-v0.1.0
git add -A -- ':!docs/superpowers'
git commit -m "Type Survivors 0.1.1: fair curve, hub-grade menus"
git push origin release-v0.1.0
```

- [ ] **Step 4: Tag + GitHub release + PyPI upload**

```bash
gh release create v0.1.1 --title "v0.1.1 — Fair curve" --notes "..."
TWINE_USERNAME=__token__ TWINE_PASSWORD='<token>' uv run --with twine twine upload dist/*
```

- [ ] **Step 5: Verify live install** (`pip install type-survivors-cli==0.1.1` in a clean venv boots)

## Self-Review

1. **Spec coverage:** sprites (T1), fair curve + scaling (T2+T3), every-screen restyle (T4+T5+T6), stats graph in README (T6 graph kept + T7 report.svg + T8), CLI-themed README (T8), screenshots (T7). Covered.
2. **Step scan:** each test step names exact assertions; code steps name exact signatures/files. T4–T6 test bodies are sketched, not transcribed — implementer fills assertions from the ids listed.
3. **Type consistency:** `wave_baseline_gap`/`adapt_multiplier`/`max_len_for_wave` defined once in T2/T3, consumed in T2-step-4/T3-step-3. No cross-task renames.
4. **Review Focus:** five failure modes listed above; each maps to its owning task (T1 sixel check → manual review in T7 screenshots; T3 rookie wave-1 test; T7 asserts; T8 path check; T9 live-install check).
5. **Proportion:** plan is shorter than the code it drives; bodies live with the implementer.
