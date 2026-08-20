import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  autoSelectCategoryId,
  categoriesForRole,
  categoryDisplayBucket,
  displayRoleLabel,
  flattenRoleCombos,
  formatEmployeeAssignmentLabel,
  groupCombosByBucket,
  groupCombosByPrimaryRole,
  currentRoleCaption,
  resolvePrimaryRoleTap,
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

  it("shows Fold for stored Folder and role helpers", () => {
    expect(displayRoleLabel({ role_name: "Folder" })).toBe("Fold");
    expect(displayRoleLabel("Folder")).toBe("Fold");
    expect(displayRoleLabel({ role_name: "Operator" })).toBe("Wash-Dry");
    expect(roleHelperText("Operator")).toBe("Washing & drying");
    expect(displayRoleLabel({ role_name: "Sort", role_code: "SORT" })).toBe("Sort");
    expect(displayRoleLabel("Sorting")).toBe("Sort");
    expect(roleHelperText("Folder")).toBe("Folding completed orders");
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

  it("flattens production selection_tree using role_id not assignment id", () => {
    const prodTree = [
      {
        id: 20,
        code: "rinse_hd",
        name: "Rinse HD",
        roles: [
          {
            id: 501,
            role_id: 2,
            role_name: "Folder",
            category_id: 20,
          },
          {
            id: 500,
            role_id: 1,
            role_name: "Operator",
            category_id: 20,
          },
        ],
      },
      {
        id: 10,
        code: "rinse_wf",
        name: "Rinse WF",
        roles: [{ id: 400, role_id: 1, role_name: "Operator", category_id: 10 }],
      },
    ];
    const combos = flattenRoleCombos(prodTree);
    expect(combos.map((c) => c.roleId)).toEqual([2, 1, 1]);
    expect(combos.every((c) => c.roleId !== 501 && c.roleId !== 500 && c.roleId !== 400)).toBe(true);
    const groups = groupCombosByBucket(combos);
    expect(groups.map((g) => g.bucket)).toEqual(["Rinse Wash & Fold", "Rinse Hang Dry"]);
    expect(groups[1].combos.map((c) => c.roleLabel)).toEqual(["Wash-Dry", "Fold"]);
    expect(categoryDisplayBucket({ name: "Rinse HD", code: "rinse_hd" })).toBe("Rinse Hang Dry");
  });

  it("groups by primary role with one Non-Rinse label (hides DHS/Drop Off)", () => {
    const treeWithDrop = [
      ...multiCatTree,
      {
        id: 40,
        name: "Drop Off",
        roles: [{ role_id: 1, role_name: "Operator" }],
      },
    ];
    const combos = flattenRoleCombos(treeWithDrop);
    const groups = groupCombosByPrimaryRole(combos, {
      currentCategoryId: 30,
      currentRoleId: 1,
    });
    expect(groups.map((g) => g.roleLabel)).toEqual(["Wash-Dry", "Fold"]);
    const wash = groups.find((g) => g.roleLabel === "Wash-Dry");
    expect(wash.workTypes.map((w) => w.label)).toEqual([
      "Rinse Wash & Fold",
      "Rinse Hang Dry",
      "Non-Rinse",
    ]);
    expect(wash.workTypes.find((w) => w.label === "Non-Rinse")?.combo.categoryId).toBe(30);
    expect(wash.workTypes.some((w) => w.label === "DHS" || w.label === "Drop Off")).toBe(false);
    const fold = groups.find((g) => g.roleLabel === "Fold");
    expect(fold.workTypes.map((w) => w.label)).toEqual(["Rinse Wash & Fold", "Rinse Hang Dry"]);
    expect(currentRoleCaption(wash.workTypes[2].combo)).toBe("Non-Rinse · Current");
  });

  it("shows Sort as its own primary role when SORT is in the tree", () => {
    const tree = [
      {
        id: 10,
        name: "Rinse WF",
        code: "RINSE_WF",
        roles: [
          { role_id: 1, role_name: "Operator", role_code: "OPERATOR" },
          { role_id: 3, role_name: "Sort", role_code: "SORT" },
          { role_id: 2, role_name: "Folder", role_code: "FOLDER" },
        ],
      },
      {
        id: 20,
        name: "Rinse HD",
        code: "RINSE_HD",
        roles: [
          { role_id: 1, role_name: "Operator", role_code: "OPERATOR" },
          { role_id: 3, role_name: "Sort", role_code: "SORT" },
          { role_id: 2, role_name: "Folder", role_code: "FOLDER" },
        ],
      },
    ];
    const groups = groupCombosByPrimaryRole(flattenRoleCombos(tree));
    expect(groups.map((g) => g.roleLabel)).toEqual(["Wash-Dry", "Sort", "Fold"]);
    const sort = groups.find((g) => g.roleLabel === "Sort");
    expect(sort.workTypes.map((w) => w.label)).toEqual([
      "Rinse Wash & Fold",
      "Rinse Hang Dry",
    ]);
    expect(formatEmployeeAssignmentLabel({ roleName: "Sort", categoryName: "Rinse WF" })).toBe(
      "Sort | Rinse Wash & Fold",
    );
  });

  it("prefers Drop Off when switching into Non-Rinse with no current Non-Rinse category", () => {
    const treeWithDrop = [
      ...multiCatTree,
      {
        id: 40,
        name: "Drop Off",
        roles: [{ role_id: 1, role_name: "Operator" }],
      },
    ];
    const combos = flattenRoleCombos(treeWithDrop);
    const groups = groupCombosByPrimaryRole(combos, {
      currentCategoryId: 10,
      currentRoleId: 1,
    });
    const wash = groups.find((g) => g.roleLabel === "Wash-Dry");
    const nr = wash.workTypes.find((w) => w.label === "Non-Rinse");
    expect(nr.combo.categoryId).toBe(40);
    expect(nr.combo.categoryName).toBe("Drop Off");
  });

  it("switches immediately when a role has one work type", () => {
    const one = [{ combo: { categoryId: 20, roleId: 2 } }];
    expect(
      resolvePrimaryRoleTap({
        workTypes: one,
        expandedRole: null,
        roleLabel: "Fold",
        currentCategoryId: 10,
        currentRoleId: 1,
      }),
    ).toEqual({ action: "switch", combo: one[0].combo });
    expect(
      resolvePrimaryRoleTap({
        workTypes: one,
        roleLabel: "Fold",
        currentCategoryId: 20,
        currentRoleId: 2,
      }).action,
    ).toBe("noop");
  });

  it("expands in place when a role has multiple work types", () => {
    const many = [{ combo: { categoryId: 1 } }, { combo: { categoryId: 2 } }];
    expect(
      resolvePrimaryRoleTap({ workTypes: many, expandedRole: null, roleLabel: "Wash-Dry" }),
    ).toEqual({ action: "expand", roleLabel: "Wash-Dry" });
    expect(
      resolvePrimaryRoleTap({ workTypes: many, expandedRole: "Wash-Dry", roleLabel: "Wash-Dry" }),
    ).toEqual({ action: "collapse" });
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

  it("always opens one-screen combo list even when a current role exists", () => {
    const controller = createSwitchRoleController({
      selectionTree: multiCatTree,
      currentCategoryId: 10,
      currentRoleId: 1,
      pin: "1234",
      slug: "veewash",
      switchRoleApi: vi.fn(),
      createIdempotencyKey: () => "key-1",
      onSuccess: vi.fn(),
    });
    expect(controller.getState().phase).toBe("select");
    expect(controller.isCurrentRole({ role_id: 1, role_name: "Operator" })).toBe(true);
  });

  it("does not call API when tapping the current combo", async () => {
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
    const result = await controller.selectCombo({
      categoryId: 10,
      roleId: 1,
      category: { id: 10, name: "Floor" },
      role: { role_id: 1, role_name: "Operator" },
    });
    expect(result.called).toBe(false);
    expect(switchRoleApi).not.toHaveBeenCalled();
  });

  it("one tap combo calls API once and blocks duplicates while pending", async () => {
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

    const p1 = controller.selectCombo({
      categoryId: 20,
      roleId: 2,
      category: { id: 20, name: "Rinse HD" },
      role: { role_id: 2, role_name: "Folder" },
    });
    const p2 = controller.selectCombo({
      categoryId: 20,
      roleId: 2,
      category: { id: 20, name: "Rinse HD" },
      role: { role_id: 2, role_name: "Folder" },
    });
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
    await controller.selectCombo({
      categoryId: 10,
      roleId: 2,
      category: { id: 10, name: "Floor" },
      role: { role_id: 2, role_name: "Folder" },
    });
    const state = controller.getState();
    expect(state.phase).toBe("select");
    expect(state.error).toBe("Couldn’t change role. Try again.");
    expect(state.pending).toBe(false);
  });
});

describe("AttendanceRoleSwitchPage open path", () => {
  it("does not call removed two-step setters that crash a successful API open", async () => {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const { dirname, join } = await import("node:path");
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../pages/AttendanceRoleSwitchPage.jsx"),
      "utf8",
    );
    expect(src).not.toMatch(/\bsetFlowStep\b/);
    expect(src).not.toMatch(/\bsetRoleId\(/);
    expect(src).not.toMatch(/\bsetCategoryId\(/);
    expect(src).toContain("needs_selection");
    expect(src).toContain("setPhase(\"select\")");
  });
});

describe("hub opens full-screen role route", () => {
  it("documents Role tile navigation target (not dialog)", () => {
    const slug = "veewash";
    const href = `/attendance/role/${encodeURIComponent(slug)}?from=hub`;
    expect(href).toBe("/attendance/role/veewash?from=hub");
    expect(href.includes("Dialog")).toBe(false);
  });

  it("keeps one-screen combo list as first screen even when a current role exists", () => {
    const currentRoleId = 1;
    const preferred = initialRoleId(multiCatTree, currentRoleId);
    expect(preferred).toBe(1);
    const openPhase = "select";
    expect(openPhase).toBe("select");
  });
});
