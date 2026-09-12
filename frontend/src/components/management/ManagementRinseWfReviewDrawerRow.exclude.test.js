import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const rowSrc = readFileSync(
  join(here, "ManagementRinseWfReviewDrawerRow.jsx"),
  "utf8",
);

describe("ManagementRinseWfReviewDrawerRow Missing From Portal actions", () => {
  it("keeps Exclude for DISAPPEARED_FROM_PORTAL", () => {
    expect(rowSrc).toContain('reasonCodes.includes("DISAPPEARED_FROM_PORTAL")');
    expect(rowSrc).toContain("canExcludeDisappeared");
    expect(rowSrc).toMatch(/>\s*\{saving \? "Saving…" : "Exclude"\}\s*</);
  });
});
