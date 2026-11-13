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

  it("dashboard counts every issue source from the unified register", () => {
    const page = fs.readFileSync(
      path.join(root, "src/pages/ManagementIssuesDashboardPage.jsx"),
      "utf8"
    );
    expect(page).toContain("getIssuesRegister");
    expect(page).toContain("Found Item");
    expect(page).not.toContain("By Issue");
    expect(page).not.toContain("Customer order issues");
    expect(page).toContain("Employee reports");
    expect(page).toContain("Needs attention");
    expect(page).toContain("date_from");
    expect(page).toContain("status_group");
    expect(page).toContain("category");
    const register = fs.readFileSync(
      path.join(root, "src/pages/ManagementIssuesPage.jsx"),
      "utf8"
    );
    for (const key of ["date_from", "date_to", "source", "category", "status_group"]) {
      expect(page).toContain(key);
      expect(register).toContain(`searchParams.get("${key}")`);
    }
  });
});
