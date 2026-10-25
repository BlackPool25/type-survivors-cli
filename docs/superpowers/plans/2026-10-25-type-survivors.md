# Type Survivors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the playable Type Survivors CLI game (Textual) from DESIGN.md, tested and gated.

**Architecture:** Pure-logic core (`words`, `combat`, `items`, `profile` — no Textual imports, fully unit-tested) with a thin Textual shell (`app`, screens) driven by pilot E2E tests. Assets in `assets/`, word lists in `words/` (already on disk, verified).

**Tech Stack:** Python ≥3.13, uv, Textual + Rich, Pydantic v2 (profile), pytest + pilot, basedpyright `all`, ruff `ALL`.

**Spec:** `type-survivors-cli/docs/superpowers/specs/DESIGN.md` (approved) + `type-survivors-cli/PLAN.md` (v0.2: research, Q&A locks, systems detail — the plan argues from both; executors read both)

## Global Constraints

- `uv` only (never pip). `basedpyright typeCheckingMode = "all"`. `ruff select = ["ALL"]`. CI gate: `uv run basedpyright && uv run ruff check && uv run ruff format --check && uv run pytest`.
- Frozen dataclasses (`frozen=True, slots=True`); `NewType` for IDs; `match` + `assert_never` for variants; no `Any`/`cast`/`type: ignore`; specific exceptions only; `anyio` never `asyncio`.
- TDD red → green → refactor for every task. Full suite green before done.
- No network at runtime (`words/` and `assets/` are local). No color-only identity (shape + icon per enemy). Respect `NO_COLOR`.

## Review Focus

- Paste/IME burst input (many chars in one event) must not skip stun or double-kill; expect per-char processing in order.
- Terminal < 80 cols must show the guard screen, never a crashed layout.
- Corrupt `profile.json` (bad JSON, future version) must fall back to defaults with gold preserved when parseable, never crash to traceback.
- Boss sentence punctuation (apostrophes, hyphens) must be typeable on a plain US keyboard layout.
- `NO_COLOR=1` must strip all color while keeping shapes/icons readable.

---

### Task 0: Scaffold

**Files:**
- Create: `type-survivors-cli/pyproject.toml`, `type-survivors-cli/src/tsurv/__init__.py`
- Test: `type-survivors-cli/tests/test_scaffold.py`

**Interfaces:**
- Consumes: nothing.
- Produces: package `tsurv` importable under `uv run pytest`; `PROFILE_DIR` convention (XDG) defined in Task 4.

- [ ] **Step 1:** `uv init --app` in `type-survivors-cli/`, replace `[tool.*]` with strict block, `uv add textual pydantic`, `uv add --dev basedpyright ruff pytest pytest-cov`.
- [ ] **Step 2 (red):** `tests/test_scaffold.py::test_package_imports` asserts `import tsurv` works. Run: `uv run pytest tests/test_scaffold.py` — expect FAIL (no src layout yet).
- [ ] **Step 3 (green):** create `src/tsurv/__init__.py` with `__version__ = "0.1.0"`. Rerun — expect PASS.
- [ ] **Step 4:** run full CI gate once, fix violations. Commit: `feat: scaffold strict uv project`.

### Task 1: Word engine (pure)

**Files:**
- Create: `src/tsurv/words.py`. Test: `tests/test_words.py`. Data: `words/*.json` (exists).

**Interfaces:**
- Consumes: nothing.
- Produces: `Tier(StrEnum: T1/T2/CODE/BOSS)`, `Corruption(StrEnum: CLEAN/REVERSED/GLITCH/ROT13)`, `Word(frozen: text, tier, corruption)`, `pick_word(tier: Tier, history: Sequence[str], on_screen: Sequence[str]) -> Word`, `chunk_boss_sentence(sentences: Sequence[str]) -> list[str]`.

- [ ] **Step 1 (red):** tests: tier length bands (T1 3–5, T2 5–8, T3→9+ from 10k list); no word repeats within last 30; max 2 shared initials on screen; swear-list word never returned. Run — FAIL (module missing).
- [ ] **Step 2 (green):** implement loader (JSON at import, local files only) + `pick_word` with constraints. Rerun — PASS.
- [ ] **Step 3 (red):** `chunk_boss_sentence` splits sentence into words, keeps punctuation attached, every chunk typeable ASCII. Run — FAIL.
- [ ] **Step 4 (green):** implement chunker. Full suite PASS. Commit: `feat: word selection engine`.

### Task 2: Combat core (pure)

**Files:**
- Create: `src/tsurv/combat.py`. Test: `tests/test_combat.py`.

**Interfaces:**
- Consumes: `Word` from Task 1.
- Produces: `EnemyId = NewType("EnemyId", int)`, `EnemyState(frozen: id, word, hp_words, distance)`, `Keystroke` union (`Advanced | Kill | TypoStun | NoTarget`), `lock_target(ch: str, enemies: Sequence[EnemyState], current: EnemyId | None) -> EnemyId | None`, `apply_keystroke(...) -> Keystroke`, `rolling_wpm(events: Sequence[float], now: float) -> float`, `spawn_interval(ref_wpm: float, player_wpm: float) -> float` (= base × clamp(ref/player, 0.6, 1.6)).

- [ ] **Step 1 (red):** tests: first-letter locks; 2nd letter disambiguates pair; Esc clears; correct char advances; wrong char → `TypoStun` (0.6s gun-jam flag + streak reset); completing word → `Kill`. Run — FAIL.
- [ ] **Step 2 (green):** implement targeting + keystroke. Rerun — PASS.
- [ ] **Step 3 (red):** tests: `rolling_wpm` over last-20 timestamps; `spawn_interval` clamps at 0.6/1.6 edges; streak x8 grants 1s shield flag. Run — FAIL.
- [ ] **Step 4 (green):** implement. Suite PASS. Commit: `feat: combat targeting and streak state`.

### Task 3: Items + NOVA + Second Wind (pure)

**Files:**
- Create: `src/tsurv/items.py`. Test: `tests/test_items.py`.

**Interfaces:**
- Consumes: `Kill` events from Task 2.
- Produces: `ItemKind(StrEnum: BLOOD_VIAL/SECOND_WIND/FROST_VEIL/CHAIN_SPARK)`, `ActiveEffects(frozen: frost_until, shield_until, ...)`, `trigger(item, state) -> ActiveEffects`, `nova_ready(clean_seconds: float, accuracy: float) -> bool` (30s @ ≥95%).

- [ ] **Step 1 (red):** tests: Blood Vial +30HP capped at max; Frost sets slow window; Second Wind auto-revives once at 50%; NOVA false at 94.9%, true at 95%+ after 30s. Run — FAIL.
- [ ] **Step 2 (green):** implement. Suite PASS. Commit: `feat: items and NOVA economy`.

### Task 4: Profile + persistence (integration)

**Files:**
- Create: `src/tsurv/profile.py`. Test: `tests/test_profile.py` (tmp_path fixture, never real home dir).

**Interfaces:**
- Consumes: keystroke/WPM events from Tasks 2–3.
- Produces: `Profile(BaseModel frozen: gold, shop, hiscores, settings, per_key: dict[str, KeyStat], runs: list[RunSummary])`, `load_profile(dir: Path) -> Profile` (corrupt → defaults, gold preserved when parseable), `save_profile(dir, profile) -> None`, `record_keystroke(profile, key, correct, dt) -> Profile`.

- [ ] **Step 1 (red):** tests: round-trip save/load; corrupt JSON → defaults; per-key accuracy aggregates; settings palette enum validated (`match` + `assert_never` on load). Run — FAIL.
- [ ] **Step 2 (green):** implement with Pydantic. Suite PASS. Commit: `feat: profile persistence`.

### Task 5: Arena UI (Textual + pilot E2E)

**Files:**
- Create: `src/tsurv/app.py`, `src/tsurv/arena.py`, reuse `hub.tcss`.
- Test: `tests/test_arena.py` (`run_test` pilot).

**Interfaces:**
- Consumes: Tasks 1–3 pure functions.
- Produces: `TypeSurvivorsApp`, arena renders enemies + words + typing line, 60fps tick via `set_interval(1/60)`.

- [ ] **Step 1 (red):** pilot test: feed word chars for the on-screen grunt → grunt dies, score increases; wrong char → stun flag visible. Run — FAIL.
- [ ] **Step 2 (green):** minimal arena (labels for words, sprite via half-block fallback first; true-pixel TerminalImage behind capability probe). Rerun — PASS.
- [ ] **Step 3 (red):** pilot: window < 80 cols shows guard screen; `NO_COLOR` strips color. Run — FAIL.
- [ ] **Step 4 (green):** implement breakpoints + fallback. Suite PASS. Commit: `feat: playable arena`.

### Task 6: Shell screens + Report Card

**Files:**
- Create: `src/tsurv/screens.py`, `src/tsurv/report.py`. Test: `tests/test_screens.py`, `tests/test_report.py`.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: menu/practice/shop/settings/pause/death screens; `render_report(run: RunSummary) -> str` with WPM sparkline (▁▂▃▄▅▆▇), weakest-3-keys row, trend delta.

- [ ] **Step 1 (red):** `render_report` unit test pins sparkline for fixed WPM series + weakest keys order. Run — FAIL.
- [ ] **Step 2 (green):** implement report. PASS.
- [ ] **Step 3 (red):** pilot: death → recap → shop → restart reaches arena in ≤3 actions; suspend writes checkpoint, resume restores wave. Run — FAIL.
- [ ] **Step 4 (green):** implement screens + checkpoint. Suite PASS. Commit: `feat: shell and report card`.

### Task 7: Juice, telegraphs, calibration, emblem pass

**Files:**
- Modify: `arena.py`, `screens.py`. Assets: pixel-letter emblem redraw.
- Test: `tests/test_juice.py` (unit on timings) + pilot spot-checks.

**Interfaces:**
- Consumes: all above. Produces: final feel + guided wave-1 calibration writing base WPM to profile.

- [ ] **Step 1 (red):** unit tests: telegraph duration ≥200ms before leak damage; bar-break triggers knockback flag + hit-stop window. Run — FAIL.
- [ ] **Step 2 (green):** implement shake/hit-stop/flash/particles/slow-mo + guided wave. Suite PASS.
- [ ] **Step 3:** full CI gate + `visual-qa` pass on arena/menu/report. Fix, commit: `feat: juice and calibration`.

## Self-review

- Spec coverage: every DESIGN.md §2 line maps to Tasks 1–7 (economy→3, coaching→4+6, shell→6, palette/shapes→5+tcss). Boss corruption chunking covered in Task 1 + 2. Emblem pass in Task 7.
- Steps each yield one reasonable artifact; no bodies needed (formulas pinned by spec values in tests).
- Types flow one way: `Word` → combat → items → screens. No renames across tasks.
- Proportion: plan ~150 lines vs spec ~100 — acceptable, interface-heavy by design.
