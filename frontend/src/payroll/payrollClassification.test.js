import { describe, expect, it } from "vitest";
import {
  CLASSIFICATION_OVERRIDE_OPTIONS,
  classificationSelectValue,
  formatRecordClassificationLabel,
} from "./payrollClassification";

describe("time record classification label", () => {
  it("shows the record override next to the existing short name", () => {
    expect(
      formatRecordClassificationLabel({
        worker_category: "temp",
        classification_source: "record_override",
      }),
    ).toBe("Temp · Record override");
    expect(
      formatRecordClassificationLabel({
        worker_category: "w2",
        classification_source: "profile",
      }),
    ).toBe("W-2");
  });

  it("offers employee default, W-2, 1099, and Temp / One-Time", () => {
    expect(CLASSIFICATION_OVERRIDE_OPTIONS.map((opt) => opt.label)).toEqual([
      "Use employee default",
      "W-2",
      "1099",
      "Temp / One-Time",
    ]);
    expect(classificationSelectValue({
      worker_category: "temp",
      classification_source: "record_override",
    })).toBe("temp");
    expect(classificationSelectValue({
      worker_category: "w2",
      classification_source: "profile",
    })).toBe("");
  });
});
