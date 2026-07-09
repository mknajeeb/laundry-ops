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

export function formToPayload(form) {
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
