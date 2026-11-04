/** Keep checklist responsibility inside the employees assigned to this task. */

export function reconcileChecklistAssignment(items, employeeIds) {
  const roster = new Set((employeeIds || []).map(Number));
  const released = [];
  const next = (items || []).map((item) => {
    if (item?.responsibility_mode !== "named") return item;
    const previous = (item.user_ids || []).map(Number);
    const kept = previous.filter((id) => roster.has(id));
    if (kept.length === previous.length) return item;
    const mode = kept.length ? "named" : "team";
    released.push({
      task_name: item.task_name || item.task_code,
      removed_user_ids: previous.filter((id) => !roster.has(id)),
      kept_user_ids: kept,
      mode,
    });
    return {
      ...item,
      responsibility_mode: mode,
      user_ids: kept,
      dirty: true,
    };
  });
  return { items: next, released };
}

export function rosterReleaseNote(released, nameFor) {
  if (!released?.length) return "";
  return released
    .map((row) => {
      const names = (row.removed_user_ids || []).map((id) => nameFor(id)).filter(Boolean);
      const who = names.join(", ") || "That employee";
      const verb = names.length > 1 ? "were" : "was";
      if (row.mode === "named") {
        const kept = (row.kept_user_ids || []).map((id) => nameFor(id)).filter(Boolean).join(", ");
        return `${who} ${verb} removed. ${row.task_name} stays with ${kept}.`;
      }
      return `${who} ${verb} removed. ${row.task_name} is any assigned employee again.`;
    })
    .join(" ");
}
