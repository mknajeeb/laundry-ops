import { describe, expect, it } from "vitest";
import { parseRinseBagScanEventsResponse } from "./rinseTimeFormat";

describe("parseRinseBagScanEventsResponse", () => {
  const sample = [{ id: 1, purpose: "start-cleaning", bag_id: "D6E0SRN9QV" }];

  it("returns raw array from scan-events API", () => {
    expect(parseRinseBagScanEventsResponse(sample)).toEqual(sample);
  });

  it("unwraps events or scan_events object shapes", () => {
    expect(parseRinseBagScanEventsResponse({ events: sample })).toEqual(sample);
    expect(parseRinseBagScanEventsResponse({ scan_events: sample })).toEqual(sample);
  });

  it("returns empty array when missing", () => {
    expect(parseRinseBagScanEventsResponse(null)).toEqual([]);
    expect(parseRinseBagScanEventsResponse({})).toEqual([]);
  });
});
