"""Type Survivors sprites — hand-authored, cell-safe, MIT (ours).
Design rules applied: silhouette-first, value-before-hue (>=2 steps vs bg #0B0B12),
3-5 rows max, 1 identity color per enemy, 2-frame idle + 1 hit flash, quarter-block
shading only, glyphs limited to wide-coverage set (fallback map included).
"""
# fg colors from Blood Neon Void palette
VOID = "#0B0B12"
BONE = "#CACACA"
GRUNT = "#952CF5"
SPLIT = "#FF7A00"
HEXB = "#24AEEB"
BOSS = "#FF2A2A"
GOLD = "#FFD23F"
HPOK = "#39FF6A"

# Fallback if font misses a glyph: replace in renderer
FALLBACK = {"◎": "O", "♛": "W", "◣": "<", "◢": ">", "⁂": "*", "⬢": "#", "◆": ">", "●": "o", "█": "#", "▓": "#", "▒": ".", "░": "."}

SPRITES = {
    # MC: sanctuary core — wide base, high contrast ring, pulses
    "core_idle": [
        "  .-~~~-.  ",
        " /  ◎◎◎  \\ ",
        "(  \\HP/  )",
        "  '-...-'  ",
    ],
    "core_hurt": [
        "  .-~~~-.  ",
        " /  ×× ×  \\ ",
        "(  \\HP/  )",
        "  '-...-'  ",
    ],
    # Grunt Imp: horns + eyes, 3 wide, bobs (2 frames) — legs alternate, clear motion
    "grunt_a": [" (ᵔДᵔ) ", " /|V|\\ "],
    "grunt_b": [" (ᵔДᵔ) ", " /|v|\\ "],
    "grunt_c": [" (ᵔДᵔ) ", "  |V|  "],
    "grunt_hit": [" (×Д×) ", " /|V|\\ "],
    # Splitter Mite: star burst, splits on death
    "mite_a": ["  ⁂  ", " ⁂⁂⁂ ", "  ⁂  "],
    "mite_b": ["   ⁂ ", " ⁂⁂⁂ ", " ⁂   "],
    # Shielded Hex: box shield pulses (closed/open), needs 2 words
    "hex_a": [" ┌───┐ ", " │⬢⬢⬢│ ", " └───┘ "],
    "hex_b": [" ┌─ ─┐ ", " │⬢⬢⬢│ ", " └───┘ "],
    # Boss Overlord: 5 rows, crown + eyes, 2 idle frames (crown tilt) + enrage
    "boss_a": [
        "   ♛ ♛ ♛   ",
        "  (◣_◢_◣)  ",
        " /|█████|\\ ",
        "  |●   ●|  ",
        "  \\VVV/   ",
    ],
    "boss_b": [
        "  ♛ ♛ ♛    ",
        "  (◣_◢_◣)  ",
        " /|█████|\\ ",
        "  | ● ● |  ",
        "  \\VVV/   ",
    ],
    "boss_hit": [
        "   ♛ ♛ ♛   ",
        "  (×_×_×)  ",
        " /|█████|\\ ",
        "  |×   ×|  ",
        "  \\VVV/   ",
    ],
    # FX: blood burst 3 frames, all 3x3, shrink + fade
    "fx_blood": [[" ░ ", "░█░", " ░ "], ["▒▒▒", "▒█▒", "▒▒▒"], [" . ", ". .", " . "]],
    "fx_ring": [["  ___  ", " /   \\ ", " \\___/ "], ["   _   ", "  / \\  ", "  \\_/  "]],
}

COLORS = {"core": HPOK, "grunt": GRUNT, "mite": SPLIT, "hex": HEXB, "boss": BOSS, "gold": GOLD, "bone": BONE}

if __name__ == "__main__":
    for name, art in SPRITES.items():
        print(f"== {name} ==")
        frames = art if isinstance(art[0], list) else [art]
        # mypy: art may be list[str] or list[list[str]]
        if isinstance(art[0], str):
            print("\n".join(art))  # type: ignore
        else:
            for f in art:  # type: ignore
                print("\n".join(f))
                print("---")
        print()
