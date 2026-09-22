import { applyEmployeeDayPatch, employeeSessionsPayload } from "./applyEmployeeDayPatch";

describe("applyEmployeeDayPatch", () => {
  it("updates employee-day and recomputes weighted summary without full reload", () => {
    const prev = {
      employees: [
        {
          employee: "Maria Rodriguez (Veewash)",
          user_id: 59,
          orders_completed: 12,
          total_pre_lbs: 240,
          performance_hours: 5,
          lbs_per_hour: 48,
          day_publication_status: "APPROVED",
          sessions: [{ session_id: "2001" }, { session_id: "2002" }],
        },
        {
          employee: "Other",
          user_id: 1,
          orders_completed: 10,
          total_pre_lbs: 200,
          performance_hours: 4,
          lbs_per_hour: 50,
          day_publication_status: "APPROVED",
        },
      ],
      summary: { needs_attribution_count: 3 },
    };
    const nextDay = {
      employee: "Maria Rodriguez (Veewash)",
      user_id: 59,
      orders_completed: 8,
      total_pre_lbs: 160,
      performance_hours: 3,
      lbs_per_hour: 53.3333,
      day_publication_status: "APPROVED",
      excluded_session_count: 1,
      sessions: [
        { session_id: "2001", publication_status: "APPROVED" },
        { session_id: "2002", publication_status: "EXCLUDED" },
      ],
    };
    const out = applyEmployeeDayPatch(prev, nextDay);
    expect(out.employees.find((e) => e.user_id === 59).orders_completed).toBe(8);
    expect(out.summary.orders_completed).toBe(18);
    expect(out.summary.total_pre_lbs).toBe(360);
    expect(out.summary.total_hours).toBe(7);
    expect(out.summary.needs_attribution_count).toBe(3);
  });

  it("employeeSessionsPayload preserves publication stamps", () => {
    const rows = employeeSessionsPayload({
      employee: "Maria",
      user_id: 59,
      sessions: [
        {
          session_id: "1",
          publication_status: "EXCLUDED",
          publication: { status: "EXCLUDED" },
          total_pre_lbs: 10,
          performance_hours: 1,
          orders_completed: 1,
        },
      ],
    });
    expect(rows[0].publication_status).toBe("EXCLUDED");
    expect(rows[0].employee).toBe("Maria");
  });
});
