import { describe, expect, it } from "vitest";
import {
  buildDirectDepositPrefill,
  resolveDirectDepositSsnDisplay,
} from "./DirectDepositFormPrint";

describe("resolveDirectDepositSsnDisplay", () => {
  it("prefers full i9.ssn for W-2 employees (print form)", () => {
    expect(
      resolveDirectDepositSsnDisplay(
        { itin_ssn_last4: null },
        { i9: { ssn: "123-45-6789" } },
      ),
    ).toBe("123-45-6789");
  });

  it("falls back to masked payroll last4 when i9.ssn is absent", () => {
    expect(resolveDirectDepositSsnDisplay({ itin_ssn_last4: "6789" }, {})).toBe("***-**-6789");
  });

  it("returns empty when no tax id is on file", () => {
    expect(resolveDirectDepositSsnDisplay({}, {})).toBe("");
  });
});

describe("buildDirectDepositPrefill", () => {
  it("includes ssn_display from hr work_json.i9", () => {
    const prefill = buildDirectDepositPrefill(
      { first_name: "Paola", last_name: "Almiron" },
      { work_json: { i9: { ssn: "987654321" } } },
      {},
    );
    expect(prefill.ssn_display).toBe("987-65-4321");
  });

  it("uppercases state from mailing address", () => {
    const prefill = buildDirectDepositPrefill(
      {},
      { work_json: { mailing: { state: "ny", city: "Brooklyn" } } },
      {},
    );
    expect(prefill.state).toBe("NY");
  });

  it("uppercases state from work root when mailing is absent", () => {
    const prefill = buildDirectDepositPrefill(
      {},
      { work_json: { state: "ca" } },
      {},
    );
    expect(prefill.state).toBe("CA");
  });
});
