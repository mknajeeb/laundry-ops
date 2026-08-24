import { describe, expect, it } from "vitest";
import {
  fetchReviewDrawerAction,
  parseReviewDrawerActionResponse,
} from "./reviewDrawerDetailLoad";

describe("parseReviewDrawerActionResponse", () => {
  it("parses a normal specialty bag with catalog", () => {
    const out = parseReviewDrawerActionResponse({
      ok: true,
      bag: {
        bag_id: "BAG01",
        has_specialty_bulk: true,
        bulk_workitems: [{ workitem_id: 1, quantity: 2 }],
      },
      active_bulk_workitems: [{ id: 1, name: "Bath Mat", current_unit_price: 4 }],
    });
    expect(out.ok).toBe(true);
    expect(out.error).toBeNull();
    expect(out.bag?.bag_id).toBe("BAG01");
    expect(out.catalog).toHaveLength(1);
  });

  it("accepts zero-scan bags with no optional bulk records", () => {
    const out = parseReviewDrawerActionResponse({
      ok: true,
      bag: {
        bag_id: "EZRTRBZGGJ",
        has_specialty_bulk: true,
        reason_codes: ["WF_BULK_WORKITEM_REVIEW"],
        bulk_workitems: [],
      },
      active_bulk_workitems: [{ id: 1, name: "Bath Mat", current_unit_price: 4 }],
    });
    expect(out.ok).toBe(true);
    expect(out.bag?.bulk_workitems).toEqual([]);
    expect(out.catalog).toHaveLength(1);
  });

  it("surfaces endpoint errors without fabricating bag data", () => {
    const out = parseReviewDrawerActionResponse({
      ok: false,
      error: "bag_not_found",
    });
    expect(out.ok).toBe(false);
    expect(out.error).toBe("bag_not_found");
    expect(out.bag).toBeNull();
    expect(out.catalog).toEqual([]);
  });

  it("tolerates missing optional fields", () => {
    const out = parseReviewDrawerActionResponse({
      ok: true,
      bag: { bag_id: "BAG02", has_specialty_bulk: true },
    });
    expect(out.ok).toBe(true);
    expect(out.catalog).toEqual([]);
  });
});

describe("fetchReviewDrawerAction", () => {
  it("always resolves loading callers on success", async () => {
    const getAction = async () => ({
      data: {
        ok: true,
        bag: { bag_id: "BAG03", has_specialty_bulk: true },
        active_bulk_workitems: [],
      },
    });
    await expect(fetchReviewDrawerAction(getAction, "2026-08-24", "BAG03")).resolves.toMatchObject({
      ok: true,
      bag: { bag_id: "BAG03" },
    });
  });

  it("always resolves loading callers on transport failure", async () => {
    const getAction = async () => {
      const err = new Error("network");
      err.response = { data: { error: "server_error" } };
      throw err;
    };
    await expect(fetchReviewDrawerAction(getAction, "2026-08-24", "BAG03")).rejects.toMatchObject({
      response: { data: { error: "server_error" } },
    });
  });

  it("propagates secondary fetch failures as structured errors", async () => {
    const getAction = async () => ({
      data: { ok: false, error: "bag_not_found" },
    });
    const out = await fetchReviewDrawerAction(getAction, "2026-08-24", "MISSING");
    expect(out.ok).toBe(false);
    expect(out.error).toBe("bag_not_found");
  });
});
