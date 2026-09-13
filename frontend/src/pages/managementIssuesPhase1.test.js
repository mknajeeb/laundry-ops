import { describe, expect, it } from "vitest";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

describe("Management Issues Phase 1 wiring", () => {
  it("registers Issues hub nav and routes", () => {
    const nav = fs.readFileSync(
      path.join(root, "src/components/management/ManagementHubNav.jsx"),
      "utf8"
    );
    expect(nav).toContain('id: "issues"');
    expect(nav).toContain("/management/issues");

    const app = fs.readFileSync(path.join(root, "src/App.jsx"), "utf8");
    expect(app).toContain('path="/management/issues"');
    expect(app).toContain('path="/management/issues/new"');
    expect(app).toContain('path="/management/issues/dashboard"');
    expect(app).toContain('path="/management/issues/:issueId"');
  });

  it("new issue page requires select and supports unmatched", () => {
    const page = fs.readFileSync(
      path.join(root, "src/pages/ManagementIssuesNewPage.jsx"),
      "utf8"
    );
    expect(page).toContain("selection_required");
    expect(page).toContain("Bag / Order Not Found");
    expect(page).toContain("UNMATCHED");
    expect(page).toContain("Production attribution");
    expect(page).toContain("html5-qrcode");
  });

  it("dashboard supports by-issue and by-employee with production default", () => {
    const page = fs.readFileSync(
      path.join(root, "src/pages/ManagementIssuesDashboardPage.jsx"),
      "utf8"
    );
    expect(page).toContain("By Issue");
    expect(page).toContain("By Employee");
    expect(page).toContain('useState("production")');
    expect(page).toContain("Rate unavailable");
  });
});
