# TYPE SURVIVORS — Design Doc (approved spec → build)

> Status: DRAFT — needs your approval before any game code is written.

## 1. What it is
Top-down 2D radial typing-survivors for the terminal. Daemon invasion, endless,
stationary Sanctuary Core at center, enemies converge from edges. Type words to
kill. Boss every 5 waves. Chase score, survive, get faster.

## 2. Locked decisions
- Endless + timed waves (survive clock → checkpoint + breather); boss waves end on boss kill. Boss every 5 waves.
- Stationary turret. Type-first-letter to lock target; 2nd letter disambiguates; Esc retargets.
- Adaptive: rolling WPM (last 20 words) drives spawn interval × clamp(0.6–1.6);
  word tier gated by wave + WPM. Targets ~90% edge.
- Typo = 0.6s gun-jam stun + streak reset. No HP loss on typo.
- Enemy leak = HP damage. Streak x8+ grants 1s shield. Second Wind revives once at 50%.
- Items typing-only, 5 pool (Blood Vial +30HP, Second Wind, Frost Veil 5s slow,
  Chain Spark 3-kill arc, NOVA screen-clear charged by 30s at 95%+). Grab by typing.
  Economy: 1/boss + 10% elites.
- Boss = authored sentence pools, chunked word-by-word. N HP bars (Boss1=2, +1 per boss).
  Emptying a bar = knockback blast (clears grunts, staggers boss, next bar faster +
  next corruption). Corruption ladder: clean → reversed → glitch/shrink → rot13+fake.
- Score = WPM × streak.
- Engine: Python + Textual + Rich truecolor (256 + NO_COLOR fallbacks).
  Sprites: true pixels via kitty/sixel/iTerm2, half-block fallback.
- Sound: bleeps (kill tick, boss roar). Palette: Blood Neon Void (locked).
- Colorblind: shape + icon per enemy + protan/deutan/tritan palette modes.
- FTUE: guided wave 1 + WPM calibration, then unleash.
- Retention: meta shop (run gold → permanent starting perks).
- Coaching: per-keystroke stats, post-run Report Card (WPM graph, acc, consistency,
  char stats, weakest-3-keys, trend vs history), practice mode targets weakest keys.
  Coaching lives in report + practice, never mid-horde.
- Shell: full start menu, settings (palette/sound/bold/shake), pause P/Esc,
  suspend/resume checkpoints each wave start, full JSON profile (XDG), death →
  recap + WPM graph → shop → restart in 3 keypresses.

## 3. Enemies (all shipped as 48×48 PNGs in assets/, 2 idle frames + hit flash)
- Grunt Imp (violet #952CF5): straight approach + sine wobble, rears up 200ms before lunge.
- Splitter Mite (orange #FF7A00): fast zigzag dart + spin, vibrates before dash, pops into 2 minis.
- Shielded Hex (blue #24AEEB): slow unstoppable, knockback-resistant, shield flares, needs 2 words.
- Overlord Boss (blood #FF2A2A + gold): hovers + strafes, inhales on phase change, lunges.
- Sanctuary Core (green #39FF6A): the player. HP ring.
- Shell: bg_void tile, bg_boss blood variant, emblem keycap, vignette, hub.tcss.
  (Emblem `T` glyph gets a pixel-letter pass during build.)

## 4. Words (downloaded, verified, in words/)
- english_1k (1000) / 5k (5000) / 10k (9944) / code_python (174) / code_js (126) /
  google10k frequency (9884 lines). Local, zero runtime download.
- Tiers: T1 3–5ch → T2 5–8 → T3 9+ → code biome → boss phrases.
- Per-spawn constraints: not on screen, no repeat within 30, max 2 shared initials,
  swear-filter pass.

## 5. Feel / UI
- 60fps loop, eased movement (in_out_cubic), trauma shake, ~80ms hit-stop on bar break,
  white flash, one-shot particles, streak-x8 slow-mo 0.5s + gold shockwave.
- Layout: top bar (HP/WPM/streak/wave/acc) → arena (sprites + word labels) →
  typing line (green typed, gold next-char) → boss bars top-center, item pings right edge.
- Scaling: ≥120×30 full, 80×24 compact, <80 guard. Silhouette-first identity,
  attributable failure (every leak names its killer), unique telegraphs, color on
  mechanics only.

## 6. Non-goals (v1)
Multiplayer, sound beyond bleeps, non-English words, story campaign, mobile.

## 7. Change log
- v0.1: research + Q&A locks. v0.2: systems + assets. v0.3 (this): doubt round
  (palette, boss cadence, timed waves, economy) + coaching + shell visuals.
