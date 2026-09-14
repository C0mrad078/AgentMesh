import { INTERACTIVE_OBJECTS, TILE_SIZE, type InteractiveObjectDefinition } from "@/game/maps/agentmashHq";

/**
 * Spec section 27/40 ("Object Registry"): the single place that knows
 * what interactive objects exist in the world and where -- so
 * `InteractionManager` never grows a spread of `if (object.name === ...)`
 * branches. Objects are sourced from the map's own `Objects` layer, not a
 * second hardcoded list.
 */
export class ObjectRegistry {
  private readonly objects: InteractiveObjectDefinition[] = INTERACTIVE_OBJECTS;

  all(): InteractiveObjectDefinition[] {
    return this.objects;
  }

  byId(id: string): InteractiveObjectDefinition | undefined {
    return this.objects.find((o) => o.id === id);
  }

  /** Nearest object to a tile position within `radiusTiles`, or `null`.
   * Distance is Euclidean over tile coordinates, matching the visual
   * "interaction radius" a player perceives (spec section 29). */
  nearest(tileX: number, tileY: number, radiusTiles: number): InteractiveObjectDefinition | null {
    let best: InteractiveObjectDefinition | null = null;
    let bestDist = Infinity;
    for (const obj of this.objects) {
      const dx = obj.tile[0] - tileX;
      const dy = obj.tile[1] - tileY;
      const dist = Math.hypot(dx, dy);
      if (dist <= radiusTiles && dist < bestDist) {
        best = obj;
        bestDist = dist;
      }
    }
    return best;
  }
}

export const TILE_SIZE_PX = TILE_SIZE;
export const objectRegistry = new ObjectRegistry();
