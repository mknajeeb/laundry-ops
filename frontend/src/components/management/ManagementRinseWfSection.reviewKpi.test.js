import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const sectionSrc = readFileSync(
  join(here, "ManagementRinseWfSection.jsx"),
  "utf8",
);

describe("ManagementRinseWfSection Review KPI wiring", () => {
  it("Review KPI opens actionable Review section via openCategoryRequest", () => {
    expect(sectionSrc).toContain("setReviewOpenRequest");
    expect(sectionSrc).toContain('category: "review_required"');
    expect(sectionSrc).toContain("openCategoryRequest={reviewOpenRequest}");
    // Must not wire Review KPI to generic CW dialog filter=review
    expect(sectionSrc).not.toMatch(
      /setCurrentWorkloadDialog\(\{\s*open:\s*true,\s*filter:\s*"review"/,
    );
  });

  it("Pending KPI still uses Current Workload dialog", () => {
    expect(sectionSrc).toMatch(
      /setCurrentWorkloadDialog\(\{\s*open:\s*true,\s*filter:\s*"pending"/,
    );
  });
});
