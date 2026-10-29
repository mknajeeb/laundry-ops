export const TASK_DRAG_TYPE = "application/x-weekly-task";

export function isSharedAssignment(item) {
  const ids = item?.user_ids || [];
  return item?.execution_mode === "shared" && ids.length >= 2;
}

export function taskDragPayload(item) {
  return JSON.stringify({
    id: item.id,
    user_id: item.user_id,
    day_of_week: item.day_of_week,
    shared: isSharedAssignment(item),
  });
}

export function parseTaskDrag(raw) {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.id) return null;
    return parsed;
  } catch {
    return null;
  }
}

/** New order when a card is dropped onto another card in the same cell. */
export function reorderIds(ids, movingId, beforeId) {
  const list = (ids || []).map(Number).filter((id) => id !== Number(movingId));
  const index = beforeId == null ? list.length : list.indexOf(Number(beforeId));
  list.splice(index < 0 ? list.length : index, 0, Number(movingId));
  return list;
}

export function unscheduledNames(entries, userIds, dayOfWeek, nameFor) {
  return (userIds || [])
    .map(Number)
    .filter(
      (userId) =>
        !(entries || []).some(
          (entry) => Number(entry.user_id) === userId && Number(entry.day_of_week) === Number(dayOfWeek),
        ),
    )
    .map((userId) => nameFor(userId));
}
