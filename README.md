# Type Survivors (CLI)

A typing-survivors terminal game. Enemies converge on your Sanctuary Core — type their words to kill them before they leak through. Boss every 5 waves, endless scaling, meta shop, synth bleeps.

## Install

```bash
pip install type-survivors-cli
```

Requires Python 3.13+. True-pixel PNG sprites on kitty/ghostty/WezTerm (kitty protocol), Windows Terminal ≥ 1.22 / foot / xterm (sixel), and iTerm2 — auto-detected, with a half-block fallback everywhere else.

## Play

```bash
type-survivors
```

Type the word on an enemy to target and damage it. `Esc` retargets. Widen to 80+ columns.

## Notes

- Sound needs a player: PipeWire/Pulse (`pw-play`/`paplay`/`aplay`) or macOS `afplay`. Silence without one is normal.
- Progress and profiles live under your platform data dir (`~/.local/share/type-survivors` on Linux).
