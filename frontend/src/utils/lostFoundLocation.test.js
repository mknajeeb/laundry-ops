import { describe, expect, it } from "vitest";
import {
  foundLocationLabel,
  identifierChoices,
  locationNumberMode,
  validateFoundLocation,
} from "./lostFoundLocation";

describe("found item location", () => {
  it("requires a number for washer, dryer, and folding table", () => {
    for (const kind of ["washer", "dryer", "folding_table"]) {
      expect(locationNumberMode(kind)).toBe("required");
      expect(validateFoundLocation({ kind, number: "", detail: "" })).toBe("location_number_required");
      expect(validateFoundLocation({ kind, number: "4", detail: "" })).toBe("");
    }
  });

  it("does not require a number for the floor", () => {
    expect(locationNumberMode("floor")).toBe("none");
    expect(validateFoundLocation({ kind: "floor", number: "", detail: "" })).toBe("");
    expect(foundLocationLabel({ kind: "floor" })).toBe("Floor");
  });

  it("keeps a cart number optional", () => {
    expect(locationNumberMode("cart")).toBe("optional");
    expect(validateFoundLocation({ kind: "cart", number: "", detail: "" })).toBe("");
    expect(foundLocationLabel({ kind: "cart", number: "2" })).toBe("Cart 2");
  });

  it("requires a short description for other", () => {
    expect(locationNumberMode("other")).toBe("detail");
    expect(validateFoundLocation({ kind: "other", detail: "a" })).toBe("location_detail_required");
    expect(validateFoundLocation({ kind: "other", detail: "by the office" })).toBe("");
    expect(foundLocationLabel({ kind: "other", detail: "by the office" })).toBe("by the office");
  });

  it("uses machine identifiers when the facility has them", () => {
    expect(identifierChoices("washer", { washers: ["W23-30-VW"] })).toEqual(["W23-30-VW"]);
    expect(identifierChoices("dryer", { dryers: ["D1-50-VW"] })).toEqual(["D1-50-VW"]);
    expect(identifierChoices("folding_table", {})).toEqual([]);
    expect(foundLocationLabel({ kind: "washer", number: "W23-30-VW" })).toBe("Washer W23-30-VW");
  });
});
