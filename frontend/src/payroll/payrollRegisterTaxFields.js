/** Payroll register line items — finance enters these after accountant confirms payroll. */

export const PAYROLL_REGISTER_EMPLOYEE_TAX_FIELDS = [
  { key: "fit", label: "FWT", helper: "Federal withholding tax" },
  { key: "ss", label: "SS W/H", helper: "Social Security withholding" },
  { key: "medicare", label: "MC W/H", helper: "Medicare withholding" },
  { key: "state", label: "NY State Tax" },
  { key: "local", label: "NYC Resident Tax" },
  { key: "other2", label: "NY SDI" },
  { key: "other1", label: "NY PFML" },
];

export const PAYROLL_REGISTER_EMPLOYER_TAX_FIELDS = [
  { key: "er_ss", label: "ER SS" },
  { key: "er_medicare", label: "ER MC" },
  { key: "futa", label: "FUTA" },
  { key: "suta", label: "NY SUTA" },
  { key: "ny_reemploy", label: "NY Re-employ" },
];

/** Accountant summary table columns (grouped where helpful). */
export const PAYROLL_REGISTER_DEDUCTION_COLUMNS = [
  { key: "fit", label: "FWT" },
  { key: "ss", label: "SS W/H" },
  { key: "medicare", label: "MC W/H" },
  { key: "state", label: "NY State" },
  { key: "local", label: "NYC" },
  { key: "other2", label: "NY SDI" },
  { key: "other1", label: "NY PFML" },
];

export function sumEmployeeRegisterTaxes(deductions) {
  return PAYROLL_REGISTER_EMPLOYEE_TAX_FIELDS.reduce((sum, field) => {
    const n = Number(deductions?.[field.key]);
    return sum + (Number.isFinite(n) ? n : 0);
  }, 0);
}

export function sumEmployerRegisterTaxes(employerTaxes) {
  return PAYROLL_REGISTER_EMPLOYER_TAX_FIELDS.reduce((sum, field) => {
    const n = Number(employerTaxes?.[field.key]);
    return sum + (Number.isFinite(n) ? n : 0);
  }, 0);
}
