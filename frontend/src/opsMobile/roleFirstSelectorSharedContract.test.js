import { readFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("shared Role-first selector consolidation", () => {
  it("exports one OpsRoleFirstSelector used by Change Role and attendance surfaces", () => {
    const selector = readFileSync(path.join(root, "OpsRoleFirstSelector.jsx"), "utf8");
    const switchFlow = readFileSync(path.join(root, "OpsSwitchRoleFlow.jsx"), "utf8");
    const pinPage = readFileSync(path.join(root, "../pages/AttendancePinPage.jsx"), "utf8");
    const rolePage = readFileSync(path.join(root, "../pages/AttendanceRoleSwitchPage.jsx"), "utf8");
    const clockPage = readFileSync(path.join(root, "../pages/ClockPage.jsx"), "utf8");
    const timeClock = readFileSync(path.join(root, "../pages/TimeClockPage.jsx"), "utf8");

    expect(selector).toContain('ROLE_ICONS');
    expect(selector).toContain("groupCombosByFamily");
    expect(selector).toContain("resolvePrimaryRoleTap");
    expect(selector).toContain("translateCanonicalRoleLabel");
    expect(selector).toContain("translateCanonicalWorkLabel");
    expect(selector).toContain('t("mobileOps.current")');
    expect(selector).toContain("role-family-rinse.png");
    expect(selector).toContain("role-family-veewash.png");
    expect(selector).toContain("Wash-Dry-Fold");
    expect(selector).toContain("useI18n");
    expect(switchFlow).toContain("OpsRoleFirstSelector");
    expect(switchFlow).toContain("OpsLocaleToggle");
    expect(switchFlow).toContain("mobileOps.roleChanged");
    expect(rolePage).toContain("OpsSwitchRoleFlow");
    expect(rolePage).toContain("ROLE_SUCCESS_DELAY_MS");
    expect(rolePage).toContain("dismissSuccess");
    expect(pinPage).toContain("OpsRoleFirstSelector");
    expect(pinPage).toContain("OpsLocaleToggle");
    expect(pinPage).not.toContain("selectCategoryTitle");
    expect(pinPage).not.toContain('pickStep === "category"');
    expect(clockPage).toContain("OpsRoleFirstSelector");
    expect(clockPage).not.toContain("roleChoiceButtonSx");
    expect(clockPage).not.toContain("rolesForCategory");
    expect(timeClock).toContain("OpsRoleFirstSelector");
    expect(timeClock).not.toContain("roleChoiceButtonSx");
    expect(timeClock).not.toContain("resumeRoles");
  });
});
