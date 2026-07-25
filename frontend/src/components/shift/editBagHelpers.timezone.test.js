describe("formatWeightObservedEt timezone-aware", () => {
  it("converts July UTC ISO to America/New_York compact label", async () => {
    const { formatWeightObservedEt } = await import("./editBagHelpers.js");
    // 12:58 UTC = 08:58 EDT
    expect(formatWeightObservedEt("2026-07-24T12:58:00Z")).toBe("07/24 08:58 ET");
  });

  it("converts winter UTC ISO to EST", async () => {
    const { formatWeightObservedEt } = await import("./editBagHelpers.js");
    expect(formatWeightObservedEt("2026-01-15T12:58:00Z")).toBe("01/15 07:58 ET");
  });

  it("formats naive portal wall without shifting hours", async () => {
    const { formatWeightObservedEt } = await import("./editBagHelpers.js");
    expect(formatWeightObservedEt("2026-07-22 06:24:11")).toBe("07/22 06:24 ET");
  });
});

describe("describeWeightProvenance separates event vs observation", () => {
  it("shows weight entered, first observed, and capture lag", async () => {
    const { describeWeightProvenance } = await import("./editBagHelpers.js");
    const d = describeWeightProvenance({
      role: "pre",
      weightLbs: 15.6,
      source: "portal_weight_num",
      portalEventAt: "2026-07-24T08:24:00-04:00",
      observedAt: "2026-07-24T12:58:00Z",
      attachBatchId: 1,
    });
    expect(d.lines.some((l) => /Weight entered:.*8:24 AM ET/i.test(l))).toBe(true);
    expect(d.lines.some((l) => /First observed:.*8:58 AM ET/i.test(l))).toBe(true);
    expect(d.lines.some((l) => /Capture lag: 34 min/i.test(l))).toBe(true);
    expect(d.helperText).not.toMatch(/Captured from portal · 07\/24 12:58/i);
  });

  it("shows only scrape observation when portal event missing", async () => {
    const { describeWeightProvenance } = await import("./editBagHelpers.js");
    const d = describeWeightProvenance({
      role: "post",
      weightLbs: 9.7,
      source: "portal_weight_num",
      observedAt: "2026-07-24T20:04:00Z",
    });
    expect(d.lines.some((l) => /First observed by scrape:.*4:04 PM ET/i.test(l))).toBe(true);
    expect(d.lines.some((l) => /Weight entered/i.test(l))).toBe(false);
  });
});

describe("captureLagMinutes", () => {
  it("computes lag from aware ISO values", async () => {
    const { captureLagMinutes } = await import("./editBagHelpers.js");
    expect(
      captureLagMinutes("2026-07-24T08:24:00-04:00", "2026-07-24T12:58:00Z")
    ).toBe(34);
    expect(
      captureLagMinutes("2026-07-24T15:49:00-04:00", "2026-07-24T20:04:00Z")
    ).toBe(15);
  });
});
