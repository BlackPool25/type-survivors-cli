"""HUB + shell visuals: arena bg tiles, boss variant, emblem, menu stylesheet.
All original, generated locally with Pillow. Tiles tile seamlessly (noise wraps).
Usage: python3 gen_shell.py  -> writes assets/*.png + hub.tcss
"""
import random
from PIL import Image, ImageDraw

A = "type-survivors-cli/assets"
random.seed(666)

def tile(base, accent, n_stars, path, size=128):
    img = Image.new("RGB", (size, size), base)
    px = img.load()
    br, bg, bb = int(base[1:3], 16), int(base[3:5], 16), int(base[5:7], 16)
    for _ in range(n_stars):  # wrap-safe: skip edges so tiling is seamless
        x, y = random.randint(2, size - 3), random.randint(2, size - 3)
        d = random.randint(6, 26)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                r = max(0, min(255, br + d)) if False else None
                px[x + dx, y + dy] = (min(255, br + d), min(255, bg + d), min(255, bb + d))
    # faint grid veins (arena feel), wrap-safe
    dr = ImageDraw.Draw(img)
    ar, ag, ab = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    for i in range(0, size, 32):
        dr.line([(i, 0), (i, size)], fill=(ar // 6, ag // 6, ab // 6))
        dr.line([(0, i), (size, i)], fill=(ar // 6, ag // 6, ab // 6))
    img.save(path)

def emblem(path, size=96):
    """Possessed keycap: bone key, violet glow glyph, blood cracks."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 10
    d.rounded_rectangle([m, m, size - m, size - m], radius=14, fill=(21, 21, 34, 255), outline=(149, 44, 245, 255), width=3)
    d.rounded_rectangle([m + 10, m + 10, size - m - 10, size - m - 10], radius=8, fill=(11, 11, 18, 255), outline=(60, 60, 90, 255), width=1)
    cx, cy = size // 2, size // 2
    d.text((cx - 14, cy - 20), "T", fill=(202, 202, 202, 255))  # shortcut: default font placeholder
    # blood cracks from corners
    for x0, y0, x1, y1 in [(m, m + 20, m + 22, m + 34), (size - m, size - m - 20, size - m - 22, size - m - 6)]:
        d.line([(x0, y0), (x1, y1)], fill=(255, 42, 42, 255), width=2)
    # glow eyes above glyph
    d.ellipse([cx - 16, cy + 12, cx - 8, cy + 20], fill=(255, 210, 63, 255))
    d.ellipse([cx + 8, cy + 12, cx + 16, cy + 20], fill=(255, 210, 63, 255))
    img.save(path)

def vignette(path, w=120, h=30):
    """Darkened-edge overlay sample (runtime code regenerates at terminal size)."""
    img = Image.new("RGB", (w * 8, h * 16), (11, 11, 18))
    px = img.load()
    W, H = img.size
    for y in range(H):
        for x in range(W):
            nx, ny = x / W - 0.5, y / H - 0.5
            t = min(1.0, (nx * nx + ny * ny) * 2.2)
            f = 1.0 - 0.75 * t * t
            px[x, y] = (int(11 * f), int(11 * f), int(18 * f))
    img.save(path)

CSS = """/* Blood Neon Void — HUB + menus */
$void: #0B0B12; $panel: #151522; $bone: #CACACA;
$hp: #39FF6A; $warn: #FFD23F; $blood: #FF2A2A;
$grunt: #952CF5; $split: #FF7A00; $elite: #24AEEB; $gold: #FFD23F;

Screen { background: $void; color: $bone; }
#title { color: $blood; text-style: bold; }
#subtitle { color: $grunt; }
Menu Button { background: $panel; color: $bone; border: solid $grunt; }
Menu Button:focus { background: $grunt; color: #FFFFFF; }
#hiscore { color: $gold; } #gold { color: $gold; text-style: bold; }
#hpbar { color: $hp; } #bossbar { color: $blood; }
TypingLine { background: $panel; } .typed { color: $hp; } .next { text-style: underline; color: $gold; }
"""

if __name__ == "__main__":
    tile("#0B0B12", "#952CF5", 260, f"{A}/bg_void.png")
    tile("#140B0E", "#FF2A2A", 200, f"{A}/bg_boss.png")   # blood-tinted boss arena
    emblem(f"{A}/emblem.png")
    vignette(f"{A}/vignette_sample.png")
    open("type-survivors-cli/hub.tcss", "w").write(CSS)
    print("shell assets + hub.tcss written")
