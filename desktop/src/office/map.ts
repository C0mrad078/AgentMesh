import type { DestinationId, RoomId } from "@/office/types";

/** Grid cell size in world pixels -- used by the Phaser scene to convert
 * grid coordinates to screen coordinates. Not a rendering concern of this
 * module, which only ever deals in grid cells. */
export const CELL_SIZE = 32;
export const GRID_COLS = 48;
export const GRID_ROWS = 30;

export interface RoomDefinition {
  id: RoomId;
  label: string;
  /** Inclusive grid rectangle: [x1, y1, x2, y2]. */
  rect: [number, number, number, number];
  /** Grid cell of the door opening in the room's perimeter wall. */
  door: [number, number];
  color: number; // Phaser fill color for the room floor
}

export const ROOMS: RoomDefinition[] = [
  { id: "ceo_office", label: "CEO Office", rect: [2, 2, 12, 9], door: [7, 9], color: 0x2b3a55 },
  { id: "meeting_room", label: "Meeting Room", rect: [16, 2, 28, 9], door: [22, 9], color: 0x40325a },
  { id: "design_desk", label: "Design Desk", rect: [32, 2, 44, 9], door: [38, 9], color: 0x2f4a3f },
  { id: "frontend_desk", label: "Frontend Desk", rect: [2, 13, 14, 20], door: [8, 13], color: 0x2f4a5a },
  { id: "backend_desk", label: "Backend Desk", rect: [32, 13, 44, 20], door: [38, 13], color: 0x4a3f2f },
  { id: "testing_lab", label: "Testing Lab", rect: [16, 21, 28, 28], door: [22, 21], color: 0x5a2f3f },
  { id: "lounge", label: "Lounge", rect: [2, 21, 14, 28], door: [8, 21], color: 0x4a4a2f },
];

const ROOM_BY_ID = new Map(ROOMS.map((r) => [r.id, r]));

/** Specific interaction points inside/around rooms, keyed by the
 * semantic destination ids the rest of the app asks to move agents to. */
const DESTINATION_POINTS: Record<DestinationId, [number, number]> = {
  ceo_office: [7, 5],
  meeting_room: [22, 5],
  design_desk: [38, 5],
  frontend_desk: [8, 16],
  backend_desk: [38, 16],
  testing_lab: [22, 24],
  lounge: [8, 24],
  lounge_sofa: [5, 25],
  coffee_machine: [11, 22],
  task_board: [22, 12],
  // Four distinct seats inside the Meeting Room, spaced apart so
  // participants never occupy the same tile (spec section 39).
  meeting_seat_01: [20, 4],
  meeting_seat_02: [24, 4],
  meeting_seat_03: [20, 6],
  meeting_seat_04: [24, 6],
};

export function destinationPoint(destination: DestinationId): [number, number] {
  return DESTINATION_POINTS[destination];
}

export function roomLabel(room: RoomId): string {
  return ROOM_BY_ID.get(room)?.label ?? room;
}

/** True if [x, y] is inside a room's outer wall ring but not the door
 * cell -- i.e. blocked. Cells outside every room (corridors) are always
 * walkable; cells strictly inside a room are always walkable (agents walk
 * around desks freely, this is not a furniture-collision simulation yet
 * -- see VIRTUAL_OFFICE.md "Fase 2"). */
function isWall(x: number, y: number): boolean {
  for (const room of ROOMS) {
    const [x1, y1, x2, y2] = room.rect;
    const onPerimeter = (x === x1 || x === x2) && y >= y1 && y <= y2
      || (y === y1 || y === y2) && x >= x1 && x <= x2;
    if (!onPerimeter) continue;
    const [doorX, doorY] = room.door;
    if (x === doorX && y === doorY) return false;
    return true;
  }
  return false;
}

export function isWalkable(x: number, y: number): boolean {
  if (x < 0 || y < 0 || x >= GRID_COLS || y >= GRID_ROWS) return false;
  return !isWall(x, y);
}
