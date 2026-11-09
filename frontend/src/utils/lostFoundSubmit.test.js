import { describe, expect, it } from "vitest";
import { reportFailureMessage, savedReport } from "./lostFoundSubmit";

describe("issue report submit result", () => {
  it("hides a raw Forbidden response", () => {
    expect(reportFailureMessage({ error: "Forbidden" }, "Could not save.")).toBe("reporting_not_allowed");
    expect(reportFailureMessage({ code: "reporting_not_allowed", error: "This account cannot file issue reports." })).toBe(
      "reporting_not_allowed",
    );
  });

  it("treats a dropped PIN session as something the employee can fix", () => {
    expect(reportFailureMessage({ error: "Invalid PIN. Please try again." })).toBe("pin_session");
  });

  it("requires the saved report and its photo", () => {
    expect(savedReport({ ok: true, item: { id: 9 } })).toBeNull();
    expect(savedReport({ ok: true, item: { id: 9, photos: [] } })).toBeNull();
    const item = { id: 9, photos: [{ id: 1 }] };
    expect(savedReport({ ok: true, item })).toBe(item);
    expect(savedReport({ ok: false, item })).toBeNull();
  });
});
