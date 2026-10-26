# Plan: adaptive difficulty engine — 2026-10-26

Goal: Kalman-tracked skill rating drives spawn pressure; word dealer trains
weak keys; director states pace waves; wave 1 is fail-soft; rank is visible.
Decisions: full engine / train weaknesses / visible rank / gentle then adapt.

## Slices (each: RED test → implement → full suite → ruff)
1. Honest speedometer (combat.py): per-kill service-time WPM replaces
   completions/min; spawn_interval takes chars-based WPM; close base_wpm loop.
2. Skill rating (new rating.py): rating + RD (Glicko-lite); update on
   kill-clean vs leak; visible rank tiers for hub/report.
3. Word dealer (words.py): word difficulty = length + weak-key overlap;
   deal near ability; weak keys served at low pressure (train), spared at
   high pressure; T1-short-only wave-1 rails.
4. Director (arena.py/app.py): stress signal (queue depth + HP trend);
   Build/Peak/Relax FSM; authored wave event tables incl. HEX/ELITE/CODE
   debuts; bosses exempt; frost_until actually slows advance (shop honesty).
5. Rank + anti-sandbag (app.py/report): visible rank display; score scales
   with pressure faced so playing down pays less.

## Constraints
- No new deps (stdlib; user lifted the cap but nothing needs it).
- Don't touch menu/CSS/shop files owned by the parallel agent.
- Update tests that pin old units (test_combat rolling, wave-1 tests).
