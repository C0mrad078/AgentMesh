/**
 * Spec section 40 ("Occupancy"): the single reservation table shared by
 * every "one agent at a time" spot in the office -- desks, beds, sofa
 * seats, meeting seats. Prevents two agents from ever being assigned the
 * same chair/bed/seat.
 */
export class OccupancySystem {
  private occupantOf = new Map<string, string>(); // spotId -> agentId
  private spotOfAgent = new Map<string, string>(); // agentId -> spotId

  isFree(spotId: string): boolean {
    return !this.occupantOf.has(spotId);
  }

  /** Claims `spotId` for `agentId`, releasing whatever spot that agent
   * previously held. Returns `false` (no-op) if the spot is already held
   * by a *different* agent. */
  claim(spotId: string, agentId: string): boolean {
    const currentOccupant = this.occupantOf.get(spotId);
    if (currentOccupant && currentOccupant !== agentId) return false;
    this.release(agentId);
    this.occupantOf.set(spotId, agentId);
    this.spotOfAgent.set(agentId, spotId);
    return true;
  }

  /** First free spot among `candidates`, or `null` if all are taken. */
  claimAny(candidates: string[], agentId: string): string | null {
    const current = this.spotOfAgent.get(agentId);
    if (current && candidates.includes(current)) return current;
    for (const spotId of candidates) {
      if (this.claim(spotId, agentId)) return spotId;
    }
    return null;
  }

  release(agentId: string): void {
    const spotId = this.spotOfAgent.get(agentId);
    if (!spotId) return;
    this.spotOfAgent.delete(agentId);
    if (this.occupantOf.get(spotId) === agentId) this.occupantOf.delete(spotId);
  }

  spotOf(agentId: string): string | null {
    return this.spotOfAgent.get(agentId) ?? null;
  }

  occupantOfSpot(spotId: string): string | null {
    return this.occupantOf.get(spotId) ?? null;
  }
}

export const occupancySystem = new OccupancySystem();
