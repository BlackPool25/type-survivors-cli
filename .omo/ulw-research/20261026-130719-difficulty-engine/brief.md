# ULW-Research: Difficulty Engine — brief

## Core question
What difficulty engine should type-survivors-cli use so that wave 1 is
completable by a hunt-and-peck beginner, the curve stays tense-but-fair for
a 60+ WPM player, shop ranks (vitality/focus/chill/greed) bend the curve
without breaking it, and difficulty adapts to measured typing skill?

## Context carried in
- Wave 1 currently can deal 11-char T1 words with 3.1s-impact mites; too hard.
- REF_WPM=40 calibration exists; rolling-WPM spawn gap; mercy tiers; leak=10dmg.
- Shop: 4 capped rank lines (~+18% power max) + 3 one-shot caches.
- Prior art already surveyed: VS wave tables + curse, L4D AI Director
  stress/relief, ZType levels, Epistory fail-soft, Dead Cells BC, Hades heat.
- User dislikes plain-ASCII fallbacks; PNG path is universal true-pixel now.

## Axes
1. Codebase audit A — current difficulty math (spawn, speed, tiers, mercy, leak).
2. Codebase audit B — shop/persistence interplay (rank power vs curve, calibration).
3. Web — typing-game difficulty (ZType, Epistory, TotD, calibration methods).
4. Web — wave/roguelike directors (VS tables, L4D stress model, Dead Cells BC, Hades heat).
5. Web — adaptive difficulty science (flow theory, DDA, rubber-band studies, churn).
6. Repo dive — real implementations (survivors-like directors, adaptive typing games).

## Scale
Multi-faceted: 2 explore + 3 librarian + 1 browsing + 1 repo-dive (floor 7+).
Lifecycle: single team, then synthesis. Precision demand: medium (design
recommendations, not legal/medical).
</analysis>

## Format gate
PENDING — asked 2026-10-26, awaiting user answer before wave 1.

## Format gate — ANSWERED 2026-10-26
- Deliverable: chat summary (no PDF/DOCX).
- Model weight: best model wins; packaging cost no object.
- Signals: all (pacing + word choice + review); economy stays fixed.
