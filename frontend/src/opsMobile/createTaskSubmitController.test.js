import { describe, expect, it, vi } from "vitest";
import { createTaskSubmitController } from "./createTaskSubmitController";
import { isCompletedStatus, statusLabel } from "../utils/maintenanceTaskListHelpers";

describe("createTaskSubmitController", () => {
  function makeList(overrides = {}) {
    return {
      id: 9,
      status: "in_progress",
      items: [
        { id: 1, completed: true, task_name_snapshot: "Clean lint traps" },
        { id: 2, completed: true, task_name_snapshot: "Sweep" },
      ],
      ...overrides,
    };
  }

  it("keeps submit disabled while any task is unchecked", () => {
    let list = makeList({
      items: [
        { id: 1, completed: true },
        { id: 2, completed: false },
      ],
    });
    const controller = createTaskSubmitController({
      getList: () => list,
      setList: (n) => {
        list = n;
      },
      submitList: vi.fn(),
      getSessionToken: () => "tok",
      onError: vi.fn(),
    });
    expect(controller.canSubmit()).toBe(false);
  });

  it("enables submit when every task is checked", () => {
    const controller = createTaskSubmitController({
      getList: () => makeList(),
      setList: vi.fn(),
      submitList: vi.fn(),
      getSessionToken: () => "tok",
      onError: vi.fn(),
    });
    expect(controller.canSubmit()).toBe(true);
  });

  it("calls existing submit API exactly once and blocks duplicates while pending", async () => {
    let resolveSubmit;
    const submitList = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveSubmit = resolve;
        }),
    );
    let list = makeList();
    const controller = createTaskSubmitController({
      getList: () => list,
      setList: (n) => {
        list = n;
      },
      submitList,
      getSessionToken: () => "tok",
      onError: vi.fn(),
    });

    const p1 = controller.submit();
    const p2 = controller.submit();
    expect(submitList).toHaveBeenCalledTimes(1);
    expect(submitList.mock.calls[0][0]).toEqual({ token: "tok", listId: 9 });

    resolveSubmit({
      status: 200,
      data: {
        ok: true,
        list: { ...list, status: "completed", read_only: true },
      },
    });
    await p1;
    await p2;
    expect(list.status).toBe("completed");
    expect(list.read_only).toBe(true);
    expect(isCompletedStatus(list.status)).toBe(true);
    expect(statusLabel(list.status)).toBe("Completed");
  });

  it("on submit failure keeps checklist editable and shows error", async () => {
    const onError = vi.fn();
    let list = makeList();
    const controller = createTaskSubmitController({
      getList: () => list,
      setList: (n) => {
        list = n;
      },
      submitList: async () => ({ status: 500, data: { ok: false } }),
      getSessionToken: () => "tok",
      onError,
    });
    const result = await controller.submit();
    expect(result.ok).toBe(false);
    expect(list.status).toBe("in_progress");
    expect(list.read_only).toBeFalsy();
    expect(onError).toHaveBeenCalledWith("Couldn’t submit. Try again.");
    expect(controller.canSubmit()).toBe(true);
  });
});
