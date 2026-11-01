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

  it("requires machine numbers and photos only when the condition matches", () => {
    const schema = [
      {
        id: "result",
        type: "choice",
        label: "New machines out of order?",
        required: true,
        options: [
          { value: "no", label: "No" },
          { value: "yes", label: "Yes" },
        ],
      },
      {
        id: "machines",
        type: "machine_numbers",
        label: "Machine Number(s)",
        required: true,
        show_when: { field: "result", in: ["yes"] },
        required_when: { field: "result", in: ["yes"] },
      },
    ];
    expect(validateInputClient(schema, { result: "no" })).toBe("");
    expect(validateInputClient(schema, { result: "yes", machines: "" })).toMatch(/Machine/);
    expect(validateInputClient(schema, { result: "yes", machines: "08, 12" })).toBe("");
    expect(
      formatCompletionInput({ values: { result: "yes", machines: ["08", "12"] } }, schema),
    ).toContain("Machine Number(s): 08, 12");
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
