import { describe, expect, it } from "vitest";
import {
  formatNetPaidDisplay,
  formatTaxWithheldDisplay,
  hasTaxWithheldBreakdown,
  isPayoutDetailsFinalized,
} from "./payoutSettlementDisplay";

describe("payoutSettlementDisplay", () => {
  it("shows Pending before finalization", () => {
    const line = { payout_details_finalized: false, net_paid: 100 };
    expect(formatNetPaidDisplay(line)).toBe("Pending");
    expect(formatTaxWithheldDisplay(line)).toBe("Pending");
  });

  it("formats net and tax after finalization", () => {
    const line = {
      payout_details_finalized: true,
      net_paid: 870.5,
      tax_withheld: 129.5,
    };
    expect(formatNetPaidDisplay(line)).toBe("$870.50");
    expect(formatTaxWithheldDisplay(line)).toBe("$129.50");
  });

  it("detects tax breakdown presence", () => {
    expect(
      hasTaxWithheldBreakdown({
        tax_withheld_breakdown: { federal_income_tax: 10, total_tax_withheld: 10 },
      }),
    ).toBe(true);
    expect(
      hasTaxWithheldBreakdown({
        tax_withheld_breakdown: { federal_income_tax: 0, total_tax_withheld: 0 },
      }),
    ).toBe(false);
  });

  it("reads finalized flag from batch or line", () => {
    expect(isPayoutDetailsFinalized({ payout_details_finalized_at: "2026-01-01" })).toBe(true);
    expect(isPayoutDetailsFinalized({ payout_details_finalized: true })).toBe(true);
    expect(isPayoutDetailsFinalized({})).toBe(false);
  });
});
