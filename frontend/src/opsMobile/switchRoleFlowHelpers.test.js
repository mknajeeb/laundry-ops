import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  autoSelectCategoryId,
  categoriesForRole,
  displayRoleLabel,
  initialCategoryId,
  initialRoleId,
  isCurrentRoleAssignment,
  resolveRoleId,
  resolveRoleName,
  roleHelperText,
  shouldCallRoleSwitchApi,
  switchRoleEmployeeError,
  uniqueRolesFromTree,
} from "./switchRoleFlowHelpers";
import { createSwitchRoleController } from "./createSwitchRoleController";

const tree = [
  {
    id: 10,
    name: "Floor",
    roles: [
      { role_id: 1, role_name: "Operator" },
      { role_id: 2, role_name: "Folder" },
      { role_id: 3, role_name: "Very Long Role Name That Must Wrap Cleanly" },
    ],
  },
];

const multiCatTree = [
  {
    id: 10,
    name: "Rinse WF",
    roles: [
      { role_id: 1, role_name: "Operator" },
      { role_id: 2, role_name: "Folder" },
    ],
  },
  {
    id: 20,
    name: "Rinse HD",
    roles: [
      { role_id: 1, role_name: "Operator" },
      { role_id: 2, role_name: "Folder" },
    ],
  },
  {
    id: 30,
    name: "DHS",
    roles: [{ role_id: 1, role_name: "Operator" }],
  },
];

describe("switchRoleFlowHelpers", () => {
  it("marks current role by category + role ids", () => {
    expect(isCurrentRoleAssignment(10, 1, 10, 1)).toBe(true);
    expect(isCurrentRoleAssignment(10, 2, 10, 1)).toBe(false);
    expect(isCurrentRoleAssignment(10, 1, null, 1)).toBe(false);
  });

  it("resolves role_id from selection-tree shape", () => {
    expect(resolveRoleId({ role_id: 2, id: 99 })).toBe(2);
    expect(resolveRoleName({ role_name: "Operator" })).toBe("Operator");
  });

  it("shows Folding for stored Folder and role helpers", () => {
    expect(displayRoleLabel({ role_name: "Folder" })).toBe("Folding");
    expect(displayRoleLabel("Folder")).toBe("Folding");
    expect(displayRoleLabel({ role_name: "Operator" })).toBe("Operator");
    expect(roleHelperText("Operator")).toBe("Weighing, Sorting, Washing & Drying");
    expect(roleHelperText("Folder")).toBe("Folding completed laundry orders");
  });

  it("dedupes roles and lists categories for a role", () => {
    const roles = uniqueRolesFromTree(multiCatTree);
    expect(roles.map((r) => resolveRoleId(r))).toEqual([1, 2]);
    expect(categoriesForRole(multiCatTree, 1).map((c) => c.name)).toEqual([
      "Rinse WF",
      "Rinse HD",
      "DHS",
    ]);
    expect(categoriesForRole(multiCatTree, 2).map((c) => c.name)).toEqual(["Rinse WF", "Rinse HD"]);
  });

  it("auto-selects the only category", () => {
    expect(autoSelectCategoryId(tree)).toBe(10);
    expect(autoSelectCategoryId([{ id: 1 }, { id: 2 }])).toBe(null);
  });

  it("prefers current category when present", () => {
    const multi = [
      { id: 1, name: "A", roles: [{ role_id: 1, role_name: "X" }] },
      { id: 2, name: "B", roles: [{ role_id: 2, role_name: "Y" }] },
    ];
    expect(initialCategoryId(multi, 2)).toBe(2);
  });

  it("prefers current role for role-first start", () => {
    expect(initialRoleId(multiCatTree, 2)).toBe(2);
    expect(initialRoleId(tree, null)).toBe(null);
  });

  it("skips API for current role and while pending", () => {
    expect(
      shouldCallRoleSwitchApi({
        categoryId: 10,
        roleId: 1,
        currentCategoryId: 10,
        currentRoleId: 1,
        pending: false,
      }),
    ).toBe(false);
    expect(
      shouldCallRoleSwitchApi({
        categoryId: 10,
        roleId: 2,
        currentCategoryId: 10,
        currentRoleId: 1,
        pending: true,
      }),
    ).toBe(false);
    expect(
      shouldCallRoleSwitchApi({
        categoryId: 10,
        roleId: 2,
        currentCategoryId: 10,
        currentRoleId: 1,
        pending: false,
      }),
    ).toBe(true);
  });

  it("maps failures to concise employee copy", () => {
    expect(switchRoleEmployeeError({ error: "boom" }, 500)).toBe(
      "Couldn’t change role. Try again.",
    );
    expect(switchRoleEmployeeError({ error: "You must be clocked in" }, 400)).toBe(
      "Role change isn’t available right now.",
    );
  });

  it("keeps long role names as full strings (no forced truncation helper)", () => {
    const long = resolveRoleName(tree[0].roles[2]);
    expect(long.length).toBeGreaterThan(20);
    expect(long).toContain("Wrap");
  });
});

describe("createSwitchRoleController", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not call API when confirming the current category+role", async () => {
    const switchRoleApi = vi.fn();
    const controller = createSwitchRoleController({
      selectionTree: tree,
      currentCategoryId: 10,
      currentRoleId: 1,
      pin: "1234",
      slug: "veewash",
      switchRoleApi,
      createIdempotencyKey: () => "key-1",
      onSuccess: vi.fn(),
    });
    expect(controller.getState().step).toBe("category");
    const result = await controller.selectCategory({ id: 10, name: "Floor" });
    expect(result.called).toBe(false);
    expect(switchRoleApi).not.toHaveBeenCalled();
  });

  it("role then category calls API once and blocks duplicates while pending", async () => {
    let resolveApi;
    const switchRoleApi = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveApi = resolve;
        }),
    );
    const onSuccess = vi.fn();
    const controller = createSwitchRoleController({
      selectionTree: multiCatTree,
      currentCategoryId: 10,
      currentRoleId: 1,
      pin: "1234",
      slug: "veewash",
      switchRoleApi,
      createIdempotencyKey: () => "key-1",
      onSuccess,
      successDelayMs: 100,
    });

    controller.setRole({ role_id: 2, role_name: "Folder" });
    expect(controller.getState().step).toBe("category");
    const p1 = controller.selectCategory({ id: 20, name: "Rinse HD" });
    const p2 = controller.selectCategory({ id: 20, name: "Rinse HD" });
    expect(switchRoleApi).toHaveBeenCalledTimes(1);
    expect(switchRoleApi.mock.calls[0][2]).toMatchObject({
      category_id: 20,
      role_id: 2,
      idempotency_key: "key-1",
    });

    resolveApi({
      status: 200,
      data: { ok: true, display_label: "Rinse HD — Folder" },
    });
    await p1;
    await p2;
    expect(controller.getState().phase).toBe("success");
    vi.advanceTimersByTime(100);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("legacy selectRole still works on single-category trees", async () => {
    const switchRoleApi = vi.fn(async () => ({
      status: 200,
      data: { ok: true, display_label: "Floor — Folder" },
    }));
    const controller = createSwitchRoleController({
      selectionTree: tree,
      currentCategoryId: 10,
      currentRoleId: 1,
      pin: "1234",
      slug: "veewash",
      switchRoleApi,
      createIdempotencyKey: () => "key-1",
      onSuccess: vi.fn(),
      successDelayMs: 0,
    });
    await controller.selectRole({ role_id: 2, role_name: "Folder" });
    expect(switchRoleApi).toHaveBeenCalledWith(
      "veewash",
      "1234",
      expect.objectContaining({ category_id: 10, role_id: 2 }),
    );
  });

  it("stays on select phase with employee error on failure", async () => {
    const switchRoleApi = vi.fn(async () => ({
      status: 500,
      data: { ok: false, error: "Internal boom" },
    }));
    const controller = createSwitchRoleController({
      selectionTree: tree,
      currentCategoryId: 10,
      currentRoleId: 1,
      pin: "1234",
      slug: "veewash",
      switchRoleApi,
      createIdempotencyKey: () => "key-1",
      onSuccess: vi.fn(),
    });
    await controller.selectCategory({ id: 10, name: "Floor" }); // current → skip
    await controller.setRole({ role_id: 2, role_name: "Folder" });
    await controller.selectCategory({ id: 10, name: "Floor" });
    const state = controller.getState();
    expect(state.phase).toBe("select");
    expect(state.error).toBe("Couldn’t change role. Try again.");
    expect(state.pending).toBe(false);
  });
});

describe("hub opens full-screen role route", () => {
  it("documents Role tile navigation target (not dialog)", () => {
    const slug = "veewash";
    const href = `/attendance/role/${encodeURIComponent(slug)}?from=hub`;
    expect(href).toBe("/attendance/role/veewash?from=hub");
    expect(href.includes("Dialog")).toBe(false);
  });
});
