import { describe, expect, it } from "vitest";
import { interpretSaveResponse } from "./plannerReview";

describe("interpretSaveResponse", () => {
  it("treats a committed save as the only success", () => {
    expect(interpretSaveResponse(200, { ok: true }).saved).toBe(true);
  });

  it("keeps the draft when another manager is saving or already saved", () => {
    const busy = interpretSaveResponse(409, { ok: false, code: "busy", error: "Another manager is saving this schedule" });
    const changed = interpretSaveResponse(409, { ok: false, code: "schedule_changed", error: "Another manager saved this week" });
    expect(busy.saved).toBe(false);
    expect(busy.keepDraft).toBe(true);
    expect(busy.reload).toBe(false);
    expect(changed.saved).toBe(false);
    expect(changed.error).toMatch(/Another manager saved/);
  });

  it("asks again only when the server needs a scope confirmation", () => {
    const confirm = interpretSaveResponse(409, { code: "confirmation_required" });
    expect(confirm.saved).toBe(false);
    expect(confirm.confirm).toBe(true);
    expect(confirm.error).toBe("");
  });
});
