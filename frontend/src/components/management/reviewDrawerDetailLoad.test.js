import { describe, expect, it } from "vitest";
import {
  fetchReviewDrawerAction,
  parseReviewDrawerActionResponse,
  reviewActionRequestParams,
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
    expect(out.error).toBe("Bag not found.");
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
  it("passes the specialty order instance and does not do so for other drawers", async () => {
    const calls = [];
    const getAction = async (dateEt, bagId, params) => {
      calls.push({ dateEt, bagId, params });
      return { data: { ok: true, bag: { bag_id: bagId }, active_bulk_workitems: [] } };
    };
    const specialty = reviewActionRequestParams("specialty_items", {
      bag_id: "REUSE1",
      order_instance_id: 10,
    });
    expect(specialty.params).toEqual({ order_instance_id: 10 });
    await fetchReviewDrawerAction(getAction, "2026-09-19", "REUSE1", {
      params: specialty.params,
    });
    expect(calls[0].params).toEqual({ order_instance_id: 10 });

    const split = reviewActionRequestParams("split_order_review", {
      bag_id: "REUSE1",
      order_instance_id: 99,
    });
    expect(split.params).toEqual({});
    expect(split.missingOrderInstance).toBeUndefined();

    const missing = reviewActionRequestParams("specialty_items", { bag_id: "REUSE1" });
    expect(missing.missingOrderInstance).toBe(true);
  });

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
    expect(out.error).toBe("Bag not found.");
  });
});
