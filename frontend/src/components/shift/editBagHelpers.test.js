import { describe, expect, it } from "vitest";
import {
  buildEditBagPayloadDraft,
  mergeBagListRow,
  parseWeightInput,
  validateEditBagDraft,
} from "./editBagHelpers.js";

describe("parseWeightInput", () => {
  it("treats blank as null and 0 as valid", () => {
    expect(parseWeightInput("")).toBeNull();
    expect(parseWeightInput("   ")).toBeNull();
    expect(parseWeightInput("0")).toBe(0);
    expect(parseWeightInput("12.5")).toBe(12.5);
  });
});

describe("validateEditBagDraft", () => {
  it("preserves draft on validation failure (returns error, does not mutate)", () => {
    const draftSections = {
      reason: "try save",
      noChargeable: true,
      noChargeReason: "",
      lines: [{ workitem_id: 1, quantity: 1 }],
      isHd: false,
    };
    const before = structuredClone(draftSections);
    const err = validateEditBagDraft(draftSections);
    expect(err).toMatch(/No Chargeable|no-charge/i);
    expect(draftSections).toEqual(before);
  });

  it("hides bulk requirement for HD (empty lines ok)", () => {
    expect(
      validateEditBagDraft({
        reason: "ok",
        noChargeable: false,
        lines: [],
        isHd: true,
      })
    ).toBe("");
  });
});

describe("buildEditBagPayloadDraft", () => {
  it("includes bath mat + weight in one payload", () => {
    const payload = buildEditBagPayloadDraft({
      draft: {
        service_type: "WF",
        rush_flag: "NON-RUSH",
        pre_weight_lbs: "10",
        post_weight_lbs: "22.5",
        no_chargeable: false,
        completed_by: "Evelin",
      },
      lines: [
        { workitem_id: 9, quantity: 1, name: "Bath Mat" },
        { workitem_id: 2, quantity: 0 },
      ],
      isHd: false,
    });
    expect(payload.post_weight_lbs).toBe(22.5);
    expect(payload.pre_weight_lbs).toBe(10);
    expect(payload.bulk_items).toEqual([{ workitem_id: 9, quantity: 1 }]);
    expect(payload.completion_employee).toBe("Evelin");
  });

  it("clears bulk items for HD", () => {
    const payload = buildEditBagPayloadDraft({
      draft: { service_type: "HD", rush_flag: "RUSH", no_chargeable: false },
      lines: [{ workitem_id: 9, quantity: 1 }],
      isHd: true,
    });
    expect(payload.bulk_items).toEqual([]);
    expect(payload.rack).toBeNull();
  });
});

describe("mergeBagListRow — 42EN4J3VRB stale cache reproducer", () => {
  const BAG = "42EN4J3VRB";
  const bathMat = [
    {
      workitem_id: 1,
      workitem_name: "Bath Mat",
      quantity: 1,
      unit_price: 4,
      line_total: 4,
    },
  ];

  it("does not let list empty bulk_workitems hide persisted Bath Mat", () => {
    const merged = mergeBagListRow({
      listBag: {
        bag_id: BAG,
        bulk_workitems: [],
        dashboard_status: "completed",
      },
      previousBag: {
        bag_id: BAG,
        bulk_workitems: bathMat,
        scans: [{ id: 1 }],
        corrections: [],
        _detailsLoaded: true,
      },
      cachedDetail: null,
      editingBagId: null,
    });
    expect(merged.bulk_workitems).toEqual(bathMat);
    expect(merged._detailsLoaded).toBe(true);
  });

  it("does not merge stale cached empty bulk over detail", () => {
    const merged = mergeBagListRow({
      listBag: { bag_id: BAG, bulk_workitems: [] },
      previousBag: null,
      cachedDetail: {
        bag_id: BAG,
        bulk_workitems: bathMat,
        scans: [],
        corrections: [],
      },
      editingBagId: null,
    });
    expect(merged.bulk_workitems).toEqual(bathMat);
  });

  it("preserves open draft bag during background refresh", () => {
    const open = {
      bag_id: BAG,
      bulk_workitems: bathMat,
      _draftMarker: true,
      _detailsLoaded: true,
    };
    const merged = mergeBagListRow({
      listBag: { bag_id: BAG, bulk_workitems: [], post_weight_lbs: 99 },
      previousBag: open,
      cachedDetail: { bulk_workitems: [] },
      editingBagId: BAG,
    });
    expect(merged._draftMarker).toBe(true);
    expect(merged.bulk_workitems).toEqual(bathMat);
  });
});
