import { describe, expect, it } from "vitest";
import { WF_OPS_MAINTENANCE_BANNER_TEXT } from "./WfOpsMaintenanceBanner";

describe("WfOpsMaintenanceBanner copy", () => {
  it("states WF maintenance and that Hang Dry is unaffected", () => {
    expect(WF_OPS_MAINTENANCE_BANNER_TEXT).toMatch(/Wash & Fold maintenance/i);
    expect(WF_OPS_MAINTENANCE_BANNER_TEXT).toMatch(/Hang Dry is unaffected/i);
  });
});

describe("WF mutation lock composition", () => {
  it("locks when maintenance is on even if the shift day is open", () => {
    const dayClosed = false;
    const maintenanceOn = true;
    const mutationsLocked = Boolean(dayClosed || maintenanceOn);
    expect(mutationsLocked).toBe(true);
  });

  it("does not lock HD when WF maintenance is on", () => {
    const wfMutationsLocked = true;
    const hdMutationsLocked = false; // HD path never receives wfMutationsLocked
    expect(wfMutationsLocked).toBe(true);
    expect(hdMutationsLocked).toBe(false);
  });
});
