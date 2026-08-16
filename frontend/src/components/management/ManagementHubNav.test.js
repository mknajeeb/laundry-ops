import { describe, expect, it } from "vitest";
import { HUB_DESTINATIONS, MANAGEMENT_BUCKETS } from "./ManagementHubNav";

describe("Management Hub destinations", () => {
  it("exposes compartments with Today landing + Rinse WF live", () => {
    expect(HUB_DESTINATIONS.map((d) => d.id)).toEqual([
      "today",
      "rinse_wf",
      "rinse_hd",
      "performance",
      "labor",
      "revenue",
      "rinse_flow",
      "analysis",
      "bag_search",
    ]);
    expect(HUB_DESTINATIONS.filter((d) => d.enabled).map((d) => d.id)).toEqual([
      "today",
      "rinse_wf",
    ]);
  });

  it("keeps the three operating buckets", () => {
    expect(MANAGEMENT_BUCKETS).toEqual(["rinse_wf", "rinse_hd", "non_rinse"]);
  });
});
