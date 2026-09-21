import { describe, expect, it } from "vitest";
import {
  classificationSelectValue,
  formatRecordClassificationLabel,
  rateOverrideInputValue,
} from "./payrollClassification";

describe("time record classification label", () => {
  it("shows category · rate and marks session overrides", () => {
    expect(
      formatRecordClassificationLabel({
        worker_category: "temp",
        resolved_hourly_rate: 17,
        rate_source: "profile",
        classification_source: "record_override",
      }),
    ).toBe("Temp · $17.00/hr");
    expect(
      formatRecordClassificationLabel({
        worker_category: "temp",
        resolved_hourly_rate: 20,
        rate_source: "session_override",
        payroll_rate_override: 20,
        classification_source: "record_override",
      }),
    ).toBe("Temp · $20.00/hr (override)");
  });

  it("falls back to record-override wording when rate missing", () => {
    expect(
      formatRecordClassificationLabel({
        worker_category: "w2",
        classification_source: "record_override",
      }),
    ).toBe("W-2 · Record override");
    expect(
      formatRecordClassificationLabel({
        worker_category: "contractor_1099",
        classification_source: "profile",
      }),
    ).toBe("1099");
  });

  it("maps select value and rate override input", () => {
    expect(
      classificationSelectValue({
        worker_category: "temp",
        classification_source: "record_override",
      }),
    ).toBe("temp");
    expect(
      classificationSelectValue({
        worker_category: "w2",
        classification_source: "profile",
      }),
    ).toBe("");
    expect(rateOverrideInputValue({ payroll_rate_override: 18 })).toBe("18");
    expect(rateOverrideInputValue({ payroll_rate_override: null })).toBe("");
  });
});
