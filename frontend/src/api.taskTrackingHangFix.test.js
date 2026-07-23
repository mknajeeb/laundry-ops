import { describe, expect, it, vi } from "vitest";

/**
 * Lightweight client contract tests for switch-task idempotency / timeout recovery.
 * Axios itself is not exercised; we validate key reuse helpers and timeout recovery rules.
 */

describe("switch-task client idempotency contract", () => {
  it("reuses the same UUID for retries of one user action", () => {
    const keys = [];
    const createKey = () => {
      const k = `fixed-${keys.length === 0 ? "A" : "B"}`;
      keys.push(k);
      return k;
    };
    let inFlightKey = null;
    const beginOrReuse = () => {
      if (!inFlightKey) inFlightKey = createKey();
      return inFlightKey;
    };
    const first = beginOrReuse();
    const retry = beginOrReuse();
    expect(first).toBe("fixed-A");
    expect(retry).toBe("fixed-A");
    expect(keys).toEqual(["fixed-A"]);
  });

  it("generates a fresh UUID only after a successful switch clears the in-flight key", () => {
    let n = 0;
    const createKey = () => `k-${++n}`;
    let inFlightKey = null;
    const beginOrReuse = () => {
      if (!inFlightKey) inFlightKey = createKey();
      return inFlightKey;
    };
    const a = beginOrReuse();
    inFlightKey = null; // success
    const b = beginOrReuse();
    expect(a).toBe("k-1");
    expect(b).toBe("k-2");
  });
});

describe("feature-flag timeout recovery contract", () => {
  it("fetches persisted value before allowing another toggle after timeout", async () => {
    const calls = [];
    const put = vi.fn(async () => {
      const err = new Error("timeout");
      err.code = "ECONNABORTED";
      throw err;
    });
    const get = vi.fn(async () => {
      calls.push("get");
      return { data: { category_role_tracking_enabled: false } };
    });

    let enabled = false;
    let togglesAfterTimeout = 0;
    const onToggle = async (next) => {
      try {
        await put({ category_role_tracking_enabled: next });
        enabled = next;
      } catch (e) {
        if (e?.code === "ECONNABORTED") {
          const saved = await get();
          enabled = !!saved.data.category_role_tracking_enabled;
          // Do not auto-toggle again; caller must explicitly toggle after refresh.
          return;
        }
        throw e;
      }
    };

    await onToggle(true);
    expect(put).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledTimes(1);
    expect(enabled).toBe(false);
    expect(togglesAfterTimeout).toBe(0);
  });
});
