import { describe, expect, it } from "vitest";
import {
  emptyInputValues,
  formatCompletionInput,
  normalizeInputSchema,
  validateInputClient,
} from "./TaskCompletionInputs";

describe("TaskCompletionInputs helpers", () => {
  it("normalizes schema and validates required number", () => {
    const schema = normalizeInputSchema([
      { id: "gallons", type: "number", label: "Gallons", required: true },
      { key: "notes", type: "text", label: "Notes", required: false },
    ]);
    expect(schema).toHaveLength(2);
    expect(validateInputClient(schema, emptyInputValues(schema))).toMatch(/Gallons/);
    expect(validateInputClient(schema, { gallons: "8", notes: "" })).toBe("");
  });

  it("formats completion input for verifiers", () => {
    expect(
      formatCompletionInput({
        values: { gallons: 8, ok: true },
        remarks: "Top shelf",
      }),
    ).toContain("gallons: 8");
  });
});
