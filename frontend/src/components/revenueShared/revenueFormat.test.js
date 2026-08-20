import { describe, expect, it } from "vitest";
import { fmtMoney, moneyToInput, parseMoneyInput } from "./revenueFormat";

describe("revenueFormat blank vs zero", () => {
  it("parseMoneyInput distinguishes blank and zero", () => {
    expect(parseMoneyInput("")).toBeNull();
    expect(parseMoneyInput("   ")).toBeNull();
    expect(parseMoneyInput(null)).toBeNull();
    expect(parseMoneyInput("0")).toBe(0);
    expect(parseMoneyInput("0.00")).toBe(0);
    expect(parseMoneyInput("$12.50")).toBe(12.5);
  });

  it("fmtMoney shows em dash for null", () => {
    expect(fmtMoney(null)).toBe("—");
    expect(fmtMoney(0)).toBe("$0.00");
  });

  it("moneyToInput keeps blank empty", () => {
    expect(moneyToInput(null)).toBe("");
    expect(moneyToInput(0)).toBe("0");
  });
});
