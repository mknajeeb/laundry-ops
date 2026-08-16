import { describe, expect, it } from "vitest";
import { HUB_DESTINATIONS } from "./ManagementHubNav";

describe("Management Hub destinations", () => {
  it("exposes the six Hub destinations with only Today enabled", () => {
    expect(HUB_DESTINATIONS.map((d) => d.id)).toEqual([
      "today",
      "rinse_flow",
      "performance",
      "labor",
      "analysis",
      "bag_search",
    ]);
    expect(HUB_DESTINATIONS.filter((d) => d.enabled).map((d) => d.id)).toEqual(["today"]);
  });
});
