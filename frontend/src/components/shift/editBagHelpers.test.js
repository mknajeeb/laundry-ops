import { describe, expect, it } from "vitest";
import {
  buildEditBagPayloadDraft,
  describeWeightProvenance,
  formatWeightObservedEt,
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

describe("describeWeightProvenance", () => {
  it("labels historical pre recovery with observed time", () => {
    const d = describeWeightProvenance({
      role: "pre",
      weightLbs: 23.6,
      source: "portal_weight_num_historical",
      observedAt: "2026-07-22 06:24:00",
      attachBatchId: 2807,
    });
    expect(d.helperText).toContain("Recovered from historical portal");
    expect(d.helperText).toContain("06:24");
    expect(d.title).toContain("Batch 2807");
  });

  it("labels current portal post capture", () => {
    const d = describeWeightProvenance({
      role: "post",
      weightLbs: 22.6,
      source: "portal_weight_num",
      observedAt: "2026-07-22T16:45:00",
      attachBatchId: 2815,
    });
    expect(d.helperText).toContain("Captured from portal");
    expect(d.helperText).toContain("16:45");
  });

  it("explains missing pre when post exists", () => {
    const d = describeWeightProvenance({
      role: "pre",
      weightLbs: null,
      needsManagerCorrection: true,
    });
    expect(d.helperText).toMatch(/no recoverable historical portal/i);
  });

  it("does not invent a portal source when weight has no enrichment provenance", () => {
    const d = describeWeightProvenance({
      role: "pre",
      weightLbs: 9.2,
      source: null,
      observedAt: null,
    });
    expect(d.helperText).toBe("Blank = null · 0 is valid");
    expect(d.title).toBe("");
  });
});

describe("formatWeightObservedEt", () => {
  it("formats to MM/DD HH:MM ET", () => {
    expect(formatWeightObservedEt("2026-07-22 06:24:11")).toBe("07/22 06:24 ET");
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
