import { describe, expect, it } from "vitest";
import { sourceFreshnessCaption } from "./shiftMonitorSourceFreshness";

describe("sourceFreshnessCaption", () => {
  it("uses MIN(portal, scans) — Aug 8 scan-limited watermark", () => {
    const out = sourceFreshnessCaption({
      source_freshness_available: true,
      portal_data_through_et: "2026-08-08T13:42:11-04:00",
      scan_data_through_et: "2026-08-08T13:09:00-04:00",
      operator_data_current_through_et: "2026-08-08T13:09:00-04:00",
      calculated_at_et: "2026-08-08T13:48:29-04:00",
    });
    expect(out.available).toBe(true);
    expect(out.label).toBe("Data current through: Aug 8, 1:09 PM ET");
    expect(out.tooltip).toContain("Portal: Aug 8, 1:42 PM ET");
    expect(out.tooltip).toContain("Scans: Aug 8, 1:09 PM ET");
    expect(out.tooltip).toContain("Calculated: Aug 8, 1:48 PM ET");
    expect(out.label).not.toContain("1:42");
    expect(out.label).not.toContain("1:48");
    expect(out.label).not.toContain("17:48");
  });

  it("portal-limited when scans are newer", () => {
    const out = sourceFreshnessCaption({
      source_freshness_available: true,
      portal_data_through_et: "2026-08-08T13:42:11-04:00",
      scan_data_through_et: "2026-08-08T13:46:00-04:00",
      operator_data_current_through_et: "2026-08-08T13:42:11-04:00",
      calculated_at_et: "2026-08-08T13:48:29-04:00",
    });
    expect(out.label).toBe("Data current through: Aug 8, 1:42 PM ET");
  });

  it("unavailable when watermark missing — does not invent a time", () => {
    const out = sourceFreshnessCaption({
      source_freshness_available: false,
      operator_data_current_through_et: null,
      calculated_at_et: "2026-08-08T13:48:29-04:00",
    });
    expect(out.available).toBe(false);
    expect(out.label).toBe("Data freshness unavailable");
    expect(out.label).not.toMatch(/\d{1,2}:\d{2}/);
  });
});
