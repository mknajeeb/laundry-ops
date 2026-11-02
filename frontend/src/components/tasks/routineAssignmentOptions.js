export const WASHER_ROLE = "agroup_washer_cleaning";
export const FLOOR_ROLE = "agroup_floor_sweeping";
export const DRYER_ROLE = "agroup_dryer_lint";
export const LEGACY_COMBINED_ROLE = "agroup_floor_washer";

const COVERED_BY_GROUP = {
  custom_check_washer_residue: WASHER_ROLE,
  washer_cleaning: WASHER_ROLE,
  floor_cleaning: FLOOR_ROLE,
  lint_cleaning: DRYER_ROLE,
};

function activeCodes(catalog) {
  return new Set(
    (catalog || [])
      .filter((role) => role && role.active !== false && role.active !== 0 && role.active !== "0")
      .map((role) => role.code)
  );
}

export function hiddenRoutineAssignmentCodes(catalog) {
  const active = activeCodes(catalog);
  const hidden = new Set();
  for (const [taskCode, groupCode] of Object.entries(COVERED_BY_GROUP)) {
    if (active.has(groupCode)) hidden.add(taskCode);
  }
  if ([WASHER_ROLE, FLOOR_ROLE, DRYER_ROLE].every((code) => active.has(code))) {
    hidden.add(LEGACY_COMBINED_ROLE);
  }
  return hidden;
}

export function routineAssignmentOptions(catalog) {
  const hidden = hiddenRoutineAssignmentCodes(catalog);
  return (catalog || [])
    .filter((role) => role && role.uses_time_slots === false && role.active !== false)
    .filter((role) => !hidden.has(role.code))
    .map((role) => ({
      value: role.code,
      label: String(role.code || "").startsWith("agroup_")
        ? `Activity: ${role.name || role.code}`
        : role.name || role.code,
      group: String(role.code || "").startsWith("agroup_"),
    }))
    .sort((a, b) => Number(b.group) - Number(a.group) || a.label.localeCompare(b.label));
}
