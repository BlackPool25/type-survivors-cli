# wave-1-codebase-audit.md — digest of ses_e888ae06fffe9L1YlehaU0nvmd

Thorough audit with file:line + formulas. Key measured facts:
- REF_WPM=40 fixed; spawn gap = 2.0 * clamp(40/player, 0.6, 1.6);
  player WPM from word-completion rate (last ≤20 kill timestamps), idle→3.2s.
- Wave size 1+level/2 cap 8; radius grows 0.5/wave (time-to-impact grows!).
- Speeds: MITE 1.6 (L1 impact 3.1s), GRUNT 1.0 (5.0s), HEX 0.6 unused live.
- Live loop spawns only GRUNT/MITE/BOSS (every 5th); HEX/ELITE/CODE unused.
- Tiers live: T1 (wave≤1) else T2; mercy downgrades one tier on 3 stuns/20s,
  recovery 10 keys @0.8 acc; mercy never arms on boss waves.
- Skill measurement: per-key EMA (α=0.1, keybr-style), review ladder
  (0/1h/1d/3d/7d/14d, promote ≥0.98/10 attempts), weak-key ×3/overdue ×6
  reweight, boss weak-slot bias 50%. base_wpm measured at wave 2 but
  WRITE-ONLY — never fed back into spawn gap.
- Stun 0.6s on typo; focus reduces to 0.4 max-rank; streak ladder scoring.
- 10-hit death clock (leak=10 @100HP); practice mode no-death drill.
- Suspected dead/suspect: frost_until never slows advance(); NOVA charge
  bookkeeping but no fire effect; rolling_wpm unit mismatch
  (completions/min vs 5-char WPM standard).

## EXPAND markers (all codebase-verifiable by orchestrator)
- LEAD base_wpm write-only → verify via grep base_wpm.
- LEAD frost_until dead → grep frost_until reads.
- LEAD HEX/ELITE/CODE unused live → grep producers.
- LEAD rolling_wpm units → read combat.py:216-227 vs metrics raw_wpm.
- LEAD NOVA unfired → grep nova_armed call sites.
- LEAD mercy boss exemption → confirmed in report (arena.py:372-377).
- LEAD spawn cap plateau L14+ → design question for proposal.
- LEAD ASCII filter narrowing pools → audit corpora.

## CLAIMS: none (codebase worker; claims verified by orchestrator reads).
