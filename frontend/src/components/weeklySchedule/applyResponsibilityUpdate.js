/** Merge a task-assignment response into the schedule already on screen.

Shift hours, attendance, breaks, and the employee list stay as they are.
Only the returned assignment cards are replaced, and removed ids leave the grid.
*/
export function applyResponsibilityUpdate(current, response) {
  const patch = response?.responsibility_update;
  if (!patch || !current) return current;
  const removed = new Set((patch.removed_ids || []).map((id) => Number(id)));
  const incoming = Array.isArray(patch.responsibilities) ? patch.responsibilities : [];
  const incomingIds = new Set(incoming.map((row) => Number(row.id)));
  const kept = (current.daily_responsibilities || []).filter(
    (row) => !removed.has(Number(row.id)) && !incomingIds.has(Number(row.id)),
  );
  return {
    ...current,
    daily_responsibilities: [...kept, ...incoming],
    template_sync: Object.prototype.hasOwnProperty.call(response, "template_sync")
      ? response.template_sync
      : current.template_sync,
  };
}

/** Task writes return a patch. Shift writes still return the whole week. */
export function mergeScheduleMutation(current, response) {
  if (!response) return current;
  if (response.responsibility_update && current) return applyResponsibilityUpdate(current, response);
  return response;
}
