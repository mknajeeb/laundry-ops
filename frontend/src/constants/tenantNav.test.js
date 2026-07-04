import { describe, expect, it } from "vitest";
import { TENANT_NAV_ITEMS, tenantNavItemVisible } from "./tenantNav";
import {
  isAccountantOnlyUser,
  isFinanceOnlyUser,
  isPayrollManagementOnlyUser,
  isRinseScheduleOnlyUser,
  tenantDefaultRoute,
  userMayUseKioskLock,
} from "../utils/platformAccess";

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
  it("blocks kiosk lock for finance-only users", () => {
    expect(userMayUseKioskLock({ roles: ["FINANCE"] })).toBe(false);
  });
});

describe("finance-only navigation", () => {
  const financeOnly = { id: 7, roles: ["FINANCE"] };
  const adminFinance = { id: 8, roles: ["ADMIN", "FINANCE"] };

  it("detects pure finance role", () => {
    expect(isFinanceOnlyUser(financeOnly)).toBe(true);
    expect(isFinanceOnlyUser(adminFinance)).toBe(false);
    expect(isPayrollManagementOnlyUser(financeOnly)).toBe(true);
  });

  it("uses payroll as default route for finance-only users", () => {
    expect(tenantDefaultRoute(financeOnly)).toBe("/payroll");
  });

  it("shows only payroll in sidebar nav", () => {
    const visible = TENANT_NAV_ITEMS.filter((item) => tenantNavItemVisible(financeOnly, item));
    expect(visible.map((item) => item.to)).toEqual(["/payroll"]);
  });
});

describe("rinse schedule-only navigation", () => {
  const rinseOnly = { id: 5, roles: ["RINSE"] };
  const adminRinse = { id: 6, roles: ["ADMIN", "RINSE"] };

  it("detects pure rinse schedule role", () => {
    expect(isRinseScheduleOnlyUser(rinseOnly)).toBe(true);
    expect(isRinseScheduleOnlyUser(adminRinse)).toBe(false);
    expect(isRinseScheduleOnlyUser({ roles: ["OPS"] })).toBe(false);
  });

  it("uses weekly schedule as default route for rinse-only users", () => {
    expect(tenantDefaultRoute(rinseOnly)).toBe("/performance/weekly-schedule");
    expect(tenantDefaultRoute(adminRinse)).toBe("/");
  });

  it("shows only weekly schedule in sidebar nav", () => {
    const visible = TENANT_NAV_ITEMS.filter((item) => tenantNavItemVisible(rinseOnly, item));
    expect(visible.map((item) => item.to)).toEqual(["/performance/weekly-schedule"]);
  });

  it("blocks kiosk lock for rinse-only users", () => {
    expect(userMayUseKioskLock(rinseOnly)).toBe(false);
  });
});
