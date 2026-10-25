"""Game-level sprite generator — real pixel art PNGs, zero license risk.
48x48 per frame, identity palette, dark outline + gradient + glow eyes + rim light.
Renders true pixels via kitty/sixel (par-textual-image) at runtime, half-block fallback.
"""
from PIL import Image, ImageDraw

SIZE = 48
BG = (11, 11, 18, 255)
PAL = {
    "grunt": ((149, 44, 245), (70, 20, 130)),
    "mite": ((255, 122, 0), (130, 55, 0)),
    "hex": ((36, 174, 235), (12, 70, 110)),
    "boss": ((255, 42, 42), (120, 10, 10)),
    "core": ((57, 255, 106), (10, 110, 50)),
    "gold": (255, 210, 63),
}

def canvas():
    return Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

def body(draw, box, c1, c2):
    # vertical gradient body with dark outline
    x0, y0, x1, y1 = box
    draw.ellipse(box, outline=(5, 5, 10, 255), width=3)
    for y in range(y0 + 3, y1 - 2):
        t = (y - y0) / max(1, y1 - y0)
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        draw.line([(x0 + 4, y), (x1 - 4, y)], fill=(r, g, b, 255))
    # rim light left edge
    draw.arc(box, start=100, end=250, fill=(255, 255, 255, 140), width=2)

def eyes(draw, y, gap, glow=(255, 240, 200)):
    cx = SIZE // 2
    for sx in (-gap, gap):
        x = cx + sx
        draw.ellipse([x - 4, y - 5, x + 4, y + 3], fill=(10, 0, 0, 255))
        draw.ellipse([x - 2, y - 3, x + 2, y + 1], fill=glow + (255,))

def horns(draw, color):
    draw.polygon([(8, 18), (14, 4), (18, 18)], fill=color + (255,), outline=(5, 5, 10, 255))
    draw.polygon([(40, 18), (34, 4), (30, 18)], fill=color + (255,), outline=(5, 5, 10, 255))

def crown(draw):
    draw.polygon([(14, 10), (16, 2), (22, 8), (24, 1), (26, 8), (32, 2), (34, 10)],
                 fill=PAL["gold"] + (255,), outline=(80, 50, 0, 255))

def hit_flash(img):
    px = img.load()
    out = img.copy()
    op = out.load()
    for y in range(SIZE):
        for x in range(SIZE):
            r, g, b, a = px[x, y]
            if a > 10:
                op[x, y] = (255, 255, 255, a)
    return out

def make(kind, frame):
    img = canvas()
    d = ImageDraw.Draw(img)
    c1, c2 = PAL[kind] if kind in PAL else PAL["grunt"]
    bob = {0: 0, 1: 2}.get(frame, 0)
    if kind == "core":
        body(d, [10, 10 + bob, 38, 38 + bob], c1, c2)
        eyes(d, 24 + bob, 7, glow=(200, 255, 220))
        d.ellipse([20, 30 + bob, 28, 36 + bob], outline=(255, 255, 255, 200), width=1)
    elif kind == "grunt":
        horns(d, c1)
        body(d, [10, 14 + bob, 38, 40 + bob], c1, c2)
        eyes(d, 26 + bob, 7)
        d.line([(20, 36 + bob), (18, 42 + bob)], fill=(5, 5, 10, 255), width=3)  # legs
        d.line([(28, 36 + bob), (30, 42 + bob)], fill=(5, 5, 10, 255), width=3)
    elif kind == "mite":
        body(d, [14, 14 - bob, 34, 34 - bob], c1, c2)
        eyes(d, 24 - bob, 5)
        for sx, sy in [(-8, 0), (8, 0), (0, -8), (0, 8)]:  # spikes
            d.line([(24 + sx // 2, 24 + sy // 2), (24 + sx, 24 + sy)], fill=c1 + (255,), width=3)
    elif kind == "hex":
        gap = 2 if frame == 1 else 0  # shield pulse
        d.rectangle([8, 12 + bob, 40, 40 + bob], outline=c1 + (255,), width=3)
        d.rectangle([12 + gap, 16 + bob, 36 - gap, 36 + bob], outline=(200, 240, 255, 255), width=1)
        body(d, [16, 18 + bob, 32, 34 + bob], c1, c2)
        eyes(d, 26 + bob, 4)
    elif kind == "boss":
        crown(d)
        horns(d, c1)
        body(d, [6, 12 + bob, 42, 42 + bob], c1, c2)
        eyes(d, 26 + bob, 10, glow=(255, 220, 100))
        d.polygon([(18, 38 + bob), (24, 44 + bob), (30, 38 + bob)], fill=PAL["gold"] + (255,))  # fangs plate
    return img

if __name__ == "__main__":
    import os
    os.makedirs("/home/shreyas/type-survivors-cli/assets", exist_ok=True)
    kinds = ["core", "grunt", "mite", "hex", "boss"]
    n = 0
    for k in kinds:
        for f in (0, 1):
            img = make(k, f)
            img.save(f"/home/shreyas/type-survivors-cli/assets/{k}_{f}.png")
            n += 1
        img = make(k, 0)
        hit_flash(img).save(f"/home/shreyas/type-survivors-cli/assets/{k}_hit.png")
        n += 1
    print(f"wrote {n} PNGs")
