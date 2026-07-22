/**
 * CopyableBagId interaction contracts.
 */
import { describe, expect, it, vi } from "vitest";
import { createCopyableBagIdPointerHandlers } from "./CopyableBagId.jsx";

function mockEvent(overrides = {}) {
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    key: undefined,
    ...overrides,
  };
}

describe("createCopyableBagIdPointerHandlers", () => {
  it("click copies via handler and stops propagation (accordion must not toggle)", () => {
    const copied = [];
    const copyFn = vi.fn(() => {
      copied.push("15M7MCEK4J");
    });
    const handlers = createCopyableBagIdPointerHandlers(copyFn);
    const e = mockEvent();
    handlers.onClick(e);
    expect(e.preventDefault).toHaveBeenCalledOnce();
    expect(e.stopPropagation).toHaveBeenCalledOnce();
    expect(copyFn).toHaveBeenCalledOnce();
    expect(copied).toEqual(["15M7MCEK4J"]);
  });

  it("mousedown stops propagation so row accordion does not toggle", () => {
    const handlers = createCopyableBagIdPointerHandlers(vi.fn());
    const e = mockEvent();
    handlers.onMouseDown(e);
    expect(e.stopPropagation).toHaveBeenCalledOnce();
  });

  it("Enter/Space keyboard activates copy and stops propagation", () => {
    const copyFn = vi.fn();
    const handlers = createCopyableBagIdPointerHandlers(copyFn);
    for (const key of ["Enter", " "]) {
      const e = mockEvent({ key });
      handlers.onKeyDown(e);
      expect(e.preventDefault).toHaveBeenCalled();
      expect(e.stopPropagation).toHaveBeenCalled();
    }
    expect(copyFn).toHaveBeenCalledTimes(2);
  });

  it("other keys do not copy (text selection / caret movement remains usable)", () => {
    const copyFn = vi.fn();
    const handlers = createCopyableBagIdPointerHandlers(copyFn);
    const e = mockEvent({ key: "ArrowLeft" });
    handlers.onKeyDown(e);
    expect(copyFn).not.toHaveBeenCalled();
    expect(e.preventDefault).not.toHaveBeenCalled();
  });
});
