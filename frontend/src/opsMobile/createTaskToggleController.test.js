import { describe, expect, it, vi } from "vitest";
import { createTaskToggleController } from "./createTaskToggleController";
import { allTasksChecked } from "../utils/maintenanceTaskListHelpers";

describe("createTaskToggleController", () => {
  it("calls patch exactly once and blocks rapid duplicate taps", async () => {
    let resolvePatch;
    const patchItem = vi.fn(
      () =>
        new Promise((resolve) => {
          resolvePatch = resolve;
        }),
    );
    let list = {
      id: 5,
      status: "in_progress",
      items: [
        { id: 1, completed: false, task_name_snapshot: "Clean lint traps" },
        { id: 2, completed: false, task_name_snapshot: "Sweep" },
      ],
    };
    const setList = vi.fn((next) => {
      list = next;
    });
    const controller = createTaskToggleController({
      getList: () => list,
      setList,
      patchItem,
      onError: vi.fn(),
      isReadOnly: () => false,
    });

    const p1 = controller.toggle(list.items[0]);
    const p2 = controller.toggle(list.items[0]);
    expect(patchItem).toHaveBeenCalledTimes(1);
    expect(patchItem.mock.calls[0][0]).toMatchObject({
      listId: 5,
      itemId: 1,
      completed: true,
    });

    resolvePatch({
      status: 200,
      data: {
        list: {
          ...list,
          items: [
            { id: 1, completed: true, task_name_snapshot: "Clean lint traps" },
            { id: 2, completed: false, task_name_snapshot: "Sweep" },
          ],
        },
      },
    });
    await p1;
    await p2;
    expect(list.items[0].completed).toBe(true);
    expect(allTasksChecked(list)).toBe(false);
  });

  it("reverts optimistic check when persistence fails", async () => {
    const onError = vi.fn();
    let list = {
      id: 5,
      status: "in_progress",
      items: [{ id: 1, completed: false, task_name_snapshot: "A" }],
    };
    const controller = createTaskToggleController({
      getList: () => list,
      setList: (next) => {
        list = next;
      },
      patchItem: async () => ({ status: 500, data: { ok: false } }),
      onError,
      isReadOnly: () => false,
    });
    await controller.toggle(list.items[0]);
    expect(list.items[0].completed).toBe(false);
    expect(onError).toHaveBeenCalledWith("Couldn’t save. Try again.");
  });

  it("does not call API for read-only completed checklist", async () => {
    const patchItem = vi.fn();
    const list = {
      id: 5,
      status: "completed",
      read_only: true,
      items: [{ id: 1, completed: true, task_name_snapshot: "A" }],
    };
    const controller = createTaskToggleController({
      getList: () => list,
      setList: vi.fn(),
      patchItem,
      onError: vi.fn(),
      isReadOnly: () => true,
    });
    const result = await controller.toggle(list.items[0]);
    expect(result.called).toBe(false);
    expect(patchItem).not.toHaveBeenCalled();
  });

  it("submit stays disabled until every task is checked", () => {
    expect(
      allTasksChecked({
        items: [
          { completed: true, task_name_snapshot: "A" },
          { completed: false, task_name_snapshot: "B" },
        ],
      }),
    ).toBe(false);
    expect(
      allTasksChecked({
        items: [
          { completed: true, task_name_snapshot: "A" },
          { completed: true, task_name_snapshot: "B" },
        ],
      }),
    ).toBe(true);
  });
});
