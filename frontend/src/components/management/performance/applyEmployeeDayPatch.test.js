import {
  applyEmployeeDayPatch,
  employeeSessionsPayload,
  partitionPublishedLiveExcluded,
} from "./applyEmployeeDayPatch";

/**
 * Simulate the backend mutation_employee_day compose that stamps one session
 * then derives day_publication_status / dashboard_rankable.
 */
function stampSessionAndCompose(employeeDay, sessionId, status) {
  const sessions = (employeeDay.sessions || []).map((s) => {
    if (String(s.session_id) !== String(sessionId)) return { ...s };
    return {
      ...s,
      publication_status: status,
      publication: { ...(s.publication || {}), status, excluded: status === "EXCLUDED" },
    };
  });
  const included = sessions.filter((s) => (s.publication_status || s.publication?.status) !== "EXCLUDED");
  const approved = included.filter((s) => (s.publication_status || s.publication?.status) === "APPROVED");
  let dayStatus = "NEEDS_APPROVAL";
  if (included.length === 0) dayStatus = "EXCLUDED";
  else if (approved.length === included.length) dayStatus = "APPROVED";
  else if (approved.length > 0) dayStatus = "PARTIALLY_APPROVED";
  return {
    ...employeeDay,
    sessions,
    day_publication_status: dayStatus,
    publication_status: dayStatus,
    dashboard_rankable: dayStatus === "APPROVED",
  };
}

function tarannumInitial() {
  return {
    employee: "Tarannum",
    user_id: 42,
    orders_completed: 30,
    total_pre_lbs: 600,
    performance_hours: 8,
    lbs_per_hour: 75,
    day_publication_status: "PARTIALLY_APPROVED",
    dashboard_rankable: false,
    sessions: [
      {
        session_id: "wf01",
        session_code: "WF-01",
        publication_status: "UNAPPROVED",
        publication: { status: "UNAPPROVED" },
        orders_completed: 10,
        total_pre_lbs: 200,
        performance_hours: 3,
        role_status: "closed",
      },
      {
        session_id: "wf02",
        session_code: "WF-02",
        publication_status: "UNAPPROVED",
        publication: { status: "UNAPPROVED" },
        orders_completed: 10,
        total_pre_lbs: 200,
        performance_hours: 2.5,
        role_status: "closed",
      },
      {
        session_id: "wf03",
        session_code: "WF-03",
        publication_status: "APPROVED",
        publication: { status: "APPROVED" },
        orders_completed: 10,
        total_pre_lbs: 200,
        performance_hours: 2.5,
        role_status: "closed",
      },
    ],
  };
}

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

  it("merges name-only patch onto existing user_id row without duplicating", () => {
    const prev = {
      employees: [tarannumInitial()],
      summary: {},
      summary_approved: {},
    };
    // Bug reproduction: API returned employee_day without user_id.
    const patch = {
      ...stampSessionAndCompose(tarannumInitial(), "wf01", "APPROVED"),
      user_id: null,
    };
    const out = applyEmployeeDayPatch(prev, patch);
    expect(out.employees).toHaveLength(1);
    expect(out.employees[0].user_id).toBe(42);
    expect(out.employees[0].day_publication_status).toBe("PARTIALLY_APPROVED");
    expect(out.employees[0].sessions.find((s) => s.session_code === "WF-01").publication_status).toBe(
      "APPROVED"
    );
  });
});

describe("Tarannum 3-session approve → Published (mutation patch only)", () => {
  it("approve WF-01 then WF-02 moves one employee-day Live → Published before reconcile GET", () => {
    let data = {
      employees: [tarannumInitial()],
      summary: {},
      summary_approved: {},
    };
    let reviewModal = data.employees[0];

    // --- Approve WF-01 ---
    const after01 = stampSessionAndCompose(reviewModal, "wf01", "APPROVED");
    // Simulate response that may omit user_id (production bug path).
    data = applyEmployeeDayPatch(data, { ...after01, user_id: null });
    reviewModal = data.employees.find((e) => e.employee === "Tarannum");

    expect(reviewModal.sessions.find((s) => s.session_code === "WF-01").publication_status).toBe(
      "APPROVED"
    );
    expect(reviewModal.day_publication_status).toBe("PARTIALLY_APPROVED");
    expect(reviewModal.dashboard_rankable).toBe(false);
    {
      const { published, live } = partitionPublishedLiveExcluded(data.employees);
      expect(published.map((e) => e.employee)).not.toContain("Tarannum");
      expect(live).toHaveLength(1);
      expect(live[0].employee).toBe("Tarannum");
    }
    expect(data.summary_approved.employee_day_count).toBe(0);
    // Rates unchanged by approval alone.
    expect(reviewModal.orders_completed).toBe(30);
    expect(reviewModal.total_pre_lbs).toBe(600);
    expect(reviewModal.lbs_per_hour).toBe(75);

    // --- Approve WF-02 (using modal state after first patch) ---
    const after02 = stampSessionAndCompose(reviewModal, "wf02", "APPROVED");
    data = applyEmployeeDayPatch(data, after02);
    reviewModal = data.employees.find((e) => e.employee === "Tarannum");

    expect(reviewModal.day_publication_status).toBe("APPROVED");
    expect(reviewModal.dashboard_rankable).toBe(true);
    expect(reviewModal.sessions.every((s) => s.publication_status === "APPROVED")).toBe(true);
    {
      const { published, live } = partitionPublishedLiveExcluded(data.employees);
      expect(live.map((e) => e.employee)).not.toContain("Tarannum");
      expect(published).toHaveLength(1);
      expect(published[0].employee).toBe("Tarannum");
      expect(published[0].user_id).toBe(42);
    }
    expect(data.summary_approved.employee_day_count).toBe(1);
    expect(data.summary_approved.orders_completed).toBe(30);
    expect(data.summary.employee_day_count).toBe(1);
    // Still exactly one observation.
    expect(data.employees.filter((e) => e.employee === "Tarannum")).toHaveLength(1);

    // --- Disapprove WF-03 → back to Live / Partial ---
    const afterDis = stampSessionAndCompose(reviewModal, "wf03", "UNAPPROVED");
    data = applyEmployeeDayPatch(data, afterDis);
    reviewModal = data.employees.find((e) => e.employee === "Tarannum");
    expect(reviewModal.day_publication_status).toBe("PARTIALLY_APPROVED");
    expect(reviewModal.dashboard_rankable).toBe(false);
    {
      const { published, live } = partitionPublishedLiveExcluded(data.employees);
      expect(published).toHaveLength(0);
      expect(live).toHaveLength(1);
      expect(live[0].employee).toBe("Tarannum");
    }
    expect(data.summary_approved.employee_day_count).toBe(0);
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
