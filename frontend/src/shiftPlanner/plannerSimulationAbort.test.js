import { describe, expect, it, vi } from "vitest";
import axios from "axios";
import {
  PlannerSimulationAbortCoordinator,
  isPlannerSimulationAbortError,
} from "./plannerSimulationAbort";

describe("isPlannerSimulationAbortError", () => {
  it("detects axios cancel errors", () => {
    expect(isPlannerSimulationAbortError({ code: "ERR_CANCELED", name: "CanceledError" })).toBe(true);
    expect(isPlannerSimulationAbortError({ name: "AbortError" })).toBe(true);
    expect(isPlannerSimulationAbortError(new Error("timeout of 30000ms exceeded"))).toBe(false);
  });
});

describe("PlannerSimulationAbortCoordinator", () => {
  it("aborts the previous controller when a newer simulation begins", () => {
    const coordinator = new PlannerSimulationAbortCoordinator();
    const first = coordinator.begin();
    const second = coordinator.begin();
    expect(first.signal.aborted).toBe(true);
    expect(second.signal.aborted).toBe(false);
    expect(coordinator.isCurrent(first.seq)).toBe(false);
    expect(coordinator.isCurrent(second.seq)).toBe(true);
  });

  it("marks only the latest sequence as current", () => {
    const coordinator = new PlannerSimulationAbortCoordinator();
    const a = coordinator.begin();
    const b = coordinator.begin();
    expect(coordinator.isCurrent(a.seq)).toBe(false);
    expect(coordinator.isCurrent(b.seq)).toBe(true);
  });
});

describe("planner simulate concurrency", () => {
  it("rapid staffing edits leave one active request and cancel older axios calls", async () => {
    const coordinator = new PlannerSimulationAbortCoordinator();
    const activeSignals = new Set();
    const simulate = vi.fn(({ signal }) => {
      activeSignals.add(signal);
      return new Promise((resolve, reject) => {
        const onAbort = () => {
          signal.removeEventListener("abort", onAbort);
          activeSignals.delete(signal);
          const err = new axios.CanceledError("canceled");
          err.code = "ERR_CANCELED";
          reject(err);
        };
        signal.addEventListener("abort", onAbort);
        setTimeout(() => {
          signal.removeEventListener("abort", onAbort);
          activeSignals.delete(signal);
          resolve({ data: { simulation_valid: true, seq: coordinator._seq } });
        }, 40);
      });
    });

    const errors = [];
    const results = [];

    async function runOnce() {
      const { signal, seq } = coordinator.begin();
      try {
        const res = await simulate({ signal });
        if (!coordinator.isCurrent(seq)) return;
        results.push(res.data.seq);
      } catch (err) {
        if (!coordinator.isCurrent(seq) || isPlannerSimulationAbortError(err)) return;
        errors.push(err);
      }
    }

    await Promise.all([runOnce(), runOnce(), runOnce()]);
    expect(simulate).toHaveBeenCalledTimes(3);
    expect(errors).toEqual([]);
    expect(results).toEqual([3]);
    expect(activeSignals.size).toBe(0);
  });

  it("cancelled request does not surface timeout or error UI state", async () => {
    const coordinator = new PlannerSimulationAbortCoordinator();
    let error = "";

    const first = coordinator.begin();
    const pending = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("timeout of 30000ms exceeded")), 50);
      first.signal.addEventListener("abort", () => {
        clearTimeout(timer);
        const err = new axios.CanceledError("canceled");
        err.code = "ERR_CANCELED";
        reject(err);
      });
    });

    coordinator.begin();
    try {
      await pending;
      if (coordinator.isCurrent(first.seq)) error = "timeout";
    } catch (err) {
      if (coordinator.isCurrent(first.seq) && !isPlannerSimulationAbortError(err)) {
        error = err.message;
      }
    }

    expect(error).toBe("");
  });

  it("manual recalculate supersedes automatic in-flight simulation", async () => {
    const coordinator = new PlannerSimulationAbortCoordinator();
    const auto = coordinator.begin();
    const manual = coordinator.begin();
    expect(auto.signal.aborted).toBe(true);
    expect(manual.signal.aborted).toBe(false);
    expect(coordinator.isCurrent(auto.seq)).toBe(false);
    expect(coordinator.isCurrent(manual.seq)).toBe(true);
  });
});
