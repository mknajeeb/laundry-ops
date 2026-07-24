import { describe, expect, it, vi } from "vitest";
import {
  compactQtyDiff,
  emptyFloorFilterMessage,
  filterFloorStockItems,
  isFloorInventoryWorkflow,
  itemIsDone,
  itemIsLow,
  itemIsOut,
  stockCheckProgress,
} from "./inventoryFloorHelpers";
import {
  createStockDraftAutosave,
  createStockSubmitController,
} from "../opsMobile/createStockDraftAutosave";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { canAccessInventoryTab } from "./inventoryRoleHelpers";

const root = path.dirname(fileURLToPath(import.meta.url));

const SAMPLE = [
  {
    id: 1,
    name: "Bleach",
    sku: "BL-1",
    barcode: "111",
    tracking_mode: "QUANTITY",
    current_on_hand: 18,
    reorder_level: 10,
    due_for_check_today: true,
    is_active: true,
    category_name: "Chemicals",
  },
  {
    id: 2,
    name: "Trash Bags",
    tracking_mode: "STATUS",
    status_level: "LOW",
    due_for_check_today: true,
    is_active: true,
  },
  {
    id: 3,
    name: "Soap",
    tracking_mode: "QUANTITY",
    current_on_hand: 0,
    reorder_level: 5,
    due_for_check_today: true,
    is_active: true,
    needs_recount: true,
  },
];

describe("inventoryFloorHelpers", () => {
  it("detects floor workflow from PIN hub app session, not viewport", () => {
    expect(isFloorInventoryWorkflow({ pinHubApp: { organization_slug: "veewash" } })).toBe(true);
    expect(isFloorInventoryWorkflow({ pinHubApp: null })).toBe(false);
  });

  it("filters Low / Out / Recount over existing item fields", () => {
    expect(itemIsLow(SAMPLE[1])).toBe(true);
    expect(itemIsOut(SAMPLE[2])).toBe(true);
    expect(filterFloorStockItems(SAMPLE, "low").map((i) => i.id)).toEqual([2]);
    expect(filterFloorStockItems(SAMPLE, "out").map((i) => i.id)).toEqual([3]);
    expect(filterFloorStockItems(SAMPLE, "recount", { draftRecounts: { 1: true } }).map((i) => i.id)).toEqual([
      1, 3,
    ]);
  });

  it("searches by name, SKU, and barcode", () => {
    expect(filterFloorStockItems(SAMPLE, "count", { search: "bleach" })[0].id).toBe(1);
    expect(filterFloorStockItems(SAMPLE, "count", { search: "BL-1" })[0].id).toBe(1);
    expect(filterFloorStockItems(SAMPLE, "count", { search: "111" })[0].id).toBe(1);
  });

  it("shows difference only when changed", () => {
    expect(compactQtyDiff("18", 18)).toBeNull();
    expect(compactQtyDiff("16", 18)).toBe(-2);
    expect(compactQtyDiff("", 18)).toBeNull();
  });

  it("tracks progress with existing done semantics", () => {
    const p = stockCheckProgress(
      SAMPLE,
      { 1: "16" },
      { 2: "OK" },
      { 3: true },
    );
    expect(p.total).toBe(3);
    expect(p.done).toBe(3);
    expect(itemIsDone(SAMPLE[0], { 1: "" }, {}, {})).toBe(false);
  });

  it("empty filter messages are concise", () => {
    expect(emptyFloorFilterMessage("low")).toBe("No low items");
    expect(emptyFloorFilterMessage("out")).toBe("No out-of-stock items");
    expect(emptyFloorFilterMessage("recount")).toBe("No recounts needed");
    expect(emptyFloorFilterMessage("count")).toBe("No stock items");
  });

  it("manager tab access remains role/permission based", () => {
    expect(canAccessInventoryTab("admin", "dashboard", () => false)).toBe(true);
    expect(canAccessInventoryTab("admin", "settings", () => false)).toBe(true);
    expect(canAccessInventoryTab("floor", "settings", () => false)).toBe(false);
    expect(canAccessInventoryTab("floor", "dashboard", () => false)).toBe(true);
  });
});

describe("stock draft autosave + submit controllers", () => {
  it("debounces and calls existing draft save once for rapid changes", async () => {
    vi.useFakeTimers();
    const saveDraft = vi.fn(async () => ({}));
    const controller = createStockDraftAutosave({
      saveDraft,
      buildLines: () => [{ item_id: 1, counted_qty: 1 }],
      getNotesMeta: () => "Draft",
      debounceMs: 450,
      onSaved: vi.fn(),
      onError: vi.fn(),
    });
    controller.schedule();
    controller.schedule();
    controller.schedule();
    expect(saveDraft).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(450);
    expect(saveDraft).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("save failure surfaces retry message and does not pretend success", async () => {
    const onError = vi.fn();
    const onSaved = vi.fn();
    const controller = createStockDraftAutosave({
      saveDraft: async () => {
        throw new Error("fail");
      },
      buildLines: () => [{ item_id: 1 }],
      debounceMs: 0,
      onSaved,
      onError,
    });
    const result = await controller.flushNow();
    expect(result.ok).toBe(false);
    expect(onSaved).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith("Couldn’t save. Try again.");
  });

  it("submit calls existing endpoint exactly once and blocks duplicates", async () => {
    let resolve;
    const submitCheck = vi.fn(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    const controller = createStockSubmitController({
      buildLines: () => [{ item_id: 1, counted_qty: 2 }],
      submitCheck,
      onSuccess: vi.fn(),
      onError: vi.fn(),
    });
    const p1 = controller.submit();
    const p2 = controller.submit();
    expect(submitCheck).toHaveBeenCalledTimes(1);
    resolve({ data: { lines_submitted: 1 } });
    await p1;
    await p2;
  });

  it("submit failure stays editable (no success callback)", async () => {
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const controller = createStockSubmitController({
      buildLines: () => [{ item_id: 1, counted_qty: 2 }],
      submitCheck: async () => {
        throw new Error("fail");
      },
      onSuccess,
      onError,
    });
    const result = await controller.submit();
    expect(result.ok).toBe(false);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith("Couldn’t submit. Try again.");
  });
});

describe("floor stock presentation contracts", () => {
  const cardSrc = readFileSync(path.join(root, "../opsMobile/OpsFloorStockCard.jsx"), "utf8");
  const flowSrc = readFileSync(path.join(root, "../opsMobile/OpsFloorStockFlow.jsx"), "utf8");
  const pageSrc = readFileSync(path.join(root, "../pages/InventoryPage.jsx"), "utf8");

  it("PIN Stock opens floor Count shell without manager tabs", () => {
    expect(pageSrc).toContain("isFloorInventoryWorkflow");
    expect(pageSrc).toContain("OpsFloorStockFlow");
    expect(pageSrc).toContain("floorWorkflow");
    expect(flowSrc).toContain('key: "count"');
    expect(flowSrc).not.toContain("Dashboard");
    expect(flowSrc).not.toContain("Purchase Orders");
    expect(flowSrc).not.toContain("Start New Weekly Check");
  });

  it("quantity stepper is primary; notes collapsed by default", () => {
    expect(cardSrc).toContain("width: 56");
    expect(cardSrc).toContain("height: 56");
    expect(cardSrc).toContain('fontSize: "1.65rem"');
    expect(cardSrc).toContain("useState(Boolean(String(noteValue || \"\").trim()))");
    expect(cardSrc).toContain("Current {current}");
    expect(cardSrc).toContain("Needs recount");
  });

  it("status-only card has OK LOW OUT without qty panels", () => {
    expect(cardSrc).toContain('STATUS_KEYS = ["OK", "LOW", "OUT"]');
    expect(cardSrc).not.toContain("Current / Entered / Difference");
  });

  it("sticky submit is the only primary floor action", () => {
    expect(flowSrc).toContain("Submit Stock Check");
    expect(flowSrc).not.toContain("Save Draft");
    expect(flowSrc).toContain("Stock check submitted");
    expect(flowSrc).toContain("Done");
  });

  it("long names wrap without ellipsis dependency", () => {
    expect(cardSrc).toContain("overflowWrap: \"anywhere\"");
    expect(cardSrc).toContain("whiteSpace: \"normal\"");
  });

  it("manager page retains Dashboard default when not floor", () => {
    expect(pageSrc).toContain('useState("dashboard")');
    expect(pageSrc).toContain("DashboardTab");
    expect(pageSrc).toContain("StockCheckTab");
  });
});
