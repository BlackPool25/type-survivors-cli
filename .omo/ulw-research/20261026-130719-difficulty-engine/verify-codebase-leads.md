# verify-codebase-leads.md — orchestrator verification (2026-10-26)

Method: direct reads/greps of src/tsurv. Verdicts:

1. base_wpm write-only — CONFIRMED. `calibrate_base_wpm` measured at
   app.py:1327, stored via `apply_calibration`; only other `base_wpm` reads
   are the `is not None` write-once guard. `spawn_interval` always gets
   REF_WPM=40. Closing this loop is the cheapest personalization win.
2. rolling_wpm unit mismatch — CONFIRMED. combat.py:216 returns
   completions/min; REF_WPM=40 is chars-based. A 40-WPM typist on 4-char
   words completes ~10/min → ratio 4 → clamped to 1.6 → gap stuck at 3.2s
   (slowest) until ~66 completions/min. The adaptive gap is effectively
   binary (idle vs fast), not proportional. Any proposal must fix units
   (chars-based rolling WPM or ref in completions).
3. frost_until dead — CONFIRMED. arena.py: only stored/merged (210, 224,
   238, 427, 462); `advance()` (382) never reads it. Frost Veil's 5s slow
   does nothing to enemy motion.
4. NOVA unfired — CONFIRMED (as a gate). `nova_armed` (app.py:711) has zero
   readers; charge accrues (947) but nothing consumes it. `chain_lightning`
   fires only on CHAIN_SPARK elite drops (1341), independent of the NOVA gate.
5. HEX/ELITE/CODE unused live — CONFIRMED live-loop. `_spawn_foe` deals only
   GRUNT/MITE/BOSS (app.py:1067-1069); HEX art/speed/visuals exist but no
   producer; ELITE only via tests/manual `spawn_wave(kind=)`; CODE pool built
   (words.py:151) but never auto-spawned.
6. Mercy boss exemption — CONFIRMED by worker (arena.py:372-377).

All six are code facts, no further waves needed on this axis.

7. Throughput confounding (sim v1, queue model): completions/min is capped
   by the regulator's own spawn gap, so a throughput-based gap can never
   speed up — it mistakes its own slow spawning for a slow player. All
   typists 15-75 WPM pegged at gap 3.2s. Fix: observe per-kill SERVICE
   time (chars/time per word), which the regulator cannot confound.
