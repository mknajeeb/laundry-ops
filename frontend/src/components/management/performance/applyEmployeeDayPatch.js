/** Apply authoritative employee_day mutation patches without a full rebuild. */

function empKey(emp) {
  if (emp?.user_id != null && emp.user_id !== "") return `u:${emp.user_id}`;
  return `n:${String(emp?.employee || "").trim().toLowerCase()}`;
}

function sameEmployee(a, b) {
  if (!a || !b) return false;
  if (
    a.user_id != null &&
    a.user_id !== "" &&
    b.user_id != null &&
    b.user_id !== "" &&
    String(a.user_id) === String(b.user_id)
  ) {
    return true;
  }
  const an = String(a.employee || "").trim().toLowerCase();
  const bn = String(b.employee || "").trim().toLowerCase();
  return Boolean(an) && an === bn;
}

function sumEmployees(rows) {
  let orders = 0;
  let lbs = 0;
  let hours = 0;
  let hasHours = false;
  for (const e of rows || []) {
    orders += Number(e.orders_completed) || 0;
    lbs += Number(e.total_pre_lbs) || 0;
    if (e.performance_hours != null || e.session_hours != null) {
      hours += Number(e.performance_hours ?? e.session_hours) || 0;
      hasHours = true;
    }
  }
  lbs = Math.round(lbs * 100) / 100;
  hours = Math.round(hours * 10000) / 10000;
  const bagsHr = hasHours && hours > 0 ? Math.round((orders / hours) * 10000) / 10000 : null;
  const lbsHr = hasHours && hours > 0 ? Math.round((lbs / hours) * 10000) / 10000 : null;
  return {
    orders_completed: orders,
    total_pre_lbs: lbs,
    total_hours: hasHours && hours > 0 ? hours : null,
    session_hours: hasHours && hours > 0 ? hours : null,
    bags_per_hour: bagsHr,
    lbs_per_hour: lbsHr,
    employee_count: (rows || []).length,
    employee_day_count: (rows || []).length,
    average_basis: "weighted_sum_orders_lbs_over_sum_hours",
  };
}

function recomputeSummary(employees) {
  const active = (employees || []).filter(
    (e) =>
      String(e.day_publication_status || e.publication_status || "") !== "EXCLUDED" &&
      !e.excluded_from_metrics
  );
  return sumEmployees(active);
}

function recomputeApprovedSummary(employees) {
  const approved = (employees || []).filter(
    (e) =>
      e.dashboard_rankable === true ||
      String(e.day_publication_status || e.publication_status || "") === "APPROVED"
  );
  return sumEmployees(approved);
}

/**
 * Merge one employee_day into dashboard state.
 * Returns next data object (or prev if patch unusable).
 *
 * Matches by user_id OR employee name so a patch missing user_id still replaces
 * the existing row (never duplicates into Live + Published).
 */
export function applyEmployeeDayPatch(prev, employeeDay) {
  if (!prev || !employeeDay || !employeeDay.employee) return prev;
  const mergeList = (list) => {
    const rows = [...(list || [])];
    const idx = rows.findIndex((e) => sameEmployee(e, employeeDay));
    if (idx >= 0) {
      // Prefer patch fields; keep prior user_id if patch omitted it.
      const prior = rows[idx];
      rows[idx] = {
        ...prior,
        ...employeeDay,
        user_id: employeeDay.user_id != null && employeeDay.user_id !== ""
          ? employeeDay.user_id
          : prior.user_id,
        sessions: employeeDay.sessions != null ? employeeDay.sessions : prior.sessions,
      };
    } else {
      rows.push(employeeDay);
    }
    return rows;
  };
  let employees = mergeList(prev.employees);
  // Deduplicate if a prior bug left both u:id and n:name rows.
  const seen = new Set();
  employees = employees.filter((e) => {
    const k = empKey(e);
    // Also collapse name-only duplicates of a user_id row.
    const nameK = `n:${String(e.employee || "").trim().toLowerCase()}`;
    if (seen.has(k) || (e.user_id != null && seen.has(nameK))) return false;
    seen.add(k);
    if (e.user_id != null) seen.add(nameK);
    return true;
  });
  // Keep excluded_employees mirror in sync.
  const excluded = employees.filter(
    (e) => String(e.day_publication_status || e.publication_status || "") === "EXCLUDED"
  );
  const summary = {
    ...(prev.summary || {}),
    ...recomputeSummary(employees),
  };
  const summaryApproved = {
    ...(prev.summary_approved || {}),
    ...recomputeApprovedSummary(employees),
  };
  // Preserve unmapped counters.
  for (const k of [
    "needs_attribution_count",
    "outside_folder_session_count",
    "unmapped_count",
    "session_count",
  ]) {
    if (prev.summary && prev.summary[k] != null) summary[k] = prev.summary[k];
  }
  return {
    ...prev,
    employees,
    excluded_employees: excluded,
    excluded_employee_count: excluded.length,
    summary,
    summary_active: summary,
    summary_approved: summaryApproved,
  };
}

export function employeeSessionsPayload(employee) {
  if (!employee) return [];
  return (employee.sessions || []).map((s) => ({
    session_id: s.session_id,
    session_code: s.session_code,
    segment_id: s.segment_id,
    user_id: s.user_id ?? employee.user_id,
    employee: employee.employee,
    total_pre_lbs: s.total_pre_lbs,
    performance_hours: s.performance_hours,
    lbs_per_hour: s.lbs_per_hour,
    orders_completed: s.orders_completed,
    start_time: s.start_time,
    end_time: s.end_time,
    performance_end: s.performance_end,
    performance_basis: s.performance_basis,
    role_status: s.role_status,
    include_in_authoritative_aggregate: s.include_in_authoritative_aggregate,
    publication_status: s.publication_status || s.publication?.status,
    publication: s.publication,
  }));
}

/** Partition helpers for tests / UI — same rules as the Performance section. */
export function partitionPublishedLiveExcluded(employees) {
  const rows = employees || [];
  const published = rows.filter(
    (e) =>
      e.dashboard_rankable === true ||
      String(e.day_publication_status || e.publication_status || "") === "APPROVED"
  );
  const live = rows.filter(
    (e) =>
      e.dashboard_rankable !== true &&
      String(e.day_publication_status || e.publication_status || "") !== "APPROVED" &&
      String(e.day_publication_status || e.publication_status || "") !== "EXCLUDED"
  );
  const excluded = rows.filter(
    (e) => String(e.day_publication_status || e.publication_status || "") === "EXCLUDED"
  );
  return { published, live, excluded };
}

export { sameEmployee, empKey };
