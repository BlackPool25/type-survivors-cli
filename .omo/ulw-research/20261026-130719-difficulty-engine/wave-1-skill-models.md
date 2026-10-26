# wave-1-skill-models.md — digest of ses_e888ae062ffekFIwS7dABeRXEy

12 searches. Model survey for single-player typing with keystroke signals:
- Elo: O(1), needs outcomes; dynamic-K fixes cold start; no uncertainty.
- Glicko-2: skill + RD + volatility; RD-gated changes ("don't adjust yet,
  still uncertain"); principled cold start (1500/350/0.06); strong fit.
- TrueSkill/2: multiplayer machinery, patent-encumbered to 2029 — skip.
- BKT: per-key/bigram mastery HMM; great for errors, ignores speed; no
  forgetting in vanilla; needs 20-50 attempts/KC.
- IRT 1PL/2PL + CAT: gold-standard selector (max Fisher info at θ̂), needs
  100-1000 pilots/item — unaffordable now; fake with expert tiers.
- Kalman: latent skill + covariance; Q = drift model (warm-up/fatigue);
  large P0 = fast lock-in; best for continuous WPM/latency signals.
  Unifying lens: Elo/Glicko/TrueSkill ≈ approximate Kalmans (arXiv:2104.14012).
- PID: 10-line closed loop on one metric (e.g. hold accuracy ~92%); no
  memory/uncertainty; sandbagging risk.
- Bandits (Thompson ~15 lines): tier picker with in-flow reward; needs
  non-stationary variant for improving players; best as selector atop a
  skill estimate.
- Flow: use as target zone (acc 85-97% + WPM ±15% rolling best + replays),
  not a metric (24 operationalizations, no consensus — Abuhamdeh 2020).
- Worker recommendation: now = player-Elo + item-Elo (or Glicko-2) +
  Kalman WPM → PID/tier selector (~50 lines); next = Thompson tier picker;
  later = per-bigram BKT + IRT bank + CAT.

## EXPAND (queue)
- Response-time IRT (joint ability+latency) — pilot on snippet timings.
- Forgetting-augmented KT for warm-up/fatigue drift.
- Contextual bandits (LinUCB) vs Thompson baseline.
- Flow-proxy validation vs Flow Short Scale self-report.

## CLAIMS (non-code; counter-searches done by worker)
- Glicko-2 cheapest principled cold-start/drift — medium risk (batching
  adaptation). Counter: Elo+dynamic-K nearly matches.
- TrueSkill overkill + encumbered — low risk.
- Kalman unification theorem — low risk (primary: arXiv:2104.14012).
- BKT ignores speed — low risk.
- IRT+CAT needs 100-1000 pilots/item — low risk.
- Flow no consensual operationalization — low risk (primary: Abuhamdeh).
