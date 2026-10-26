# Universal true-pixel plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PNG sprites on every terminal with a graphics protocol via par-textual-image auto-detect.

**Architecture:** Extend RendererKind to KITTY|SIXEL|ITERM2|CELLS; probe_renderer delegates to detect_protocol() when env doesn't pin; app mounts TerminalImage for any non-CELLS and force_protocols the detected value.

**Tech Stack:** Python, Textual, par-textual-image, Pillow

**Spec:** brainstorm decision Option A in chat 2026-10-26.

## Global Constraints

- Python >=3.13 (par-textual-image floor).
- No new dependencies.
- TSURV_TRUEPIXEL=0/1 and PAR_TERM_GRAPHICS overrides keep working.

## Review Focus

- Windows Terminal without WT_SESSION set still probes via sixel DA1.
- tmux/ssh stripping env falls back to detect() tty probes, never hangs >200ms.
- halfblock from lib maps to CELLS, never mounts TerminalImage.
- force_protocol only called with kitty|sixel|iterm2.
- Existing kitty terminals unchanged.

---

### Task 1: stage.py universal probe

**Files:**
- Modify: `src/tsurv/stage.py:68-184`
- Test: `tests/test_stage.py`, `tests/test_task10.py`

**Interfaces:**
- Consumes: `par_textual_image.detect_protocol() -> str`
- Produces: `RendererKind.{KITTY,SIXEL,ITERM2,CELLS}`, `RendererKind.true_pixel: bool`, `select_renderer(..., wt_session, lc_terminal)`, `probe_renderer(env, *, detect, query_tty)`

- [ ] **Step 1: Write failing test** `test_par_sixel_selects_sixel` in tests/test_stage.py asserting `select_renderer(par_graphics="sixel").kind is RendererKind.SIXEL`.
- [ ] **Step 2: Run** `uv run pytest tests/test_stage.py::test_par_sixel_selects_sixel -v` Expected: FAIL (SIXEL missing / maps to CELLS).
- [ ] **Step 3: Implement** RendererKind + mapping + env hints + detect() delegation in src/tsurv/stage.py.
- [ ] **Step 4: Run** `uv run pytest tests/test_stage.py tests/test_task10.py -v` Expected: PASS after updating the two stale `PAR_TERM_GRAPHICS=sixel → CELLS` asserts to SIXEL.
- [ ] **Step 5: Commit** `git add src/tsurv/stage.py tests/test_stage.py tests/test_task10.py; git commit -m "feat: universal true-pixel probe"`

### Task 2: app.py mount any true-pixel

**Files:**
- Modify: `src/tsurv/app.py:718,745,1549`
- Test: `tests/test_visuals.py`

**Interfaces:**
- Consumes: `RendererPick.true_pixel` from Task 1
- Produces: TerminalImage mounted + forced for kitty/sixel/iterm2

- [ ] **Step 1: Write failing test** asserting compose mounts TerminalImage when pick is SIXEL (pilot with PAR_TERM_GRAPHICS=sixel).
- [ ] **Step 2: Run** Expected: FAIL (only KITTY mounts).
- [ ] **Step 3: Implement** `true_pixel` swaps + `force_protocol(self._pick.kind.value)` in src/tsurv/app.py; rename `_refresh_kitty` doc to true-pixel (keep name to avoid churn).
- [ ] **Step 4: Run** `uv run pytest tests/test_visuals.py tests/test_task11.py tests/test_task12.py -v` Expected: PASS.
- [ ] **Step 5: Commit** `git add src/tsurv/app.py tests/...; git commit -m "feat: mount sprites on any true-pixel terminal"`
