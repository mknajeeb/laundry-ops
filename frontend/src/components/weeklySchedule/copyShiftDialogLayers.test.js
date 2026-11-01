import { describe, expect, it } from "vitest";
import { copyShiftDialogZIndex, copyShiftEmployeeMenuZIndex } from "./copyShiftDialogLayers";

const theme = { zIndex: { modal: 1300, tooltip: 1500 } };

describe("Copy Shift stacking layers", () => {
  it("keeps the dialog above the modal layer and the employee menu above the dialog", () => {
    const dialog = copyShiftDialogZIndex(theme);
    const menu = copyShiftEmployeeMenuZIndex(theme);
    expect(dialog).toBeGreaterThan(theme.zIndex.modal);
    expect(menu).toBeGreaterThan(dialog);
  });
});
