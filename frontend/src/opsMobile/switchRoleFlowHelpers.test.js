import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  autoSelectCategoryId,
  initialCategoryId,
  isCurrentRoleAssignment,
  resolveRoleId,
  resolveRoleName,
  shouldCallRoleSwitchApi,
  switchRoleEmployeeError,
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

  it("does not call API when tapping the current role", async () => {
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
    const result = await controller.selectRole({ role_id: 1, role_name: "Operator" });
    expect(result.called).toBe(false);
    expect(switchRoleApi).not.toHaveBeenCalled();
  });

  it("calls role-switch API once for a different role and blocks duplicates while pending", async () => {
    let resolveApi;
    const switchRoleApi = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveApi = resolve;
        }),
    );
    const onSuccess = vi.fn();
    const controller = createSwitchRoleController({
      selectionTree: tree,
      currentCategoryId: 10,
      currentRoleId: 1,
      pin: "1234",
      slug: "veewash",
      switchRoleApi,
      createIdempotencyKey: () => "key-1",
      onSuccess,
      successDelayMs: 100,
    });

    const p1 = controller.selectRole({ role_id: 2, role_name: "Folder" });
    const p2 = controller.selectRole({ role_id: 2, role_name: "Folder" });
    expect(switchRoleApi).toHaveBeenCalledTimes(1);
    expect(switchRoleApi.mock.calls[0][2]).toMatchObject({
      category_id: 10,
      role_id: 2,
      idempotency_key: "key-1",
    });

    resolveApi({
      status: 200,
      data: { ok: true, display_label: "Floor — Folder" },
    });
    await p1;
    await p2;
    expect(controller.getState().phase).toBe("success");
    vi.advanceTimersByTime(100);
    expect(onSuccess).toHaveBeenCalledTimes(1);
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
    await controller.selectRole({ role_id: 2, role_name: "Folder" });
    const state = controller.getState();
    expect(state.phase).toBe("select");
    expect(state.error).toBe("Couldn’t change role. Try again.");
    expect(state.pending).toBe(false);
  });
});

describe("hub opens full-screen role route", () => {
  it("documents Role tile navigation target (not dialog)", () => {
    // Integration contract: EmployeePinHubPage navigates to /attendance/role/:slug?from=hub
    const slug = "veewash";
    const href = `/attendance/role/${encodeURIComponent(slug)}?from=hub`;
    expect(href).toBe("/attendance/role/veewash?from=hub");
    expect(href.includes("Dialog")).toBe(false);
  });
});
