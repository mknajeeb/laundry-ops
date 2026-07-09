export function parseMoneyInput(val) {
  if (val === "" || val === null || val === undefined) return 0;
  const n = Number(String(val).replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

export function parseIntInput(val) {
  if (val === "" || val === null || val === undefined) return 0;
  const n = parseInt(String(val).replace(/[^0-9-]/g, ""), 10);
  return Number.isFinite(n) ? n : 0;
}

export function formatCurrency(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatPercent(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "0.0%";
  return `${n.toFixed(1)}%`;
}

export const DRC_SECTION_CARD_SX = {
  borderRadius: 2,
  p: { xs: 2, sm: 2.5 },
  mb: 2,
  border: "1px solid",
  borderColor: "divider",
};

export const DRC_INPUT_SX = {
  "& .MuiInputBase-input": {
    fontSize: { xs: "1.1rem", sm: "1rem" },
    py: { xs: 1.5, sm: 1 },
  },
};

export const DRC_STICKY_SAVE_SX = {
  position: "fixed",
  bottom: 0,
  left: 0,
  right: 0,
  zIndex: 1100,
  p: 2,
  pb: "calc(16px + env(safe-area-inset-bottom))",
  bgcolor: "background.paper",
  borderTop: "1px solid",
  borderColor: "divider",
  boxShadow: "0 -4px 12px rgba(0,0,0,0.08)",
  display: { xs: "block", md: "none" },
};

export const DRC_NAV_SX = {
  position: "sticky",
  top: 0,
  zIndex: 10,
  bgcolor: "background.paper",
  borderBottom: "1px solid",
  borderColor: "divider",
  mb: 2,
};

export function emptyDailyEntryForm() {
  return {
    self_service_cash: "",
    self_service_card: "",
    drop_off_cash: "",
    drop_off_card: "",
    rinse_wf_pounds: "",
    rinse_hd_orders: "",
    rinse_hd_revenue: "",
    rinse_wi_orders: "",
    rinse_wi_revenue: "",
    payroll_total: "",
    commercial_lines: [],
  };
}

export function entryToForm(entry) {
  if (!entry) return emptyDailyEntryForm();
  return {
    self_service_cash: entry.self_service_cash ?? "",
    self_service_card: entry.self_service_card ?? "",
    drop_off_cash: entry.drop_off_cash ?? "",
    drop_off_card: entry.drop_off_card ?? "",
    rinse_wf_pounds: entry.rinse_wf_pounds ?? "",
    rinse_hd_orders: entry.rinse_hd_orders ?? "",
    rinse_hd_revenue: entry.rinse_hd_revenue ?? "",
    rinse_wi_orders: entry.rinse_wi_orders ?? "",
    rinse_wi_revenue: entry.rinse_wi_revenue ?? "",
    payroll_total: entry.payroll_total ?? "",
    commercial_lines: (entry.commercial_lines || []).map((line) => ({
      commercial_account_id: line.commercial_account_id,
      account_name: line.account_name,
      pounds: line.pounds ?? "",
      rate_per_pound: line.rate_per_pound ?? "",
      logistics_charge: line.logistics_charge ?? "",
      additional_charge: line.additional_charge ?? "",
      revenue: line.revenue ?? 0,
    })),
  };
}

export function formToPayload(form, overrideReasons = {}) {
  return {
    self_service_cash: parseMoneyInput(form.self_service_cash),
    self_service_card: parseMoneyInput(form.self_service_card),
    drop_off_cash: parseMoneyInput(form.drop_off_cash),
    drop_off_card: parseMoneyInput(form.drop_off_card),
    rinse_wf_pounds: parseMoneyInput(form.rinse_wf_pounds),
    rinse_hd_orders: parseIntInput(form.rinse_hd_orders),
    rinse_hd_revenue: parseMoneyInput(form.rinse_hd_revenue),
    rinse_wi_orders: parseIntInput(form.rinse_wi_orders),
    rinse_wi_revenue: parseMoneyInput(form.rinse_wi_revenue),
    payroll_total: parseMoneyInput(form.payroll_total),
    commercial_lines: (form.commercial_lines || []).map((line) => ({
      commercial_account_id: line.commercial_account_id,
      pounds: parseMoneyInput(line.pounds),
      rate_per_pound: parseMoneyInput(line.rate_per_pound),
      logistics_charge: parseMoneyInput(line.logistics_charge),
      additional_charge: parseMoneyInput(line.additional_charge),
    })),
    overrides: buildDrcOverridePayload(overrideReasons),
  };
}

export const DRC_ENTRY_STATUS = {
  OPEN: "open",
  LOCKED: "locked",
  SUBMITTED: "submitted",
  APPROVED: "approved",
  REJECTED: "rejected",
};

export function isDrcEntryEditable(status) {
  return String(status || DRC_ENTRY_STATUS.OPEN) === DRC_ENTRY_STATUS.OPEN;
}

export function getDrcStatusChipColor(status) {
  switch (String(status || DRC_ENTRY_STATUS.OPEN)) {
    case DRC_ENTRY_STATUS.LOCKED:
      return "warning";
    case DRC_ENTRY_STATUS.SUBMITTED:
      return "info";
    case DRC_ENTRY_STATUS.APPROVED:
      return "success";
    case DRC_ENTRY_STATUS.REJECTED:
      return "error";
    default:
      return "default";
  }
}

export function getDrcStatusLabel(status) {
  const key = String(status || DRC_ENTRY_STATUS.OPEN);
  return key.charAt(0).toUpperCase() + key.slice(1);
}

/** Workflow actions available for the current entry status (requires saved entry). */
export function getDrcWorkflowActions(status, hasEntry = true) {
  if (!hasEntry) return [];
  const s = String(status || DRC_ENTRY_STATUS.OPEN);
  if (s === DRC_ENTRY_STATUS.OPEN) return ["lock", "submit"];
  if (s === DRC_ENTRY_STATUS.SUBMITTED) return ["approve", "reject"];
  if (s === DRC_ENTRY_STATUS.REJECTED) return ["reopen"];
  return [];
}

export function drcWorkflowActionLabel(action) {
  switch (action) {
    case "lock":
      return "Lock";
    case "submit":
      return "Submit";
    case "approve":
      return "Approve";
    case "reject":
      return "Reject";
    case "reopen":
      return "Reopen";
    default:
      return action;
  }
}

export function drcWorkflowConfirmMessage(action, entryDate) {
  const dateLabel = entryDate || "this date";
  switch (action) {
    case "lock":
      return `Lock the entry for ${dateLabel}? It will become read-only.`;
    case "submit":
      return `Submit the entry for ${dateLabel} for review?`;
    case "approve":
      return `Approve the entry for ${dateLabel}?`;
    case "reject":
      return `Reject the entry for ${dateLabel}?`;
    case "reopen":
      return `Reopen the rejected entry for ${dateLabel} for editing?`;
    default:
      return `Apply "${action}" to the entry for ${dateLabel}?`;
  }
}

export function drcWorkflowSupportsNotes(action) {
  return action === "reject" || action === "reopen";
}

export const DRC_SOURCE_MANUAL = "manual";

export const DRC_LINE_KEYS = {
  self_service_cash: "revenue.self_service.cash",
  self_service_card: "revenue.self_service.card",
  drop_off_cash: "revenue.drop_off.cash",
  drop_off_card: "revenue.drop_off.card",
  rinse_wf_pounds: "revenue.rinse_wf.pounds",
  rinse_hd_orders: "revenue.rinse_hd.orders",
  rinse_hd_revenue: "revenue.rinse_hd.amount",
  rinse_wi_orders: "revenue.rinse_wi.orders",
  rinse_wi_revenue: "revenue.rinse_wi.amount",
  payroll_total: "payroll.total",
};

export function commercialPoundsLineKey(accountId) {
  return `revenue.commercial.${accountId}.pounds`;
}

export const DRC_SOURCE_LABELS = {
  manual: "Manual",
  workload: "Workload",
  productivity: "Productivity",
  payroll: "Payroll",
  pos: "POS",
  stripe: "Stripe",
  cleancloud: "CleanCloud",
  accounting: "Accounting",
};

export function getDrcSourceLabel(sourceSystem) {
  const key = String(sourceSystem || DRC_SOURCE_MANUAL).toLowerCase();
  return DRC_SOURCE_LABELS[key] || key.charAt(0).toUpperCase() + key.slice(1);
}

/** gray = manual, blue = imported, orange = manual override */
export function getDrcSourceIndicatorStyle(meta) {
  if (!meta) {
    return { color: "default", variant: "outlined", label: "Manual" };
  }
  if (meta.is_manual_override) {
    return { color: "warning", variant: "filled", label: "Override" };
  }
  const source = String(meta.source_system || DRC_SOURCE_MANUAL).toLowerCase();
  if (source === DRC_SOURCE_MANUAL) {
    return { color: "default", variant: "outlined", label: "Manual" };
  }
  return { color: "info", variant: "filled", label: getDrcSourceLabel(source) };
}

export function isImportedDrcSource(meta) {
  if (!meta) return false;
  return String(meta.source_system || DRC_SOURCE_MANUAL).toLowerCase() !== DRC_SOURCE_MANUAL;
}

export function normalizeDrcFieldValue(field, value) {
  if (["rinse_hd_orders", "rinse_wi_orders"].includes(field)) {
    return parseIntInput(value);
  }
  return parseMoneyInput(value);
}

export function drcFieldValuesEqual(field, a, b) {
  return normalizeDrcFieldValue(field, a) === normalizeDrcFieldValue(field, b);
}

export function buildDrcOverridePayload(overrideReasons) {
  const overrides = {};
  Object.entries(overrideReasons || {}).forEach(([lineKey, reason]) => {
    if (reason && String(reason).trim()) {
      overrides[lineKey] = { is_manual_override: true, reason: String(reason).trim() };
    }
  });
  return overrides;
}

/**
 * Fields changed from imported baseline that still need an override reason.
 * Returns [{ lineKey, fieldLabel, sourceLabel, field?, commercialIndex? }]
 */
export function fieldsNeedingOverrideReason({ baselineForm, form, lineSources, overrideReasons, commercialAccountIds }) {
  const needs = [];
  const reasons = overrideReasons || {};

  Object.entries(DRC_LINE_KEYS).forEach(([field, lineKey]) => {
    const meta = lineSources?.[lineKey];
    if (!isImportedDrcSource(meta)) return;
    if (!drcFieldValuesEqual(field, baselineForm?.[field], form?.[field])) {
      if (!reasons[lineKey]?.trim()) {
        needs.push({
          lineKey,
          field,
          fieldLabel: drcFieldLabel(field),
          sourceLabel: getDrcSourceLabel(meta.source_system),
        });
      }
    }
  });

  (form?.commercial_lines || []).forEach((line, index) => {
    const aid = line.commercial_account_id;
    const lineKey = commercialPoundsLineKey(aid);
    const meta = lineSources?.[lineKey];
    if (!isImportedDrcSource(meta)) return;
    const baselineLine = (baselineForm?.commercial_lines || []).find((l) => l.commercial_account_id === aid);
    if (!drcFieldValuesEqual("pounds", baselineLine?.pounds, line.pounds) && !reasons[lineKey]?.trim()) {
      needs.push({
        lineKey,
        field: "pounds",
        fieldLabel: `${line.account_name || "Commercial"} pounds`,
        sourceLabel: getDrcSourceLabel(meta.source_system),
        commercialIndex: index,
      });
    }
  });

  return needs;
}

export function drcFieldLabel(field) {
  const labels = {
    self_service_cash: "Self Service Cash",
    self_service_card: "Self Service Card",
    drop_off_cash: "Drop Off Cash",
    drop_off_card: "Drop Off Card",
    rinse_wf_pounds: "Rinse WF Pounds",
    rinse_hd_orders: "Rinse HD Orders",
    rinse_hd_revenue: "Rinse HD Revenue",
    rinse_wi_orders: "Rinse WI Orders",
    rinse_wi_revenue: "Rinse WI Revenue",
    payroll_total: "Payroll Total",
  };
  return labels[field] || field;
}
