import { describe, expect, it } from "vitest";
import {
  addReportPhotos,
  displayFoundEvent,
  displayFoundLocation,
  filterIdentifiers,
  foundLocationLabel,
  identifierChoices,
  locationNumberMode,
  removeReportPhoto,
  replaceReportPhoto,
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

  it("translates a stored dryer label without changing the machine number", () => {
    const t = (key) => ({ "lostFound.location.dryer": "Secadora" }[key] || key);
    expect(displayFoundLocation({ location_kind: "dryer", location_number: "D4", location_label: "Dryer D4" }, t)).toBe("Secadora 4");
    expect(displayFoundEvent("reported", (key) => (key === "lostFound.event.reported" ? "Reportado" : key))).toBe("Reportado");
  });

  it("uses machine identifiers when the facility has them", () => {
    expect(identifierChoices("washer", { washers: ["W23-30-VW"] })).toEqual(["W23-30-VW"]);
    expect(identifierChoices("dryer", { dryers: ["D1-50-VW"] })).toEqual(["D1-50-VW"]);
    expect(identifierChoices("folding_table", {})).toEqual([]);
    expect(foundLocationLabel({ kind: "washer", number: "W23-30-VW" })).toBe("Washer W23-30-VW");
  });

  it("filters configured numbers and edits the photo list before upload", () => {
    const dryers = ["D1", "D2", "D10", "D40"];
    expect(filterIdentifiers(dryers, "d1")).toEqual(["D1", "D10"]);
    const first = addReportPhotos([], [{ size: 10, type: "image/jpeg", name: "a.jpg" }]);
    const both = addReportPhotos(first, [
      { size: 12, type: "image/png", name: "b.png" },
      { size: 0, type: "image/png", name: "empty.png" },
    ]);
    expect(both).toHaveLength(2);
    const replaced = replaceReportPhoto(both, both[0].id, { size: 20, type: "image/jpeg", name: "c.jpg" });
    expect(replaced[0].file.name).toBe("c.jpg");
    expect(removeReportPhoto(replaced, both[1].id)).toHaveLength(1);
    expect(identifierChoices("dehumidifier", { dehumidifiers: ["DH-1"] })).toEqual(["DH-1"]);
  });
});
