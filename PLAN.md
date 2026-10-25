# TYPE SURVIVORS (CLI) — Plan v0.2 (Locked decisions + systems)

> Status: ALL CORE DECISIONS LOCKED. Engine Python Textual, sound bleeps, endless daemon invasion.

## 1. Locked (your picks)
- Typing survivors: enemies approach, type to fight. Bosses = multi-bar sentence battles.
- Endless, boss every 5 waves, chase score + survive. Stationary turret, type-to-target.
- Adaptive (starts easy, ends brutal, tracks WPM). Typo = stun jam 0.6s + streak reset, no HP loss.
- Items typing-only (5 pool, grab by typing). Boss = sentences, bars scale 2 + wave/5, knockback per bar, corruption ladder.
- Engine Python + Textual + Rich truecolor. Sound: bleeps. Barely-survive chaos every 60s.
- Palette "Blood Neon Void" + 15 hand-made PNG sprites in assets/ (kitty/sixel true pixels, half-block fallback).

## 2. Research summary
- Games: ZType, Typing of the Dead, Glyphica, WORDFALL, typense (we beat it with bosses + true pixels).
- Animation: 60fps set_interval(1/60) + reactive HP/time; animate() in_out_cubic; trauma shake; hit-stop ~80ms on bar break; white flash overlay; one-shot particle bursts. 2-frame idle 4fps, 80ms hit-flash, 3-frame death, boss stagger + knockback ring, streak-x8 slow-mo 0.5s.
- Word store DOWNLOADED + verified in words/: english_1k 1000, english_5k 5000, english_10k 9944, code_python 174, code_js 126, google10k frequency 9884 lines. Local, zero runtime download.

## 3. Systems (how difficulty / streak / UI work)
- Difficulty: rolling WPM (last 20 words). Spawn interval = base * clamp(ref_wpm/player_wpm, 0.6, 1.6). Word tier = wave + wpm gate (T1 3-5 -> T2 5-8 -> T3 9+ -> code biome). Selection constraints per spawn: no word already on screen, no repeat within 30 spawns, max 2 shared initials on screen, swear-filter pass. Boss sentences from authored pools, chunked word-by-word. Corruption ladder: clean -> reversed -> glitch/shrink -> rot13+fake. Targets ~90% edge.
- Enemy leak = HP damage. Streak x8+ grants 1s shield. Second Wind revives once at 50%.
- Streak: score x = streak; x4 Frost slow 3s; x8 slow-mo + gold shockwave; x16 Chain Spark arcs 3 kills. NOVA charged by 30s at 95%+ accuracy, clears screen.
- UI: top-down 2D radial arena, Sanctuary Core at center; enemies spawn at edges, converge inward; distance = threat. Top bar HP/WPM/streak/wave/accuracy, center arena (PNG sprites + word labels), bottom typing line w/ gold next-char underline, boss multi-bars top-center, item pings right edge, damage vignette flash. Scaling: >=120x30 full, 80x24 compact, <80 guard; truecolor -> 256 -> NO_COLOR mono.
- Movement anims: grunt straight approach + sine wobble + leg bob; mite fast zigzag dart + spin, pops into 2 minis; hex slow unstoppable + shield pulse, knockback-resistant; boss hovers + strafes, lunges on phase change. All moves eased (in_out_cubic), 200ms white telegraph before lunges/leaks, knockback = damped-sine pushback, deaths = burst + fade.

## 3b. Locked audit decisions (expert review round 1)
- Colorblind: shapes + icons per enemy + palette modes for protan/deutan/tritan (never color-only identity).
- Retention: meta shop — run gold buys permanent starting perks (VS-style PowerUps).
- FTUE: guided first wave + WPM calibration, then unleash.
- Target clash: type-to-disambiguate (2nd letter picks), Esc retargets.

## 3c. Visual language + UX (researched: League clarity, Hades attributable failure, Dark Souls telegraph anatomy, Cogmind readability, MUD UI rules)
- Silhouette-first identity: grunt = horned, mite = spiked ball, hex = box, boss = big crowned — readable as pure shadow at 10+ cells.
- Hierarchy: nearest/leaking enemy pulses brightest; boss > elite > grunt; kill FX small, bar-break FX big. Noise budget: small events quiet, big events loud.
- Attributable failure: every leak flashes WHICH enemy + its word remnant; death screen names killer + WPM graph so deaths feel earned.
- Telegraphs: unique 200ms white wind-up per enemy (grunt rears, mite vibrates, hex shield flares, boss inhales) before lunge/leak; bigger damage = longer tell.
- Terminal readability: words semibold bone on void, typed prefix green, gold next-char; boss sentences chunked word-by-word, never a wall; bold-thickness option; color only on mechanics (words/HP), never flavor prose.

## 3e. Coaching — game makes you faster (keybr + Monkeytype model)
- Track every keystroke: per-key accuracy + timing stored in profile across runs (keybr-style per-key stats).
- Post-run Report Card: WPM-over-time graph (block-char sparkline ▁▂▃▄▅▆▇), accuracy, consistency % (steadiness), char stats (correct/incorrect/extra/missed), weakest-3-keys heatmap row, best streak, killer recap, trend sparkline vs your run history with delta vs average.
- Practice mode auto-targets weakest keys: spawns words heavy in your worst letters until they stop being worst (keybr lesson loop). Settable target WPM with progress-to-goal.
- Coaching lives in report + practice, never as mid-horde popups (noise budget).

## 3d. Shell + persistence (locked)
- Start UI (full menu): Title w/ animated logo, Start Run, Practice (no-death sandbox), How to Play, Meta Shop, Settings (palette mode protan/deutan/tritan, sound on/off, bold readability, screen-shake toggle), Quit.
- Returning player: full profile in local JSON (XDG data dir): gold wallet, shop unlocks, hiscores, settings, run stats, calibrated base WPM. First boot probes terminal (size, truecolor/256/mono, kitty/sixel) and stores capability.
- Mid-run: auto-checkpoint each wave start; Suspend/Resume restores exact wave; quitting otherwise banks earned gold. Pause on P/Esc with resume/settings/quit. Death -> killer recap + WPM graph -> shop -> restart in 3 keypresses.
- Milestones replace victory: boss-kill toasts, wave banners every 5, streak callouts.

## 3f. Final locks (doubt round)
- Palette: Blood Neon Void locked. Boss every 5 waves. Waves are TIMED (survive the clock -> checkpoint + breather); boss waves end on boss kill. Economy: 1 item/boss + 10% elites, NOVA 30s at 95%+.
> STATUS: EVERYTHING LOCKED. No open questions. Next: DESIGN.md -> approval -> build plan -> code.

## 4. Next step
Write DESIGN.md for your approval, then implementation plan (writing-plans skill). No game code until you approve DESIGN.md.
