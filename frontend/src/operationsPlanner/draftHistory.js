/** Undo and redo for planner drafts that have not been saved. */

export function recordDraft(history, future, draft, next) {
  return { history: [...history, draft], future: [], draft: next };
}

export function undoDraftHistory(history, future, draft) {
  if (!history.length) return { history, future, draft };
  const previous = history[history.length - 1];
  return {
    history: history.slice(0, -1),
    future: [draft, ...future],
    draft: previous,
  };
}

export function redoDraftHistory(history, future, draft) {
  if (!future.length) return { history, future, draft };
  const next = future[0];
  return {
    history: [...history, draft],
    future: future.slice(1),
    draft: next,
  };
}
