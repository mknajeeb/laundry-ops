/** Time Records payroll classification display. Session override, not role segments. */

export const CLASSIFICATION_OVERRIDE_OPTIONS = [
  { value: "", label: "Use employee default" },
  { value: "w2", label: "W-2" },
  { value: "contractor_1099", label: "1099" },
  { value: "temp", label: "Temp / One-Time" },
];

const CATEGORY_SHORT = {
  w2: "W-2",
  contractor_1099: "1099",
  temp: "Temp",
  tryout: "Try Out",
};

export function formatRecordClassificationLabel(row) {
  const code = row?.worker_category;
  const short = CATEGORY_SHORT[code] || row?.worker_category_label || code || "";
  if (row?.classification_source === "record_override") {
    return `${short} · Record override`;
  }
  return short;
}

export function classificationSelectValue(row) {
  if (
    row?.classification_source === "record_override" &&
    CLASSIFICATION_OVERRIDE_OPTIONS.some((opt) => opt.value && opt.value === row.worker_category)
  ) {
    return row.worker_category;
  }
  return "";
}
