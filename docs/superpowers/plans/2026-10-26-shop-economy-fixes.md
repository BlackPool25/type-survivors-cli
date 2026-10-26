# All-9 Shop/Economy/Persistence Fixes + Balance

## Goal
Wire the dead shop/persistence paths, harden saves, and ship a balanced ranked catalog.

## Architecture
- Pure logic in `screens.py` (catalog, prices, buy/refund/bank), `profile.py` (versioned model, fsync saves), `items.py`/`combat.py`/`arena.py` (rank effect knobs + held inventory).
- `app.py` only wires: load-on-start, save-on-mutate, bank-on-death/quit, starting perks, shop UI refresh.
- `__main__.py`: platformdirs data dir.

## Decisions
- `Profile.shop`: `dict[str, int]` (id -> rank) with list->dict migration validator.
- Rank effects: vitality +10 maxHP x5, focus -0.05s stun x4, frost +1s veil x3, greed +1g/kill x3. Caches stay one-time.
- Held inventory: `ArenaState.held`, cap 3, hotkeys 1-3, overflow auto-applies.
- Bank on death (tick transition) and quit-to-desktop; suspend keeps checkpoint; clear checkpoint on bank.
- Per-keystroke profile updates in-memory only (`save=False`); save on run end/shop/settings.

## Slices (TDD each: failing test -> implement -> suite -> ruff)
1. screens.py: ranked catalog, price_for, buy ranks, refund_all, bank rate param, clear_checkpoint.
2. profile.py: version field, shop migration, fsync+.bak saves.
3. items/combat/arena: veil_bonus, stun_duration, held stow/use, max_hp init.
4. __main__.py: platformdirs + load_profile at startup.
5. app.py: apply/note/bank wiring, _build_arena ranks+held, death/quit hooks, ShopScreen dynamic keys + gold refresh + refund.
6. Full suite + ruff + fresh-venv install check.

## Out of scope
- Difficulty overhaul (deferred, user asked deep-dive later, ML ok).
- Parallel agent's hunks (menus/CSS/banner): surgical edits only, no commit.
