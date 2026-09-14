import { describe, expect, it } from "vitest";
import {
  formatOrderDisplayId,
  orderDisplayIdFromRow,
  parseOrderDisplayId,
} from "./orderDisplayId";

describe("orderDisplayId", () => {
  it("formats BAGID-OI-MMDDYYYY from EDD", () => {
    expect(formatOrderDisplayId("8MNDJDAV8D", 5493, "2026-09-14")).toBe(
      "8MNDJDAV8D-OI-09142026",
    );
  });

  it("falls back to BAG-OI-{oi} when EDD missing", () => {
    expect(formatOrderDisplayId("8MNDJDAV8D", 5493, null)).toBe("8MNDJDAV8D-OI-5493");
  });

  it("parses EDD display id", () => {
    const p = parseOrderDisplayId("8MNDJDAV8D-OI-09142026");
    expect(p.bagId).toBe("8MNDJDAV8D");
    expect(p.form).toBe("edd");
    expect(p.eddMmddyyyy).toBe("09142026");
  });

  it("parses oi-fallback display id", () => {
    const p = parseOrderDisplayId("8MNDJDAV8D-OI-5493");
    expect(p.bagId).toBe("8MNDJDAV8D");
    expect(p.orderInstanceId).toBe(5493);
    expect(p.form).toBe("oi_fallback");
  });

  it("reads server order_display_id from row", () => {
    expect(
      orderDisplayIdFromRow({
        bag_id: "X",
        order_instance_id: 1,
        order_display_id: "X-OI-01012026",
      }),
    ).toBe("X-OI-01012026");
  });
});
