"""Generate high-quality pixel art sprites for the Main Character (MC) Hero.

Design: The Void Slayer / Arcane Battlemage
- Hooded cowl with glowing cyan ethereal eyes
- Dark steel plate armor with brass filigree
- Glowing chest runic power core
- Flowing royal purple tattered battle cape
- Ornate golden crescent war-staff with floating gem in right hand
- Crackling arcane flame orb in left hand
- 32-bit true RGBA alpha transparency
"""

from pathlib import Path
from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def draw_hero_sprite(frame: int = 0, *, hit: bool = False) -> Image.Image:
    """Render one 48x48 RGBA frame of the MC Hero."""
    im = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    dy = -1 if frame == 1 else 0

    c_hood_dark = (18, 16, 26, 255)
    c_hood_mid = (36, 32, 52, 255)
    c_hood_light = (58, 52, 82, 255)
    c_shadow = (10, 8, 16, 255)
    c_cape_dark = (28, 14, 44, 255)
    c_cape_mid = (50, 24, 76, 255)
    c_cape_light = (82, 38, 122, 255)
    c_gold = (212, 175, 55, 255)
    c_gold_bright = (255, 220, 100, 255)
    c_steel = (65, 68, 88, 255)
    c_steel_light = (110, 115, 142, 255)
    c_sash = (168, 34, 64, 255)
    c_sash_light = (217, 46, 83, 255)
    c_cyan_glow = (0, 255, 255, 255)
    c_cyan_bright = (200, 255, 255, 255)
    c_white = (255, 255, 255, 255)
    c_wood = (74, 55, 40, 255)
    c_magic_purple = (157, 78, 221, 255)
    c_magic_bright = (224, 170, 255, 255)

    if hit:
        c_hood_dark = (120, 30, 40, 255)
        c_hood_mid = (180, 50, 60, 255)
        c_hood_light = (255, 120, 130, 255)
        c_cape_dark = (100, 20, 30, 255)
        c_cape_mid = (160, 40, 50, 255)
        c_cyan_glow = (255, 80, 80, 255)
        c_cyan_bright = (255, 200, 200, 255)
        c_magic_purple = (255, 100, 100, 255)

    # 1. Flowing Cape (Back Layer)
    cape_spread = 2 if frame == 1 else 0
    for y in range(18 + dy, 43 + dy):
        width_f = int(6 + (y - (18 + dy)) * 0.45) + (1 if frame == 1 and y % 3 == 0 else 0)
        x1 = 24 - width_f - cape_spread
        x2 = 24 + width_f
        if y > 40 + dy and (x1 + y) % 3 == 0:
            continue
        d.line([(x1, y), (x2, y)], fill=c_cape_dark)
        d.line([(x1 + 1, y), (x1 + 3, y)], fill=c_cape_mid)
        d.point((x1 + 2, y), fill=c_cape_light)

    # 2. Staff Shaft
    staff_x = 36
    d.line([(staff_x, 10 + dy), (staff_x, 43 + dy)], fill=c_wood, width=2)
    d.line([(staff_x - 1, 12 + dy), (staff_x - 1, 41 + dy)], fill=(45, 32, 22, 255))
    d.line([(staff_x + 1, 11 + dy), (staff_x + 1, 42 + dy)], fill=(110, 85, 62, 255))

    # 3. Armored Legs & Boots
    d.rectangle([18, 35 + dy, 22, 43 + dy], fill=c_steel)
    d.rectangle([26, 35 + dy, 30, 43 + dy], fill=c_steel)
    d.rectangle([17, 41 + dy, 22, 43 + dy], fill=(30, 30, 40, 255))
    d.rectangle([26, 41 + dy, 31, 43 + dy], fill=(30, 30, 40, 255))
    d.point((19, 37 + dy), fill=c_steel_light)
    d.point((27, 37 + dy), fill=c_steel_light)

    # 4. Torso & Armored Robes
    for y in range(20 + dy, 36 + dy):
        tw = int(6 + (y - (20 + dy)) * 0.2)
        d.line([(24 - tw, y), (24 + tw, y)], fill=c_hood_dark)
    d.polygon([(20, 20 + dy), (28, 20 + dy), (27, 28 + dy), (21, 28 + dy)], fill=c_steel)
    d.polygon([(21, 21 + dy), (27, 21 + dy), (26, 27 + dy), (22, 27 + dy)], fill=c_steel_light)

    # Arcane chest core
    d.ellipse([23, 22 + dy, 25, 24 + dy], fill=c_cyan_glow)
    d.point((24, 23 + dy), fill=c_white)

    # Sash & Belt
    d.rectangle([18, 29 + dy, 30, 31 + dy], fill=c_sash)
    d.point((24, 30 + dy), fill=c_gold_bright)
    d.rectangle([23, 29 + dy, 25, 31 + dy], fill=c_gold)
    d.line([(22, 32 + dy), (22, 37 + dy)], fill=c_sash_light)

    # 5. Pauldrons
    d.ellipse([14, 16 + dy, 20, 22 + dy], fill=c_steel)
    d.ellipse([15, 17 + dy, 19, 21 + dy], fill=c_steel_light)
    d.arc([14, 16 + dy, 20, 22 + dy], 0, 360, fill=c_gold)

    d.ellipse([28, 16 + dy, 34, 22 + dy], fill=c_steel)
    d.ellipse([29, 17 + dy, 33, 21 + dy], fill=c_steel_light)
    d.arc([28, 16 + dy, 34, 22 + dy], 0, 360, fill=c_gold)

    # 6. Hood & Cowl (Head)
    d.polygon([(24, 5 + dy), (17, 13 + dy), (18, 19 + dy), (30, 19 + dy), (31, 13 + dy)], fill=c_hood_mid)
    d.polygon([(24, 6 + dy), (18, 13 + dy), (19, 18 + dy), (29, 18 + dy), (30, 13 + dy)], fill=c_hood_dark)
    d.line([(23, 5 + dy), (25, 5 + dy)], fill=c_hood_light)
    d.line([(21, 8 + dy), (27, 8 + dy)], fill=c_hood_light)
    d.polygon([(20, 12 + dy), (28, 12 + dy), (27, 18 + dy), (21, 18 + dy)], fill=c_shadow)

    # Piercing glowing eyes
    eye_lx, eye_rx = 22, 26
    eye_y = 14 + dy
    d.rectangle([eye_lx, eye_y, eye_lx + 1, eye_y], fill=c_cyan_glow)
    d.point((eye_lx, eye_y), fill=c_white)
    d.rectangle([eye_rx - 1, eye_y, eye_rx, eye_y], fill=c_cyan_glow)
    d.point((eye_rx, eye_y), fill=c_white)
    if frame == 1:
        d.point((eye_lx - 1, eye_y - 1), fill=c_cyan_glow)
        d.point((eye_rx + 1, eye_y - 1), fill=c_cyan_glow)

    # 7. Hands & Magic
    hand_l_x, hand_l_y = 13, 24 + dy
    d.rectangle([hand_l_x, hand_l_y, hand_l_x + 2, hand_l_y + 2], fill=c_steel)
    orb_y = hand_l_y - 6
    orb_r = 3 if frame == 1 else 2
    d.ellipse([hand_l_x - orb_r, orb_y - orb_r, hand_l_x + orb_r + 1, orb_y + orb_r + 1], fill=c_magic_purple)
    d.ellipse([hand_l_x - 1, orb_y - 1, hand_l_x + 1, orb_y + 1], fill=c_magic_bright)
    d.point((hand_l_x, orb_y), fill=c_white)
    spark_off = 2 if frame == 1 else 0
    d.point((hand_l_x - 3 + spark_off, orb_y - 3), fill=c_cyan_bright)
    d.point((hand_l_x + 3 - spark_off, orb_y - 2), fill=c_gold_bright)

    hand_r_x, hand_r_y = 35, 25 + dy
    d.rectangle([hand_r_x - 1, hand_r_y, hand_r_x + 2, hand_r_y + 2], fill=c_steel)

    # 8. Staff Head Relic
    crescent_cx, crescent_cy = staff_x, 9 + dy
    d.arc([crescent_cx - 5, crescent_cy - 5, crescent_cx + 5, crescent_cy + 5], 30, 330, fill=c_gold, width=2)
    d.point((crescent_cx, crescent_cy - 4), fill=c_gold_bright)
    cry_r = 3 if frame == 1 else 2
    d.polygon([
        (crescent_cx, crescent_cy - cry_r),
        (crescent_cx + cry_r, crescent_cy),
        (crescent_cx, crescent_cy + cry_r),
        (crescent_cx - cry_r, crescent_cy),
    ], fill=c_cyan_glow)
    d.point((crescent_cx, crescent_cy), fill=c_white)
    orbit_angle = 1 if frame == 1 else -1
    d.point((crescent_cx + 4 * orbit_angle, crescent_cy - 3), fill=c_gold_bright)
    d.point((crescent_cx - 4 * orbit_angle, crescent_cy + 2), fill=c_cyan_bright)

    if hit:
        d.line([(14, 12), (34, 32)], fill=(255, 255, 255, 220), width=1)
        d.line([(34, 14), (16, 36)], fill=(255, 80, 80, 220), width=1)
        d.point((24, 23), fill=c_white)

    return im


def generate_all() -> None:
    """Write all hero sprites to assets directory."""
    im0 = draw_hero_sprite(0)
    im1 = draw_hero_sprite(1)
    imh = draw_hero_sprite(0, hit=True)

    im0.save(ASSETS_DIR / "core_0.png")
    im1.save(ASSETS_DIR / "core_1.png")
    imh.save(ASSETS_DIR / "core_hit.png")
    print(f"Hero sprites saved to {ASSETS_DIR}: core_0.png, core_1.png, core_hit.png")


if __name__ == "__main__":
    generate_all()
