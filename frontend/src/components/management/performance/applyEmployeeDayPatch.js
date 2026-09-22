/** Apply authoritative employee_day mutation patches without a full rebuild. */

function empKey(emp) {
  if (emp?.user_id != null && emp.user_id !== "") return `u:${emp.user_id}`;
  return `n:${String(emp?.employee || "").trim().toLowerCase()}`;
}

function recomputeSummary(employees) {
  const active = (employees || []).filter(
    (e) =>
      String(e.day_publication_status || e.publication_status || "") !== "EXCLUDED" &&
      !e.excluded_from_metrics
  );
  let orders = 0;
  let lbs = 0;
  let hours = 0;
  let hasHours = false;
  for (const e of active) {
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
    employee_count: active.length,
    employee_day_count: active.length,
    average_basis: "weighted_sum_orders_lbs_over_sum_hours",
  };
}

/**
 * Merge one employee_day into dashboard state.
 * Returns next data object (or prev if patch unusable).
 */
export function applyEmployeeDayPatch(prev, employeeDay) {
  if (!prev || !employeeDay || !employeeDay.employee) return prev;
  const key = empKey(employeeDay);
  const mergeList = (list) => {
    const rows = [...(list || [])];
    const idx = rows.findIndex((e) => empKey(e) === key);
    if (idx >= 0) {
      rows[idx] = { ...rows[idx], ...employeeDay };
    } else {
      rows.push(employeeDay);
    }
    return rows;
  };
  let employees = mergeList(prev.employees);
  // Keep excluded_employees mirror in sync.
  const excluded = employees.filter(
    (e) => String(e.day_publication_status || e.publication_status || "") === "EXCLUDED"
  );
  const summary = {
    ...(prev.summary || {}),
    ...recomputeSummary(employees),
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
