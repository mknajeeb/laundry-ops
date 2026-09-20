/** Payroll Time Records — break row action labels (open vs completed). */

export function payrollBreakRowActions(breakRow) {
  const status = String(breakRow?.status || "");
  if (status === "open") {
    return [
      { key: "close", label: "Close Break", emphasis: "primary" },
      { key: "delete", label: "Delete Break", emphasis: "danger" },
    ];
  }
  return [
    { key: "edit", label: "Edit Break", emphasis: "primary" },
    { key: "delete", label: "Delete Break", emphasis: "danger" },
  ];
}

export function formatOpenBreakCaption(breakRow) {
  if (String(breakRow?.status || "") !== "open") return null;
  return "Open — currently not deducted";
}
