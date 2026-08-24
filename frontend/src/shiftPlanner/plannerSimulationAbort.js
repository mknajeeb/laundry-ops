/** Abort coordination for Management Capacity Planner simulate requests. */

export function isPlannerSimulationAbortError(err) {
  return (
    err?.code === "ERR_CANCELED"
    || err?.name === "CanceledError"
    || err?.name === "AbortError"
  );
}

/**
 * Ensures only one active planner simulate HTTP request: newer calls abort the prior one.
 */
export class PlannerSimulationAbortCoordinator {
  constructor() {
    this._seq = 0;
    this._controller = null;
  }

  begin() {
    if (this._controller) {
      this._controller.abort();
    }
    this._controller = new AbortController();
    const seq = ++this._seq;
    return { signal: this._controller.signal, seq };
  }

  isCurrent(seq) {
    return seq === this._seq;
  }

  abort() {
    if (this._controller) {
      this._controller.abort();
      this._controller = null;
    }
  }
}
