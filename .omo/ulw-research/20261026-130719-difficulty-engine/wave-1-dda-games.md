# wave-1-dda-games.md — digest of ses_e888ae06affeTuyNg6t90AtTfw

Excellent report. Portable findings:
- L4D Director: NOT stat-scaling but population filter; per-survivor Intensity
  (+damage/incap, decay not-while-engaged); 4-state FSM (Build Up / Sustain
  Peak 3-5s / Peak Fade / Relax 30-45s); mobs 90-180s; bosses exempt from
  pacing; economy (items) separate from threat. Failure: pure randomness
  exhausted players → landmarks + countable structure added.
- RE4: invisible rank 1-10 (signals: acc/damage/deaths/kills/inventory);
  remake DA points + rank bands per base difficulty. Critique: discovered =
  patronizing; death-farming exploit; God Hand visible meter praised instead.
- Mario Kart: rank-weighted items + per-frame CPU speed regulation vs gap;
  GameAIPro rule — modify *skill* first, *power* only at extremes; dead zone
  around player; disable at race start/lapped.
- Forza: behavioral-cloning Drivatars → FM2023 "no cheats, no rubber banding"
  (26k laps/track, ~19 lines, tiers 1-8 via grip/power); binary pedal +
  raceline limits caused demolition-derby + hidden rubber-band compensation.
- Hades Heat: 15 modular conditions, Heat costs, per-weapon bounties,
  +1-at-a-time optimal climb; transparent opt-in = perceived fair.
- Dead Cells BC: coarse discrete rule changes; Update 19 smoothed curve +
  Assist Mode after del Toro complaint.
- VS: scripted wave tables (~90s switches) + Curse (uncapped player slider,
  formula new_interval = base/(1+Curse)); Curse = XP/gold tradeoff.
- Synthesis: invisible DDA must stay invisible; separate pacing from power;
  skilled players need opt-out/visible rank (God Hand meter > forced adap).

## EXPAND (queue; most need a typing-game angle to matter here)
- Visible-meter DDA (God Hand) numbers/quotes — relevant to Q: show "FOCUS"
  rank? Open.
- Pity-RNG (XCOM 120% display + miss-streak pity) — portable to typo
  forgiveness; open.
- StS Ascensions granularity — open, lower priority.
- Anti-exploit rules (RE4 death-farming, speedrun bans) — relevant: idle
  farming already clamped (3.2s); open.
- Versus Flow Limit / MK fairness — only if leaderboards planned; park.

## CLAIMS (non-code; 1 high-risk)
- High-risk: "Visible opt-in difficulty perceived fairer than invisible DDA"
  — needs counter-search before synthesis asserts it.
- High-risk: "Dead Cells 5BC requires cursed chests" — irrelevant here; drop.
