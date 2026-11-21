import { describe, expect, it } from "vitest";
import {
  chronologyMetrics,
  recordedSessionContext,
  scanEmployee,
  serviceTypesParam,
  userActivityRows,
} from "./pinScanModel";

describe("scan chronology mobile model", () => {
  it("counts recorded scans when no session exists", () => {
    const data = {
      summary: { total_stage_seconds: 0 },
      sessions: [
        { bag_id: "B1", employee: "Ana Rivera", local_session_id: null, session_status: "unassigned" },
        { bag_id: "B2", employee: "", local_session_id: null, session_status: "unassigned" },
      ],
      local_sessions: {
        summary: {
          total_scans: 170,
          unassigned_scans: 170,
          total_sessions: 0,
          total_hours: 0,
        },
      },
    };
    const metrics = Object.fromEntries(
      chronologyMetrics("weighing", data).map((row) => [row.labelKey, row.value]),
    );
    expect(metrics["pinMgmt.scans"]).toBe(2);
    expect(metrics["pinMgmt.withEmployee"]).toBe(1);
    expect(metrics["pinMgmt.unassigned"]).toBeUndefined();
    expect(scanEmployee(data.sessions[0])).toBe("Ana Rivera");
    expect(scanEmployee(data.sessions[1])).toBe("");
    expect(recordedSessionContext(data)).toBeNull();
  });

  it("keeps a recorded session separate from the scan count", () => {
    const context = recordedSessionContext({
      local_sessions: { summary: { total_sessions: 1, total_hours: 1.5 } },
    });
    expect(context).toEqual({ sessions: 1, hours: 1.5 });
  });

  it("lists only recorded user activities", () => {
    const rows = userActivityRows({
      employee_groups: [
        {
          employee: "Ana",
          activities: [{ activity_type: "weighing", time_et: "2026-11-21 09:00:00", bag_id: "B1" }],
        },
      ],
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].employee).toBe("Ana");
    expect(userActivityRows({})).toEqual([]);
  });

  it("builds the existing service-type filter", () => {
    expect(serviceTypesParam(true, true)).toBe("");
    expect(serviceTypesParam(true, false)).toBe("WF");
    expect(serviceTypesParam(false, true)).toBe("HD");
    expect(serviceTypesParam(false, false)).toBe("none");
  });
});
