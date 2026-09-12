import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const here = dirname(fileURLToPath(import.meta.url));

describe("Pending / Review UX guards", () => {
  it("does not auto-expand first Review bag on list load", () => {
    const src = readFileSync(
      join(here, "ManagementRinseWfReviewSection.jsx"),
      "utf8",
    );
    expect(src).not.toMatch(
      /setExpandedBagId\(\(prev\)\s*=>\s*prev\s*\|\|\s*data\.bags\[0\]/,
    );
    expect(src).toMatch(/Do not auto-expand first bag/);
  });

  it("Pending CW rows are clickable and open Pending drawer", () => {
    const src = readFileSync(join(here, "ManagementRinseWfSection.jsx"), "utf8");
    expect(src).toMatch(/ManagementPendingBagDrawer/);
    expect(src).toMatch(/pending-cw-row/);
    expect(src).toMatch(/setPendingBagDrawer\(\{\s*open:\s*true/);
  });

  it("Pending drawer exposes Send to Review without completion fields", () => {
    const src = readFileSync(join(here, "ManagementPendingBagDrawer.jsx"), "utf8");
    expect(src).toMatch(/pending-send-to-review/);
    expect(src).toMatch(/Send to Review/);
    expect(src).not.toMatch(/Save & Complete/);
    expect(src).not.toMatch(/Completion employee/);
    expect(src).not.toMatch(/label=\"POST lbs\"/);
  });

  it("Review inline gates completion fields behind Complete choice", () => {
    const src = readFileSync(
      join(here, "ManagementRinseWfReviewDrawerRow.jsx"),
      "utf8",
    );
    expect(src).toMatch(/review-choose-complete/);
    expect(src).toMatch(/review-reason-banner/);
    expect(src).toMatch(/phase === \"choose\"/);
    expect(src).toMatch(/setPhase\(\"complete\"\)/);
  });
});
