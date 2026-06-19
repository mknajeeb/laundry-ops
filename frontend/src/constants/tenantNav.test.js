import { describe, expect, it } from "vitest";
import { TENANT_NAV_ITEMS, tenantNavItemVisible } from "./tenantNav";
import { isAccountantOnlyUser, tenantDefaultRoute, userMayUseKioskLock } from "../utils/platformAccess";

describe("accountant-only navigation", () => {
  const accountantOnly = { id: 1, roles: ["ACCOUNTANT"] };
  const adminAccountant = { id: 2, roles: ["ADMIN", "ACCOUNTANT"] };
  const checkoutAccountant = { id: 3, roles: ["CHECKOUT", "ACCOUNTANT"] };

  it("detects pure accountant role", () => {
    expect(isAccountantOnlyUser(accountantOnly)).toBe(true);
    expect(isAccountantOnlyUser(adminAccountant)).toBe(false);
    expect(isAccountantOnlyUser(checkoutAccountant)).toBe(false);
    expect(isAccountantOnlyUser({ roles: ["SUPER_ADMIN", "ACCOUNTANT"] })).toBe(false);
  });

  it("uses payroll as default route for accountant-only users", () => {
    expect(tenantDefaultRoute(accountantOnly)).toBe("/payroll");
    expect(tenantDefaultRoute(adminAccountant)).toBe("/");
    expect(tenantDefaultRoute(null)).toBe("/");
  });

  it("shows only payroll in sidebar nav", () => {
    const visible = TENANT_NAV_ITEMS.filter((item) => tenantNavItemVisible(accountantOnly, item));
    expect(visible.map((item) => item.to)).toEqual(["/payroll"]);
  });

  it("keeps home and portal nav for admin with accountant role", () => {
    const home = TENANT_NAV_ITEMS.find((item) => item.to === "/");
    const checkout = TENANT_NAV_ITEMS.find((item) => item.to === "/checkout");
    expect(tenantNavItemVisible(adminAccountant, home)).toBe(true);
    expect(tenantNavItemVisible(adminAccountant, checkout)).toBe(true);
  });

  it("blocks kiosk lock for accountant-only users", () => {
    expect(userMayUseKioskLock(accountantOnly)).toBe(false);
    expect(userMayUseKioskLock(adminAccountant)).toBe(false);
    expect(userMayUseKioskLock({ id: 4, roles: ["CHECKOUT"] })).toBe(true);
  });
});
