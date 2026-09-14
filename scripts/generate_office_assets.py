"""Generates the AgentMash HQ tileset and the four named agent spritesheets.

Real, original pixel art -- procedurally drawn shapes, not traced or
copied from any existing game, brand, or asset pack. Deliberately simple
(schematic, flat-shaded) rather than detailed: the goal across every
stage of this project has been proving the *systems* work (real tiles,
real collision, real state-driven animation) with honest placeholder
art, not shipping final art.

Stage 2 adds: bed / coffee machine / whiteboard / design-tablet tiles,
small pixel status-icon glyphs, and four distinct character spritesheets
driven by a real, parameterized `AvatarAppearance`-shaped preset per
role (skin/hair/shirt/pants/accessory) -- see
`desktop/src/game/avatars/appearancePresets.ts`, which must stay in sync
with the `PRESETS` dict below.

Run with: python3 scripts/generate_office_assets.py
"""

from PIL import Image, ImageDraw
import pathlib

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "desktop" / "src" / "game" / "assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TILE = 32

# ---------------------------------------------------------------------------
# Tileset: 8 columns x 8 rows of 32x32 tiles = 256x256
# ---------------------------------------------------------------------------
COLS, ROWS = 8, 8
tileset = Image.new("RGBA", (COLS * TILE, ROWS * TILE), (0, 0, 0, 0))
td = ImageDraw.Draw(tileset)


def tile_box(idx):
    col = idx % COLS
    row = idx // COLS
    x0, y0 = col * TILE, row * TILE
    return x0, y0, x0 + TILE - 1, y0 + TILE - 1


def fill_tile(idx, color, border=None):
    x0, y0, x1, y1 = tile_box(idx)
    td.rectangle((x0, y0, x1, y1), fill=color)
    if border:
        td.rectangle((x0, y0, x1, y1), outline=border, width=1)


FLOORS = {
    0: ((196, 196, 204, 255), (170, 170, 180, 255)),  # corridor
    1: ((58, 74, 110, 255), (44, 58, 90, 255)),        # ceo office
    2: ((88, 66, 122, 255), (70, 50, 100, 255)),       # meeting room
    3: ((60, 108, 88, 255), (46, 88, 70, 255)),        # design desk
    4: ((54, 96, 122, 255), (40, 78, 100, 255)),       # frontend desk
    5: ((122, 92, 58, 255), (100, 74, 44, 255)),       # backend desk
    6: ((122, 62, 78, 255), (100, 48, 62, 255)),       # testing lab
    7: ((104, 104, 58, 255), (86, 86, 44, 255)),       # lounge
}
for idx, (color, border) in FLOORS.items():
    fill_tile(idx, color, border)

fill_tile(8, (70, 90, 96, 255), (56, 74, 80, 255))  # recovery room floor

# 9 rug
x0, y0, x1, y1 = tile_box(9)
td.rectangle((x0, y0, x1, y1), fill=(150, 60, 60, 255))
td.rectangle((x0 + 3, y0 + 3, x1 - 3, y1 - 3), outline=(210, 180, 120, 255), width=2)

# 10 floor seam (corridor with a subtle grid seam)
x0, y0, x1, y1 = tile_box(10)
td.rectangle((x0, y0, x1, y1), fill=(196, 196, 204, 255))
td.line((x0, y0 + TILE // 2, x1, y0 + TILE // 2), fill=(170, 170, 180, 255))
td.line((x0 + TILE // 2, y0, x0 + TILE // 2, y1), fill=(170, 170, 180, 255))

# 11 door tile (wood, arch hint)
x0, y0, x1, y1 = tile_box(11)
td.rectangle((x0, y0, x1, y1), fill=(120, 80, 45, 255))
td.rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), outline=(90, 58, 30, 255), width=2)
td.ellipse((x0 + 22, y0 + 14, x0 + 26, y0 + 18), fill=(230, 200, 120, 255))  # handle

# 12 wall face
x0, y0, x1, y1 = tile_box(12)
td.rectangle((x0, y0, x1, y1), fill=(58, 60, 68, 255))
for i in range(0, TILE, 8):
    td.line((x0, y0 + i, x1, y0 + i), fill=(46, 48, 55, 255))
td.rectangle((x0, y0, x1, y1), outline=(30, 31, 36, 255), width=1)

# 13 wall top cap (lighter, thin -- used in WallsTop for a capped look)
x0, y0, x1, y1 = tile_box(13)
td.rectangle((x0, y0, x1, y0 + 12), fill=(80, 83, 94, 255))
td.rectangle((x0, y0, x1, y0 + 12), outline=(58, 60, 68, 255), width=1)

# 14 window wall
x0, y0, x1, y1 = tile_box(14)
td.rectangle((x0, y0, x1, y1), fill=(58, 60, 68, 255))
td.rectangle((x0 + 6, y0 + 6, x1 - 6, y1 - 14), fill=(120, 170, 210, 255), outline=(30, 31, 36, 255))

# 15 spare / blank
tile_box(15)

# 16 desk
x0, y0, x1, y1 = tile_box(16)
td.rectangle((x0 + 2, y0 + 8, x1 - 2, y1 - 4), fill=(150, 108, 60, 255), outline=(100, 70, 38, 255), width=1)
td.rectangle((x0 + 4, y0 + 4, x1 - 4, y0 + 8), fill=(170, 128, 76, 255))

# 17 chair
x0, y0, x1, y1 = tile_box(17)
td.rectangle((x0 + 8, y0 + 6, x1 - 8, y0 + 20), fill=(90, 60, 130, 255), outline=(60, 40, 90, 255))
td.rectangle((x0 + 8, y0 + 20, x1 - 8, y1 - 4), fill=(60, 42, 30, 255))

# 18 sofa
x0, y0, x1, y1 = tile_box(18)
td.rectangle((x0 + 1, y0 + 10, x1 - 1, y1 - 4), fill=(150, 70, 70, 255), outline=(110, 46, 46, 255))
td.rectangle((x0 + 1, y0 + 4, x1 - 1, y0 + 12), fill=(170, 90, 90, 255))

# 19 meeting table
x0, y0, x1, y1 = tile_box(19)
td.ellipse((x0 + 2, y0 + 6, x1 - 2, y1 - 6), fill=(160, 120, 70, 255), outline=(110, 80, 44, 255), width=2)

# 20 shelf
x0, y0, x1, y1 = tile_box(20)
td.rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), fill=(96, 72, 48, 255), outline=(64, 46, 30, 255), width=1)
for i in range(3):
    td.line((x0 + 2, y0 + 2 + i * 9, x1 - 2, y0 + 2 + i * 9), fill=(64, 46, 30, 255))

# 21 server rack
x0, y0, x1, y1 = tile_box(21)
td.rectangle((x0 + 3, y0 + 2, x1 - 3, y1 - 2), fill=(40, 42, 48, 255), outline=(20, 21, 24, 255), width=1)
for i in range(4):
    color = (60, 210, 120, 255) if i % 2 == 0 else (210, 90, 60, 255)
    td.rectangle((x0 + 6, y0 + 5 + i * 6, x0 + 9, y0 + 8 + i * 6), fill=color)

# 22 testing equipment (oscilloscope-ish box with a waveform)
x0, y0, x1, y1 = tile_box(22)
td.rectangle((x0 + 3, y0 + 6, x1 - 3, y1 - 6), fill=(50, 54, 60, 255), outline=(24, 26, 30, 255), width=1)
td.line((x0 + 6, y0 + 18, x0 + 10, y0 + 12, x0 + 14, y0 + 20, x0 + 18, y0 + 10, x0 + 22, y0 + 18), fill=(90, 230, 140, 255))

# 23 plant small
x0, y0, x1, y1 = tile_box(23)
td.rectangle((x0 + 10, y1 - 8, x1 - 10, y1 - 2), fill=(120, 84, 50, 255))
td.ellipse((x0 + 6, y0 + 6, x1 - 6, y1 - 10), fill=(50, 130, 60, 255), outline=(30, 96, 40, 255))

# 24 plant tall canopy (foreground -- renders above characters)
x0, y0, x1, y1 = tile_box(24)
td.ellipse((x0 + 2, y0 + 4, x1 - 2, y1 - 6), fill=(46, 122, 56, 200), outline=(28, 90, 36, 230))
td.ellipse((x0 + 8, y0 + 10, x1 - 8, y1 - 12), fill=(60, 150, 70, 220))

# 25 shelf top (foreground cap)
x0, y0, x1, y1 = tile_box(25)
td.rectangle((x0 + 2, y0 + 2, x1 - 2, y0 + 10), fill=(110, 84, 56, 255), outline=(64, 46, 30, 255))

# 26 server top (foreground cap)
x0, y0, x1, y1 = tile_box(26)
td.rectangle((x0 + 3, y0 + 2, x1 - 3, y0 + 8), fill=(46, 48, 54, 255), outline=(20, 21, 24, 255))

# 27 lamp top
x0, y0, x1, y1 = tile_box(27)
td.polygon([(x0 + 16, y0 + 2), (x0 + 8, y0 + 14), (x0 + 24, y0 + 14)], fill=(230, 210, 140, 220))

# 28 whiteboard / strategic board (wall-mounted, CEO office + meeting room)
x0, y0, x1, y1 = tile_box(28)
td.rectangle((x0 + 3, y0 + 4, x1 - 3, y1 - 10), fill=(235, 235, 230, 255), outline=(90, 90, 90, 255), width=1)
td.line((x0 + 6, y0 + 10, x0 + 20, y0 + 10), fill=(60, 90, 200, 255))
td.line((x0 + 6, y0 + 15, x0 + 16, y0 + 15), fill=(200, 60, 60, 255))
td.line((x0 + 6, y0 + 20, x0 + 22, y0 + 20), fill=(40, 40, 40, 255))

# 29 bookshelf top (foreground cap, reuses shelf-top palette but distinct row)
x0, y0, x1, y1 = tile_box(29)
td.rectangle((x0 + 2, y0 + 2, x1 - 2, y0 + 10), fill=(120, 60, 50, 255), outline=(70, 34, 28, 255))

# 30 design tablet (drawing tablet + stylus, decorative)
x0, y0, x1, y1 = tile_box(30)
td.rectangle((x0 + 5, y0 + 10, x1 - 5, y1 - 8), fill=(45, 45, 52, 255), outline=(20, 20, 24, 255), width=1)
td.rectangle((x0 + 8, y0 + 13, x1 - 8, y1 - 11), fill=(210, 130, 220, 255))
td.line((x0 + 10, y1 - 6, x0 + 22, y0 + 8), fill=(230, 200, 120, 255), width=2)

# 31 color palette (decorative)
x0, y0, x1, y1 = tile_box(31)
td.ellipse((x0 + 4, y0 + 8, x1 - 4, y1 - 6), fill=(200, 170, 130, 255), outline=(140, 110, 80, 255))
for i, c in enumerate([(220, 60, 60, 255), (60, 140, 220, 255), (230, 210, 60, 255), (60, 200, 100, 255)]):
    td.ellipse((x0 + 8 + (i % 2) * 8, y0 + 12 + (i // 2) * 7, x0 + 12 + (i % 2) * 8, y0 + 16 + (i // 2) * 7), fill=c)

# 32 computer (interactive)
x0, y0, x1, y1 = tile_box(32)
td.rectangle((x0 + 6, y0 + 6, x1 - 6, y1 - 12), fill=(30, 32, 38, 255), outline=(14, 15, 18, 255), width=1)
td.rectangle((x0 + 8, y0 + 8, x1 - 8, y1 - 15), fill=(80, 200, 230, 255))
td.rectangle((x0 + 12, y1 - 11, x1 - 12, y1 - 6), fill=(60, 62, 70, 255))

# 33 second monitor (decorative -- "multiple monitors" flavor)
x0, y0, x1, y1 = tile_box(33)
td.rectangle((x0 + 5, y0 + 5, x1 - 5, y1 - 12), fill=(28, 30, 36, 255), outline=(12, 13, 16, 255), width=1)
td.rectangle((x0 + 7, y0 + 7, x1 - 7, y1 - 15), fill=(230, 170, 90, 255))

# 34 coffee machine
x0, y0, x1, y1 = tile_box(34)
td.rectangle((x0 + 7, y0 + 6, x1 - 7, y1 - 8), fill=(60, 44, 36, 255), outline=(30, 22, 18, 255), width=1)
td.rectangle((x0 + 10, y1 - 12, x1 - 10, y1 - 8), fill=(40, 30, 24, 255))
td.ellipse((x0 + 12, y0 + 9, x0 + 16, y0 + 13), fill=(230, 60, 60, 255))

# 35 bed (headboard + blanket, horizontal)
x0, y0, x1, y1 = tile_box(35)
td.rectangle((x0 + 1, y0 + 3, x1 - 1, y1 - 3), fill=(120, 90, 150, 255), outline=(80, 60, 110, 255), width=1)
td.rectangle((x0 + 1, y0 + 3, x1 - 1, y0 + 9), fill=(230, 225, 235, 255))
td.rectangle((x0 + 1, y0 + 3, x0 + 4, y1 - 3), fill=(90, 66, 120, 255))

# 36 puff / small seat (recovery room)
x0, y0, x1, y1 = tile_box(36)
td.ellipse((x0 + 6, y0 + 12, x1 - 6, y1 - 4), fill=(90, 120, 130, 255), outline=(60, 86, 96, 255), width=1)

tileset.save(OUT_DIR / "tileset.png")
print(f"tileset.png -> {tileset.size}")


# ---------------------------------------------------------------------------
# Status icon glyphs: small (16x16) pixel icons, NOT emoji, drawn onto their
# own atlas so `Character`-adjacent UI can show discreet status without a
# giant text balloon (spec section 62/63).
# 6 columns x 1 row: zzz, error, thinking, waiting, coffee, celebrate-star.
# ---------------------------------------------------------------------------
ICON = 16
icons = Image.new("RGBA", (ICON * 6, ICON), (0, 0, 0, 0))
idr = ImageDraw.Draw(icons)


def icon_box(i):
    return i * ICON, 0, i * ICON + ICON - 1, ICON - 1


# 0 zzz (sleeping)
x0, y0, x1, y1 = icon_box(0)
idr.text((x0 + 1, y0 + 1), "Z", fill=(140, 200, 255, 255))
idr.text((x0 + 6, y0 + 5), "z", fill=(140, 200, 255, 220))
idr.text((x0 + 9, y0 + 9), "z", fill=(140, 200, 255, 180))

# 1 error (!)
x0, y0, x1, y1 = icon_box(1)
idr.polygon([(x0 + 8, y0 + 1), (x0 + 1, y0 + 14), (x0 + 15, y0 + 14)], fill=(235, 60, 60, 255))
idr.rectangle((x0 + 7, y0 + 6, x0 + 9, y0 + 10), fill=(255, 255, 255, 255))
idr.rectangle((x0 + 7, y0 + 11, x0 + 9, y0 + 12), fill=(255, 255, 255, 255))

# 2 thinking (...)
x0, y0, x1, y1 = icon_box(2)
for i in range(3):
    idr.ellipse((x0 + 2 + i * 5, y0 + 7, x0 + 5 + i * 5, y0 + 10), fill=(230, 230, 235, 255))

# 3 waiting (hourglass)
x0, y0, x1, y1 = icon_box(3)
idr.polygon([(x0 + 3, y0 + 2), (x0 + 13, y0 + 2), (x0 + 8, y0 + 8), (x0 + 3, y0 + 2)], fill=(230, 190, 90, 255))
idr.polygon([(x0 + 3, y0 + 14), (x0 + 13, y0 + 14), (x0 + 8, y0 + 8), (x0 + 3, y0 + 14)], fill=(230, 190, 90, 255))

# 4 coffee
x0, y0, x1, y1 = icon_box(4)
idr.rectangle((x0 + 3, y0 + 6, x0 + 11, y0 + 13), fill=(230, 230, 230, 255), outline=(120, 100, 80, 255))
idr.rectangle((x0 + 4, y0 + 8, x0 + 10, y0 + 12), fill=(90, 60, 40, 255))
idr.arc((x0 + 10, y0 + 6, x0 + 14, y0 + 10), 300, 120, fill=(120, 100, 80, 255))

# 5 celebrate (star)
x0, y0, x1, y1 = icon_box(5)
idr.polygon([
    (x0 + 8, y0 + 1), (x0 + 10, y0 + 6), (x0 + 15, y0 + 6), (x0 + 11, y0 + 9),
    (x0 + 13, y0 + 14), (x0 + 8, y0 + 11), (x0 + 3, y0 + 14), (x0 + 5, y0 + 9),
    (x0 + 1, y0 + 6), (x0 + 6, y0 + 6),
], fill=(250, 210, 80, 255))

icons.save(OUT_DIR / "status_icons.png")
print(f"status_icons.png -> {icons.size}")


# ---------------------------------------------------------------------------
# Character spritesheets. Layout (rows), each frame 32x48, 4 columns/row:
#   0-3  walk:  down, left, right, up   (idle = column 0 of each)
#   4-7  seat:  down, left, right, up   (columns 0/2 = seated still,
#                                        columns 1/3 = subtle typing shift --
#                                        reused for CODING/DESIGNING/TESTING/
#                                        READING/WAITING-seated)
#   8    lying  (sofa rest / bed sleep -- same pose, differentiated by tint
#                 + status icon, not a second drawn pose)
#   9    celebrate (arms raised)
# This is a deliberate, documented scoping decision (see GAME_ENGINE.md):
# rather than hand-animate 12 fully unique contextual poses, most
# contextual states reuse {seated or lying pose} + {a small status icon},
# which is honest about what's real animation vs. icon-driven context.
# ---------------------------------------------------------------------------
FRAME_W, FRAME_H = 32, 48
DIRECTIONS = ["down", "left", "right", "up"]


def draw_head(d, cx, head_top, skin, hair, direction, accessory):
    d.ellipse((cx - 8, head_top, cx + 8, head_top + 16), fill=skin, outline=(0, 0, 0, 60))
    if direction == "up":
        d.ellipse((cx - 8, head_top - 2, cx + 8, head_top + 10), fill=hair)
    else:
        d.ellipse((cx - 8, head_top - 2, cx + 8, head_top + 6), fill=hair)

    if direction == "down":
        d.ellipse((cx - 4, head_top + 7, cx - 2, head_top + 9), fill=(20, 20, 25, 255))
        d.ellipse((cx + 2, head_top + 7, cx + 4, head_top + 9), fill=(20, 20, 25, 255))
    elif direction == "left":
        d.ellipse((cx - 6, head_top + 7, cx - 4, head_top + 9), fill=(20, 20, 25, 255))
    elif direction == "right":
        d.ellipse((cx + 4, head_top + 7, cx + 6, head_top + 9), fill=(20, 20, 25, 255))

    # Accessories -- small, silhouette-only, never a real logo/brand mark.
    if accessory == "glasses" and direction in ("down", "left", "right"):
        d.rectangle((cx - 6, head_top + 6, cx + 6, head_top + 9), outline=(20, 20, 25, 220))
    elif accessory == "headset":
        d.arc((cx - 9, head_top - 6, cx + 9, head_top + 10), 200, 340, fill=(40, 40, 45, 255), width=2)
        d.ellipse((cx - 10, head_top + 4, cx - 6, head_top + 9), fill=(40, 40, 45, 255))
    elif accessory == "beret":
        d.ellipse((cx - 9, head_top - 6, cx + 9, head_top + 2), fill=(150, 40, 90, 255))
        d.ellipse((cx + 5, head_top - 8, cx + 8, head_top - 5), fill=(150, 40, 90, 255))


def draw_character(path: pathlib.Path, skin, shirt, pants, hair, accessory=None):
    rows = 10
    sheet = Image.new("RGBA", (FRAME_W * 4, FRAME_H * rows), (0, 0, 0, 0))
    d = ImageDraw.Draw(sheet)

    def body_frame(cx, oy, leg_shift, tie=False):
        head_top = oy + 6
        body_top = oy + 20
        body_bottom = oy + 36
        feet_y = oy + 44
        d.rectangle((cx - 6 + leg_shift, body_bottom, cx - 2 + leg_shift, feet_y), fill=pants)
        d.rectangle((cx + 2 - leg_shift, body_bottom, cx + 6 - leg_shift, feet_y), fill=pants)
        d.rounded_rectangle((cx - 9, body_top, cx + 9, body_bottom), radius=3, fill=shirt, outline=(0, 0, 0, 60))
        if tie:
            d.polygon([(cx - 2, body_top + 2), (cx + 2, body_top + 2), (cx, body_top + 10)], fill=(150, 30, 30, 255))
        return head_top, body_top, body_bottom

    # Rows 0-3: walking (idle = column 0).
    for row, direction in enumerate(DIRECTIONS):
        for col in range(4):
            ox, oy = col * FRAME_W, row * FRAME_H
            cx = ox + FRAME_W // 2
            leg_shift = [0, 3, 0, -3][col]
            head_top, body_top, body_bottom = body_frame(cx, oy, leg_shift, tie=(accessory == "tie"))
            arm_shift = leg_shift // 2
            d.rectangle((cx - 12, body_top + 2 + arm_shift, cx - 9, body_bottom - 2), fill=shirt)
            d.rectangle((cx + 9, body_top + 2 - arm_shift, cx + 12, body_bottom - 2), fill=shirt)
            draw_head(d, cx, head_top, skin, hair, direction, accessory)

    # Rows 4-7: seated (chair covers the legs; columns 1/3 raise the arms
    # slightly for a subtle typing loop).
    for row, direction in enumerate(DIRECTIONS):
        oy = (4 + row) * FRAME_H
        for col in range(4):
            ox = col * FRAME_W
            cx = ox + FRAME_W // 2
            head_top = oy + 10
            body_top = oy + 24
            body_bottom = oy + 40
            typing = col in (1, 3)
            d.rectangle((cx - 6, body_bottom, cx - 2, oy + 44), fill=pants)
            d.rectangle((cx + 2, body_bottom, cx + 6, oy + 44), fill=pants)
            d.rounded_rectangle((cx - 9, body_top, cx + 9, body_bottom), radius=3, fill=shirt, outline=(0, 0, 0, 60))
            if accessory == "tie":
                d.polygon([(cx - 2, body_top + 2), (cx + 2, body_top + 2), (cx, body_top + 9)], fill=(150, 30, 30, 255))
            arm_y = body_top + (0 if typing else 2)
            d.rectangle((cx - 12, arm_y, cx - 9, body_bottom - 2), fill=shirt)
            d.rectangle((cx + 9, arm_y, cx + 12, body_bottom - 2), fill=shirt)
            draw_head(d, cx, head_top, skin, hair, direction, accessory)

    # Row 8: lying (sofa rest / bed sleep -- one shared horizontal pose).
    oy = 8 * FRAME_H
    for col in range(4):
        ox = col * FRAME_W
        cy = oy + FRAME_H // 2 + 6
        d.rounded_rectangle((ox + 4, cy - 6, ox + 26, cy + 6), radius=4, fill=shirt, outline=(0, 0, 0, 60))
        d.ellipse((ox + 22, cy - 9, ox + 30, cy + 3), fill=skin, outline=(0, 0, 0, 60))
        d.ellipse((ox + 24, cy - 11, ox + 30, cy - 3), fill=hair)
        d.rectangle((ox + 2, cy - 3, ox + 6, cy + 5), fill=pants)

    # Row 9: celebrate (arms raised, idle-down base).
    oy = 9 * FRAME_H
    for col in range(4):
        ox = col * FRAME_W
        cx = ox + FRAME_W // 2
        head_top, body_top, body_bottom = body_frame(cx, oy, 0, tie=(accessory == "tie"))
        d.rectangle((cx - 13, head_top - 4, cx - 9, body_top + 4), fill=shirt)
        d.rectangle((cx + 9, head_top - 4, cx + 13, body_top + 4), fill=shirt)
        draw_head(d, cx, head_top, skin, hair, "down", accessory)

    sheet.save(path)
    print(f"{path.name} -> {sheet.size}")


# Must stay in sync with `desktop/src/game/avatars/appearancePresets.ts`.
PRESETS = {
    "gemini_ceo": dict(skin=(230, 195, 160, 255), shirt=(35, 40, 55, 255), pants=(25, 28, 38, 255),
                        hair=(35, 30, 30, 255), accessory="tie"),
    "gemini_designer": dict(skin=(225, 185, 165, 255), shirt=(210, 80, 150, 255), pants=(70, 60, 110, 255),
                             hair=(160, 90, 200, 255), accessory="beret"),
    "codex": dict(skin=(215, 175, 140, 255), shirt=(50, 130, 200, 255), pants=(60, 80, 130, 255),
                  hair=(40, 35, 32, 255), accessory="headset"),
    "claude_code": dict(skin=(235, 200, 170, 255), shirt=(60, 120, 90, 255), pants=(45, 50, 45, 255),
                         hair=(50, 40, 35, 255), accessory="glasses"),
}

for name, appearance in PRESETS.items():
    draw_character(OUT_DIR / f"{name}.png", **appearance)

print("done")
