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

  it('defaults pay_amount to "Full" when no amount is stored', () => {
    const prefill = buildDirectDepositPrefill({}, { work_json: {} }, {});
    expect(prefill.pay_amount).toBe("Full");
  });

  it("uses explicit pay_amount from profile when set", () => {
    const prefill = buildDirectDepositPrefill(
      {},
      { work_json: { pay_amount: "$500.00" } },
      {},
    );
    expect(prefill.pay_amount).toBe("$500.00");
  });

  it("uses hourly_rate when pay_amount is absent", () => {
    const prefill = buildDirectDepositPrefill(
      {},
      { work_json: { hourly_rate: "18.50" } },
      {},
    );
    expect(prefill.pay_amount).toBe("18.50");
  });
});
