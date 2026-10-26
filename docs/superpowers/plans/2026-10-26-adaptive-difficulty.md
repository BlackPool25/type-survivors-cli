# Plan: adaptive difficulty engine — 2026-10-26

Goal: Kalman-tracked skill rating drives spawn pressure; word dealer trains
weak keys; director states pace waves; wave 1 is fail-soft; rank is visible.
Decisions: full engine / train weaknesses / visible rank / gentle then adapt.

## Slices (all built; each: RED test → implement → full suite → ruff)
1. [x] Honest speedometer: per-kill service-time WPM; spawn gap takes
   chars-based pace; base_wpm seeds the tick reference.
2. [x] Skill rating (new rating.py): rating + RD (Glicko-lite); one update
   per banked run via bank_run_skill; rank tiers for the hub.
3. [x] Word dealer: difficulty = length + surcharges; deal near ability;
   weak keys served at low strain, spared at high; wave-1 short-only rails.
4. [x] Director: strain FSM (Build/Peak/Relax); HEX/ELITE debut waves;
   bosses exempt; frost slows advance. CODE tier undebuted (deferred).
5. [x] Rank persistence: skill fields on Profile; bank_run folds run pace;
   run start capped at GENTLE_START_WPM; hub footer shows rank.
   Deferred: score scaling with pressure faced (anti-sandbag pay curve).

## Constraints
- No new deps (stdlib; user lifted the cap but nothing needs it).
- Don't touch menu/CSS/shop files owned by the parallel agent.
- Update tests that pin old units (test_combat rolling, wave-1 tests).
