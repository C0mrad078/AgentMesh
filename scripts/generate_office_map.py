"""Generates the AgentMash HQ Tiled map (real Tiled JSON format, orthogonal,
32x32 grid, multiple layers) -- not an image, not CSS, not hardcoded
in-code rectangles. Phaser loads this exact file at runtime via
`this.load.tilemapTiledJSON`.

Stage 2 changes: splits the old wide Lounge into a narrower Lounge +
a new Recovery Room (beds), and adds per-room decorative furniture
(whiteboard, bookshelf, design tablet, palette, extra monitor, real
coffee machine) so each room reads as visually distinct (spec section 3).
There is no more Owner/Test Agent spawn -- the four named agents share
one entry point and are sent to their desks by the state machine.

Run with: python3 scripts/generate_office_map.py
"""

import json
import pathlib

OUT_PATH = pathlib.Path(__file__).resolve().parent.parent / "desktop" / "src" / "game" / "maps" / "agentmashHq.json"

TILE = 32
COLS, ROWS = 40, 30

# Local tileset ids (see generate_office_assets.py for what each draws).
T_CORRIDOR, T_CEO, T_MEETING, T_DESIGN, T_FRONTEND, T_BACKEND, T_TESTING, T_LOUNGE = range(8)
T_RECOVERY, T_RUG, T_SEAM, T_DOOR, T_WALL, T_WALL_CAP, T_WINDOW, T_BLANK = range(8, 16)
T_DESK, T_CHAIR, T_SOFA, T_TABLE, T_SHELF, T_SERVER, T_TESTEQ, T_PLANT = range(16, 24)
T_PLANT_TOP, T_SHELF_TOP, T_SERVER_TOP, T_LAMP_TOP = range(24, 28)
T_WHITEBOARD, T_BOOKSHELF_TOP, T_DESIGN_TABLET, T_PALETTE = range(28, 32)
T_COMPUTER, T_MONITOR2, T_COFFEE_MACHINE, T_BED, T_PUFF = range(32, 37)

ROOM_FLOOR = {
    "ceo_office": T_CEO,
    "meeting_room": T_MEETING,
    "design_desk": T_DESIGN,
    "frontend_desk": T_FRONTEND,
    "backend_desk": T_BACKEND,
    "testing_lab": T_TESTING,
    "lounge": T_LOUNGE,
    "recovery_room": T_RECOVERY,
}

# id, rect [x1,y1,x2,y2] inclusive (outer wall ring included), door cell [x,y]
ROOMS = [
    ("ceo_office", (2, 2, 11, 9), (6, 9)),
    ("meeting_room", (15, 2, 24, 9), (19, 9)),
    ("design_desk", (28, 2, 37, 9), (33, 9)),
    ("frontend_desk", (2, 13, 11, 20), (6, 13)),
    ("testing_lab", (15, 13, 24, 20), (19, 13)),
    ("backend_desk", (28, 13, 37, 20), (33, 13)),
    ("lounge", (2, 23, 19, 28), (10, 23)),
    ("recovery_room", (22, 23, 37, 28), (29, 23)),
]

# One extra decorative window cell per room (still collidable, purely visual).
WINDOWS = {
    "ceo_office": (6, 2),
    "design_desk": (33, 2),
    "frontend_desk": (6, 20),
    "backend_desk": (33, 20),
}


def blank_grid(fill=0):
    return [[fill for _ in range(COLS)] for _ in range(ROWS)]


ground = blank_grid(T_CORRIDOR + 1)
floor_layer = blank_grid(0)
floor_details = blank_grid(0)
walls_bottom = blank_grid(0)
walls_top = blank_grid(0)
furniture_bottom = blank_grid(0)
furniture_top = blank_grid(0)
collision = blank_grid(0)

# Outer building shell.
for x in range(COLS):
    walls_bottom[0][x] = T_WALL + 1
    walls_bottom[ROWS - 1][x] = T_WALL + 1
    collision[0][x] = 1
    collision[ROWS - 1][x] = 1
for y in range(ROWS):
    walls_bottom[y][0] = T_WALL + 1
    walls_bottom[y][COLS - 1] = T_WALL + 1
    collision[y][0] = 1
    collision[y][COLS - 1] = 1


def place_room_floor(room_id, rect):
    x1, y1, x2, y2 = rect
    tile = ROOM_FLOOR[room_id]
    for y in range(y1 + 1, y2):
        for x in range(x1 + 1, x2):
            floor_layer[y][x] = tile + 1


def place_room_walls(room_id, rect, door):
    x1, y1, x2, y2 = rect
    dx, dy = door
    window = WINDOWS.get(room_id)
    for x in range(x1, x2 + 1):
        for y in (y1, y2):
            if (x, y) == (dx, dy):
                walls_bottom[y][x] = T_DOOR + 1
                walls_top[y][x] = T_WALL_CAP + 1
                continue
            tile = T_WINDOW if (x, y) == window else T_WALL
            walls_bottom[y][x] = tile + 1
            collision[y][x] = 1
    for y in range(y1, y2 + 1):
        for x in (x1, x2):
            if (x, y) == (dx, dy):
                walls_bottom[y][x] = T_DOOR + 1
                walls_top[y][x] = T_WALL_CAP + 1
                continue
            tile = T_WINDOW if (x, y) == window else T_WALL
            walls_bottom[y][x] = tile + 1
            collision[y][x] = 1


for room_id, rect, door in ROOMS:
    place_room_floor(room_id, rect)
    place_room_walls(room_id, rect, door)


def add_furniture(x, y, tile, collidable=True, cap_tile=None):
    furniture_bottom[y][x] = tile + 1
    if collidable:
        collision[y][x] = 1
    if cap_tile is not None and y - 1 >= 0:
        furniture_top[y - 1][x] = cap_tile + 1


# Desks + chairs (chair tiles are NOT collidable -- they are the walkable
# "sit here" destination right next to the collidable desk).
DESKS = [
    ("ceo_office", 5, 5, 5, 6),
    ("design_desk", 31, 5, 31, 6),
    ("frontend_desk", 5, 16, 5, 17),
    ("backend_desk", 31, 16, 31, 17),
]
for _room, dx, dy, cx, cy in DESKS:
    add_furniture(dx, dy, T_DESK)
    furniture_bottom[cy][cx] = T_CHAIR + 1  # walkable

# Meeting table + 4 seats around it (seats are plain walkable floor).
add_furniture(19, 5, T_TABLE)

# Testing lab equipment + a server rack.
add_furniture(19, 16, T_TESTEQ)
add_furniture(22, 16, T_SERVER, cap_tile=T_SERVER_TOP)

# --- Per-room identity furniture (spec section 3) -----------------------

# CEO Office: strategic whiteboard, bookshelf, an ops monitor, a plant.
furniture_bottom[3][8] = T_WHITEBOARD + 1  # decorative, non-collidable
add_furniture(9, 6, T_SHELF, cap_tile=T_BOOKSHELF_TOP)
furniture_bottom[5][3] = T_MONITOR2 + 1  # "monitor de operação", non-collidable
add_furniture(3, 7, T_PLANT, cap_tile=T_PLANT_TOP)

# Meeting Room: a wall whiteboard for the planning/task-graph flavor.
furniture_bottom[3][19] = T_WHITEBOARD + 1

# Design Desk: a drawing tablet + a color palette, plus the existing plant.
furniture_bottom[6][34] = T_DESIGN_TABLET + 1
furniture_bottom[7][29] = T_PALETTE + 1
add_furniture(36, 7, T_PLANT, cap_tile=T_PLANT_TOP)

# Frontend Desk: a second monitor ("múltiplos monitores").
furniture_bottom[16][7] = T_MONITOR2 + 1

# Backend Desk: a second server rack (infra flavor) alongside the first.
add_furniture(35, 16, T_SERVER, cap_tile=T_SERVER_TOP)
add_furniture(33, 18, T_SERVER, cap_tile=T_SERVER_TOP)

# Lounge (narrower now): sofa, coffee table, a real coffee machine, a plant.
add_furniture(8, 25, T_SOFA)
add_furniture(10, 25, T_TABLE, collidable=False)
add_furniture(13, 25, T_COFFEE_MACHINE)
add_furniture(15, 25, T_PLANT, cap_tile=T_PLANT_TOP)

# Recovery Room (new): two beds + a puff. Beds are NOT collidable -- the
# sleep point is the bed tile itself (same convention as chairs: the
# character renders on top of the low furniture sprite via depth order).
furniture_bottom[25][27] = T_BED + 1
furniture_bottom[25][31] = T_BED + 1
furniture_bottom[26][24] = T_PUFF + 1  # decorative extra seating, non-collidable

# Lamp (purely decorative foreground, no collision, no base sprite).
furniture_top[24][19] = T_LAMP_TOP + 1

# Floor details: rug under the CEO desk and under the lounge sofa; seam
# tiles sprinkled along the main corridor for texture.
for y in range(4, 8):
    for x in range(4, 8):
        floor_details[y][x] = T_RUG + 1
for y in range(24, 28):
    for x in range(6, 12):
        floor_details[y][x] = T_RUG + 1
for x in range(3, 37, 4):
    floor_details[11][x] = T_SEAM + 1


def layer(name, data2d, layer_type="tilelayer", visible=True, opacity=1.0):
    flat = [v for row in data2d for v in row]
    return {
        "name": name,
        "type": layer_type,
        "id": 0,
        "width": COLS,
        "height": ROWS,
        "x": 0,
        "y": 0,
        "opacity": opacity,
        "visible": visible,
        "data": flat,
    }


def obj_layer(name, objects):
    return {
        "name": name,
        "type": "objectgroup",
        "id": 0,
        "x": 0,
        "y": 0,
        "opacity": 1,
        "visible": True,
        "objects": objects,
    }


def point_obj(oid, name, otype, tx, ty, properties=None):
    obj = {
        "id": oid,
        "name": name,
        "type": otype,
        "x": tx * TILE + TILE / 2,
        "y": ty * TILE + TILE / 2,
        "width": 0,
        "height": 0,
        "visible": True,
        "point": True,
    }
    if properties:
        obj["properties"] = [{"name": k, "type": "string", "value": v} for k, v in properties.items()]
    return obj


def rect_obj(oid, name, otype, rect, properties=None):
    x1, y1, x2, y2 = rect
    obj = {
        "id": oid,
        "name": name,
        "type": otype,
        "x": x1 * TILE,
        "y": y1 * TILE,
        "width": (x2 - x1 + 1) * TILE,
        "height": (y2 - y1 + 1) * TILE,
        "visible": True,
    }
    if properties:
        obj["properties"] = [{"name": k, "type": "string", "value": v} for k, v in properties.items()]
    return obj


# Named destinations. Workstation/Bed/Sofa "seat" points below double as
# the seat_point/sleepPoint of their respective systems (see
# game/systems/WorkstationSystem.ts etc.) -- approach points are derived
# geometrically (one tile further from the furniture) rather than
# hand-placed a second time.
DESTINATIONS = {
    "ceo_office": (5, 6),
    "meeting_room": (19, 4),
    "design_desk": (31, 6),
    "frontend_desk": (5, 17),
    "backend_desk": (31, 17),
    "testing_lab": (19, 17),
    "lounge": (14, 26),
    "lounge_sofa_01": (8, 26),
    "lounge_sofa_02": (9, 26),
    "coffee_machine": (13, 26),
    "recovery_room": (29, 26),
    "recovery_bed_01": (27, 25),
    "recovery_bed_02": (31, 25),
    "task_board": (19, 11),
    "meeting_seat_01": (17, 5),
    "meeting_seat_02": (21, 5),
    "meeting_seat_03": (18, 7),
    "meeting_seat_04": (20, 7),
    "agents_entry": (12, 11),
}

zones_objs = []
for i, (room_id, rect, _door) in enumerate(ROOMS, start=1):
    zones_objs.append(rect_obj(i, room_id, "zone", rect, {"room": room_id}))

spawn_objs = []
oid = 1
for dest_id, (tx, ty) in DESTINATIONS.items():
    spawn_objs.append(point_obj(oid, dest_id, "destination", tx, ty))
    oid += 1

objects_objs = []
oid = 1
computers = [("ceo_office", 5, 5), ("design_desk", 31, 5), ("frontend_desk", 5, 16), ("backend_desk", 31, 16)]
for room_id, cx, cy in computers:
    objects_objs.append(point_obj(oid, f"computer_{room_id}", "computer", cx, cy, {"room": room_id}))
    oid += 1
objects_objs.append(point_obj(oid, "task_board", "task_board", 19, 11)); oid += 1

tileset = {
    "columns": 8,
    "image": "tileset.png",
    "imageheight": 256,
    "imagewidth": 256,
    "margin": 0,
    "name": "agentmash_tileset",
    "spacing": 0,
    "tilecount": 64,
    "tileheight": TILE,
    "tilewidth": TILE,
    "firstgid": 1,
}

tilemap = {
    "compressionlevel": -1,
    "width": COLS,
    "height": ROWS,
    "tilewidth": TILE,
    "tileheight": TILE,
    "infinite": False,
    "orientation": "orthogonal",
    "renderorder": "right-down",
    "type": "map",
    "version": "1.10",
    "tiledversion": "1.11.0",
    "nextlayerid": 20,
    "nextobjectid": 100,
    "tilesets": [tileset],
    "layers": [
        layer("Ground", ground),
        layer("Floor", floor_layer),
        layer("FloorDetails", floor_details),
        layer("WallsBottom", walls_bottom),
        layer("FurnitureBottom", furniture_bottom),
        layer("Collision", collision, visible=False),
        obj_layer("Objects", objects_objs),
        obj_layer("Zones", zones_objs),
        obj_layer("SpawnPoints", spawn_objs),
        layer("FurnitureTop", furniture_top),
        layer("WallsTop", walls_top),
    ],
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(json.dumps(tilemap, indent=2))
print(f"wrote {OUT_PATH} ({COLS}x{ROWS} tiles, {len(tilemap['layers'])} layers, {len(ROOMS)} rooms)")
