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
          dashboard_rankable: true,
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
          dashboard_rankable: true,
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
      dashboard_rankable: true,
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
    expect(out.summary_approved.orders_completed).toBe(18);
    expect(out.summary_approved.employee_day_count).toBe(2);
  });

  it("partial day stays in live summary but drops from approved summary", () => {
    const prev = {
      employees: [
        {
          employee: "Maria",
          user_id: 59,
          orders_completed: 12,
          total_pre_lbs: 240,
          performance_hours: 5,
          day_publication_status: "APPROVED",
          dashboard_rankable: true,
        },
      ],
      summary: {},
    };
    const out = applyEmployeeDayPatch(prev, {
      employee: "Maria",
      user_id: 59,
      orders_completed: 12,
      total_pre_lbs: 240,
      performance_hours: 5,
      day_publication_status: "PARTIALLY_APPROVED",
      dashboard_rankable: false,
    });
    expect(out.summary.employee_day_count).toBe(1);
    expect(out.summary.lbs_per_hour).toBe(48);
    expect(out.summary_approved.employee_day_count).toBe(0);
  });
});

describe("employeeSessionsPayload", () => {
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
