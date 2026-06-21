import { describe, expect, it } from "vitest";
import {
  accountantPeriodStatusColor,
  accountantPeriodStatusLabel,
  pickDefaultAccountantBatch,
} from "./accountantBatchPick";

describe("accountantBatchPick", () => {
  it("prefers pending batch over paid", () => {
    const batches = [
      {
        id: 1,
        status: "paid",
        pay_period_start: "2026-06-08",
        pay_period_end: "2026-06-14",
      },
      {
        id: 2,
        status: "sent_to_accountant",
        pay_period_start: "2026-06-01",
        pay_period_end: "2026-06-07",
      },
    ];
    expect(pickDefaultAccountantBatch(batches)?.id).toBe(2);
  });

  it("labels pending, payment initiated, and paid periods", () => {
    expect(accountantPeriodStatusLabel({ status: "sent_to_accountant" })).toBe("Pending");
    expect(
      accountantPeriodStatusLabel({
        status: "approved_for_payment",
        accountant_payment_confirmed_at: "2026-06-20",
      }),
    ).toBe("Payment initiated");
    expect(accountantPeriodStatusLabel({ status: "paid" })).toBe("Paid");
    expect(accountantPeriodStatusColor({ status: "paid" })).toBe("success");
    expect(accountantPeriodStatusColor({ status: "sent_to_accountant" })).toBe("warning");
  });
});
